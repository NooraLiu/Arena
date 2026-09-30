import random
from collections import Counter, defaultdict
from typing import Dict, List
from .models import (Zone, PlayerState, GameState, Move, Draw, Attack, CardType, Card,
                     PlantBomb, TradeCard, Bomb, Message, StealCard, CraftWeapon, CraftShield, PoisonFood, EatFood,
                     PeekIdentity, FeedFood)
from .map import legal_moves
from .deck import draw as deck_draw, enforce_hand_limit
from .combat import resolve_attack
from .players.base import Observation, Player
from .events import Event, EventLog
from . import config
from . import skills
from . import identities


class Engine:
    def __init__(self, state: GameState, players_by_seat: Dict[int, Player],
                 rng: random.Random = None, log: EventLog = None):
        self.state = state
        self.players_by_seat = players_by_seat
        self.rng = rng or random.Random()
        self.log = log or EventLog()
        self.kills = Counter()               # seat -> kills credited
        self.last_attacker = {}              # victim seat -> last attacker seat
        self.killer_of = {}                  # dead seat -> killer seat (at death)
        self.deaths_by_round = []            # [(round, [seats]) ...] in elimination order
        self.died_with_advanced = {}         # dead seat -> #advanced weapons held at death
        self.ever_attacked = set()           # seats that used violence (by choice) before the final three
        self.gives = Counter()               # (giver, receiver) -> cards handed over
        self.reached_final3 = set()          # seats alive when count first <= 3
        self.messages = []                   # dialogue log (public + private)
        self.declarations = {}               # seat -> list of (guess_seat, guess_identity)
        self.known_identities = defaultdict(dict)  # seat -> {seat: identity} learned privately (Iris)
        self.peek_used = set()               # seats that spent their once-per-game peek

    def __setstate__(self, d):
        """Unpickle a game saved before two-way exchange tracking: its gifts can't be split by
        direction, so the exchange count starts fresh."""
        self.__dict__.update(d)
        self.__dict__.setdefault("gives", Counter())

    def alive_players(self) -> List[PlayerState]:
        return [p for p in self.state.players if p.alive]

    def _p(self, seat: int) -> PlayerState:
        return next(p for p in self.state.players if p.seat == seat)

    def _skill(self, p: PlayerState):
        return skills.for_character(p.character.name)

    def post_message(self, sender_seat, to_seat, text):
        self.messages.append(Message(self.state.round_no, sender_seat, to_seat, text))
        self.log.record(Event("say", self.state.round_no, sender_seat,
                              "public" if to_seat is None else "private",
                              {"to": to_seat, "text": text}))

    def visible_messages(self, seat):
        return [m for m in self.messages if m.to is None or m.to == seat or m.sender == seat]

    async def negotiation_phase(self):
        for p in self.alive_players():
            obs = build_observation(self, p.seat)
            msgs = await self.players_by_seat[p.seat].decide_messages(obs)
            for m in msgs[:config.MESSAGES_PER_ROUND]:
                self.post_message(p.seat, m.to, m.text)

    async def movement_phase(self):
        chosen = {}
        for p in self.alive_players():
            if p.zone in self.state.frozen_zones:          # sandstorm: pinned in place this round
                chosen[p.seat] = p.zone
                continue
            obs = build_observation(self, p.seat)
            mv: Move = await self.players_by_seat[p.seat].decide_move(obs)
            if mv.zone in obs.legal_move_zones:
                zone = mv.zone
            elif p.zone in self.state.open_zones:
                zone = p.zone                              # stay if current zone still open
            else:
                zone = obs.legal_move_zones[0]             # forced out of a closed zone
            chosen[p.seat] = zone
        for seat, zone in chosen.items():          # apply after all decided
            self._p(seat).zone = zone
            self.log.record(Event("move", self.state.round_no, seat, "public",
                                   {"to": zone.value}))

    async def action_phase(self):
        order = sorted(self.alive_players(),
                       key=lambda p: (p.seat - self.state.first_seat) % 100)
        for p in order:
            if not p.alive:
                continue
            self._maybe_heal(p)          # free additional action: eat food when wounded/downed
            obs = build_observation(self, p.seat)
            forced = bool(p.zone == Zone.CENTER and obs.attackable_seats)
            action = await self.players_by_seat[p.seat].decide_action(obs)
            valid_attack = isinstance(action, Attack) and action.target_seat in obs.attackable_seats
            if forced and not valid_attack:
                action = Attack(self._lowest_hp(obs.attackable_seats))   # must fight; you pick whom
            elif not forced and isinstance(action, Attack) and not valid_attack:
                action = Draw()
            self._apply(p, action, forced=forced)
            if forced:      # center: you must fight, and you also grab a card from the rich stash
                self.center_draw(p)
            for extra in await self.players_by_seat[p.seat].decide_additional_actions(obs):
                self._apply_additional(p, extra)

    def center_draw(self, p: PlayerState):
        """The draw that comes with a forced center attack (+Feast bonus while it's active)."""
        self._draw_one(p)
        self._feast(p)
        self._hand_limit(p)

    def _hand_limit(self, p: PlayerState):
        """Drop the oldest cards over the hand limit, and say so (the player sees it happen)."""
        dropped = enforce_hand_limit(p, self._skill(p).hand_limit(p))
        if dropped:
            self.log.record(Event("discard", self.state.round_no, p.seat, "private",
                                   {"cards": [c.id for c in dropped], "why": "hand_limit"}))

    @staticmethod
    def _heal(p: PlayerState, amount: int):
        """Restore HP up to the character's max; healing never lowers HP."""
        p.hp = max(p.hp, min(p.character.hp_max, p.hp + amount))

    def _feast(self, p: PlayerState):
        """The Feast, for someone in the center while it is active: bonus center draws, or,
        once the center deck is empty, a heal instead (never above max HP)."""
        if not (self.state.feast_active and p.zone == Zone.CENTER):
            return
        if self.state.decks.get(Zone.CENTER):
            for _ in range(config.EVENT_FEAST_BONUS):
                self._draw_one(p)
            return
        before = p.hp
        self._heal(p, config.EVENT_FEAST_HEAL)
        self.log.record(Event("feast_heal", self.state.round_no, p.seat, "public",
                               {"from": before, "hp": p.hp}))

    def swap_partners(self, seat):
        """Players `seat` has completed a two-way exchange with (each gave the other a card)."""
        return {b for (a, b) in self.gives if a == seat and self.gives[(b, a)] > 0}

    def swap_count(self, a, b):
        """Completed two-way exchanges between a and b: one-way gifts don't count."""
        return min(self.gives[(a, b)], self.gives[(b, a)])

    def _note_violence(self, seat):
        """For the Pacifist: attacks by choice and bombs count, until the final three is reached."""
        if not self.reached_final3:
            self.ever_attacked.add(seat)

    def _lowest_hp(self, seats):
        return sorted(seats, key=lambda s: self._p(s).hp)[0]

    _SHRINK_ORDER = [Zone.W, Zone.S, Zone.E, Zone.N]

    def shrink_step(self):
        if len(self.alive_players()) > config.SHRINK_TRIGGER:
            return
        for z in self._SHRINK_ORDER:
            if z in self.state.open_zones:
                self.state.open_zones.discard(z)      # remove from the map; do NOT teleport anyone
                self.log.record(Event("zone_closed", self.state.round_no, None,
                                       "public", {"zone": z.value}))
                break
        # occupants of a now-closed zone are not moved; next round they must pick
        # an adjacent open zone (legal_moves excludes the closed zone, so no "stay").

    LOVERS_WIN = -2        # check_winner sentinel: only the two Lovers are left

    def check_winner(self):
        """Seat of the last survivor, -1 if nobody is left, LOVERS_WIN if the only survivors
        are the two Lovers (they win together, no need to fight it out), else None."""
        alive = self.alive_players()
        if len(alive) == 1:
            return alive[0].seat
        if len(alive) == 0:
            return -1
        if len(alive) == 2 and all(p.identity == "Lovers" for p in alive):
            return self.LOVERS_WIN
        return None

    def _apply_additional(self, p: PlayerState, action):
        if isinstance(action, PlantBomb):
            skill = self._skill(p)
            if not skill.can_make_bomb():
                return
            need = skill.bomb_fragments()
            frags = [c for c in p.hand if c.type == CardType.AMMO]
            if len(frags) < need:
                return
            for c in frags[:need]:
                p.hand.remove(c)
            self.state.bombs.append(
                Bomb(zone=action.target_zone, detonate_round=self.state.round_no + 1, planter_seat=p.seat))
            self._note_violence(p.seat)                   # planting a bomb is violence (Pacifist)
            self.log.record(Event("plant_bomb", self.state.round_no, p.seat, "private",
                                   {"zone": action.target_zone.value}))
        elif isinstance(action, TradeCard):
            card = next((c for c in p.hand if c.id == action.card_id), None)
            from_equipped = card is None and p.equipped_weapon is not None \
                and p.equipped_weapon.id == action.card_id
            if from_equipped:
                card = p.equipped_weapon      # you may hand over the weapon you're wielding
            target = next((q for q in self.state.players if q.seat == action.to_seat and q.alive), None)
            if card is not None and target is not None:
                if from_equipped:
                    p.equipped_weapon = None
                else:
                    p.hand.remove(card)
                # receiver equips a weapon upgrade (mirrors _draw_one), else keeps it in hand
                if card.type == CardType.WEAPON and (
                        target.equipped_weapon is None or card.value > target.equipped_weapon.value):
                    target.equipped_weapon = card
                else:
                    target.hand.append(card)
                self.log.record(Event("trade", self.state.round_no, p.seat, "private",
                                       {"to": target.seat, "card": card.id}))
                self.gives[(p.seat, target.seat)] += 1
        elif isinstance(action, StealCard):
            if not self._skill(p).can_steal():
                return
            target = next((q for q in self.alive_players()
                           if q.seat == action.target_seat and q.zone == p.zone and q.hand), None)
            if target is None:
                return
            if self.rng.randint(1, 4) == 4:                 # 25% success
                idx = self.rng.randrange(len(target.hand))
                stolen = target.hand.pop(idx)
                p.hand.append(stolen)
                self.log.record(Event("steal", self.state.round_no, p.seat, "private",
                                       {"from": target.seat, "card": stolen.id}))
        elif isinstance(action, EatFood):
            food = next((c for c in p.hand if c.id == action.card_id and c.type == CardType.FOOD), None)
            if food is None:
                return
            p.hand.remove(food)
            self._heal(p, food.value)
            self.log.record(Event("heal", self.state.round_no, p.seat, "public",
                                   {"food": food.id, "hp": p.hp}))
        elif isinstance(action, (CraftWeapon, CraftShield)):
            if not self._skill(p).can_craft():
                return
            basics = [c for c in p.hand if c.type == CardType.WEAPON and c.value <= 2]
            if len(basics) < 2:
                return
            a, b = basics[0], basics[1]
            p.hand.remove(a); p.hand.remove(b)
            if isinstance(action, CraftWeapon):
                crafted = Card(f"crafted-{a.id}-{b.id}", CardType.WEAPON, a.value + b.value,
                               name="合成武器")
                if p.equipped_weapon is None or crafted.value > p.equipped_weapon.value:
                    p.equipped_weapon = crafted
                else:
                    p.hand.append(crafted)
            else:
                p.hand.append(Card(f"shield-{a.id}-{b.id}", CardType.ARMOR, 2, name="合成护盾"))
            self.log.record(Event("craft", self.state.round_no, p.seat, "public",
                                   {"kind": action.__class__.__name__}))
        elif isinstance(action, PoisonFood):
            if not self._skill(p).can_poison():
                return
            foods = [c for c in p.hand if c.type == CardType.FOOD]
            if len(foods) < 2:
                return
            p.hand.remove(foods[0]); p.hand.remove(foods[1])
            poison = Card(f"poison-{self.state.round_no}-{p.seat}", CardType.FOOD, 0,
                          name="食物", poison=True)
            deck = self.state.decks.setdefault(p.zone, [])
            deck.insert(self.rng.randrange(len(deck) + 1), poison)      # shuffled in
            self.log.record(Event("poison_planted", self.state.round_no, p.seat, "private",
                                   {"zone": p.zone.value}))
        elif isinstance(action, PeekIdentity):
            if not self._skill(p).can_peek() or p.seat in self.peek_used or p.zone != Zone.W:
                return
            target = next((q for q in self.alive_players() if q.seat == action.target_seat
                           and q.seat != p.seat and q.zone == p.zone), None)
            if target is None:
                return
            self.peek_used.add(p.seat)
            self.known_identities[p.seat][target.seat] = target.identity
            self.log.record(Event("peek", self.state.round_no, p.seat, "private",
                                   {"target": target.seat, "identity": target.identity}))
        elif isinstance(action, FeedFood):
            skill = self._skill(p)
            if not skill.can_feed():
                return
            target = next((q for q in self.alive_players() if q.seat == action.target_seat
                           and q.seat != p.seat and q.zone == p.zone), None)
            foods = [c for c in p.hand if c.type == CardType.FOOD and not c.poison]
            food = (next((c for c in foods if c.id == action.card_id), None) if action.card_id
                    else min(foods, key=lambda c: c.value, default=None))
            if target is None or food is None:
                return
            p.hand.remove(food)
            self._heal(target, food.value + skill.feed_bonus())
            self.log.record(Event("feed", self.state.round_no, p.seat, "public",
                                   {"to": target.seat, "food": food.id, "hp": target.hp}))

    def _detonate_bombs(self):
        due = [b for b in self.state.bombs if b.detonate_round == self.state.round_no]
        for bomb in due:
            for victim in self.alive_players():
                if victim.zone == bomb.zone:
                    armor = next((c for c in victim.hand if c.type == CardType.ARMOR), None)
                    reduction = armor.value if armor else 0
                    if armor:
                        victim.hand.remove(armor)
                    victim.hp -= max(0, config.BOMB_DAMAGE - reduction)   # no immunity, even the planter
                    self.last_attacker[victim.seat] = bomb.planter_seat
                    self.log.record(Event("bomb", self.state.round_no, bomb.planter_seat, "public",
                                           {"zone": bomb.zone.value, "hit": victim.seat, "hp": victim.hp}))
        self.state.bombs = [b for b in self.state.bombs if b.detonate_round != self.state.round_no]

    _D4_ZONES = [Zone.N, Zone.E, Zone.S, Zone.W]   # d4: 1->forest 2->water 3->stone 4->city

    def maybe_random_event(self):
        """On an event round, roll d4 for the target outer zone, draw one event, apply it.
        Returns (event, target_zone) if one fired, else None."""
        if self.state.round_no not in config.EVENT_ROUNDS or not self.state.events:
            return None
        # roll among the outer zones still open; once only the center is left, it hits the center
        open_outer = [z for z in self._D4_ZONES if z in self.state.open_zones]
        target = open_outer[self.rng.randint(1, len(open_outer)) - 1] if open_outer else Zone.CENTER
        ev = self.state.events.pop(0)
        self.apply_random_event(ev, target)
        return ev, target

    def _event_target_zones(self, ev, target_zone):
        if ev.id == "E06":                              # Fire Balls: all zones except center & water
            return [z for z in self.state.open_zones if z not in (Zone.CENTER, Zone.E)]
        if ev.id == "E08":                              # the Feast is about the center, telegraphed
            return [Zone.CENTER]
        return [target_zone]                            # d4-picked outer zone

    def _zone_occupants(self, zones):
        zs = set(zones)
        return [p for p in self.alive_players() if p.zone in zs]

    def _return_to_deck(self, cards, zone):
        """Shuffle cards back into a zone's deck at random places (events never destroy weapons)."""
        deck = self.state.decks.setdefault(zone, [])
        for c in cards:
            deck.insert(self.rng.randrange(len(deck) + 1), c)

    def apply_random_event(self, ev, target_zone):
        zones = self._event_target_zones(ev, target_zone)
        victims = self._zone_occupants(zones)
        eid = ev.id
        if eid == "E01":                                # 变异狼群
            for p in victims:
                p.hp -= config.EVENT_WOLF_DAMAGE
        elif eid == "E06":                              # Fire Balls
            for p in victims:
                p.hp -= config.EVENT_FIRE_DAMAGE
        elif eid == "E02":                              # 洪水: HAND weapons wash back into the zone's deck
            for p in victims:
                lost = [c for c in p.hand if c.type == CardType.WEAPON]
                p.hand[:] = [c for c in p.hand if c.type != CardType.WEAPON]
                if lost:
                    self._return_to_deck(lost, p.zone)
                    self.log.record(Event("discard", self.state.round_no, p.seat, "private",
                                           {"cards": [c.id for c in lost], "why": "flood", "to": p.zone.value}))
        elif eid == "E03":                              # 猴群: the equipped weapon goes back into the zone's deck
            for p in victims:
                if p.equipped_weapon is not None:
                    self._return_to_deck([p.equipped_weapon], p.zone)
                    self.log.record(Event("discard", self.state.round_no, p.seat, "private",
                                           {"cards": [p.equipped_weapon.id], "why": "monkeys", "to": p.zone.value}))
                p.equipped_weapon = None
        elif eid == "E04":                              # 沙尘暴: freeze the zone (can't move this round)
            for z in zones:
                self.state.frozen_zones.add(z)
        elif eid == "E07":                              # Hungry Dogs: pay 2 food OR take damage
            for p in victims:
                foods = [c for c in p.hand if c.type == CardType.FOOD]
                if len(foods) >= 2:
                    for c in foods[:2]:
                        p.hand.remove(c)
                    self.log.record(Event("discard", self.state.round_no, p.seat, "private",
                                           {"cards": [c.id for c in foods[:2]], "why": "dogs"}))
                else:
                    p.hp -= config.EVENT_DOGS_DAMAGE
        elif eid == "E08":                              # the Feast: telegraph +2 center draws next round
            self.state.feast_next = True
        # E05 和平日: nothing happens
        self.log.record(Event("random_event", self.state.round_no, None, "public",
                               {"id": eid, "name": ev.name, "zone": target_zone.value,
                                "hits": [p.seat for p in victims]}))

    async def play_round(self):
        # a telegraphed Feast from last round becomes active now; a fresh sandstorm starts clear
        self.state.feast_active, self.state.feast_next = self.state.feast_next, False
        self.state.frozen_zones = set()
        self.maybe_random_event()      # fires on EVENT_ROUNDS, before movement (sandstorm freezes it)
        await self.negotiation_phase()
        await self.movement_phase()
        self._detonate_bombs()         # bombs planted last round go off after movement
        await self.action_phase()
        self.resolve_deaths()          # finalize deaths only after everyone has acted
        self.shrink_step()
        self.state.round_no += 1
        self.state.first_seat = (self.state.first_seat + 1) % len(self.state.players)

    def declare(self, seat, guesses):
        """Record a player's identity guesses: list of (target_seat, identity_name)."""
        self.declarations[seat] = list(guesses)

    def identity_winners(self):
        return identities.check_winners(self, self.declarations)

    async def play_game(self):
        elim_round = {}
        while True:
            w = self.check_winner()
            if w is not None:
                outcome = {-1: "draw", self.LOVERS_WIN: "lovers"}.get(w, "win")
                return {"winner": None if w < 0 else w,
                        "rounds": self.state.round_no - 1,
                        "outcome": outcome, "elim_round_by_seat": elim_round,
                        "identity_winners": self.identity_winners()}
            if self.state.round_no > config.ROUND_CAP:
                survivors = self.alive_players()
                top = max(survivors, key=lambda p: p.hp).seat if survivors else None
                return {"winner": top, "rounds": self.state.round_no - 1,
                        "outcome": "capped", "elim_round_by_seat": elim_round,
                        "identity_winners": self.identity_winners()}
            before = {p.seat for p in self.alive_players()}
            await self.play_round()
            after = {p.seat for p in self.alive_players()}
            for seat in before - after:
                elim_round[seat] = self.state.round_no - 1

    def _draw_one(self, p: PlayerState):
        """Draw the top card of p's zone (equip if it's a weapon upgrade, else hand). Returns the card."""
        card = deck_draw(self.state, p.zone)
        if card is not None and getattr(card, "poison", False):
            p.hp -= 4
            self.log.record(Event("poison", self.state.round_no, p.seat, "public",
                                   {"card": card.id, "hp": p.hp}))
            return card
        if card is not None:
            is_upgrade = card.type == CardType.WEAPON and (
                p.equipped_weapon is None or card.value > p.equipped_weapon.value)
            if is_upgrade:
                if p.equipped_weapon is not None:   # the old weapon is thrown away
                    self.log.record(Event("discard", self.state.round_no, p.seat, "private",
                                           {"cards": [p.equipped_weapon.id], "why": "replaced"}))
                p.equipped_weapon = card          # equip slot, not the hand
            else:
                p.hand.append(card)
        self.log.record(Event("draw", self.state.round_no, p.seat, "public",
                               {"got": card.id if card else None}))
        return card

    def _apply(self, p: PlayerState, action, forced: bool = False, dice=None):
        """forced: an attack the center rule made (doesn't count against the Pacifist).
        dice: the attack dice a human already rolled on their page (None: the engine rolls)."""
        skill = self._skill(p)
        if isinstance(action, Draw):
            alone = not any(q.alive and q.seat != p.seat and q.zone == p.zone
                            for q in self.state.players)
            draws = skill.draw_count(p, alone, p.zone)
            for _ in range(draws):
                self._draw_one(p)
            self._feast(p)                                          # the Feast: bonus draws or a heal
            self._hand_limit(p)
        elif isinstance(action, Attack):
            defender = self._p(action.target_seat)
            bonus = self._skill(defender).damage_reduction(defender, defender.zone)
            res = resolve_attack(p, defender, self.rng, config.ARMOR_REDUCTION,
                                 bonus_reduction=bonus, ignore_armor=skill.ignores_armor(p),
                                 rolls=skill.attack_rolls(p), preset=dice)
            if not forced:
                self._note_violence(p.seat)
            self.last_attacker[defender.seat] = p.seat
            self.log.record(Event("attack", self.state.round_no, p.seat, "public",
                                   {"target": defender.seat, **res}))
            # death is not finalized here; end-of-round resolve_deaths() handles it
            for _ in range(skill.draws_after_attack(p, p.zone)):   # e.g. Fae in the forest
                self._draw_one(p)
            self._hand_limit(p)

    def _eat_one_food(self, p: PlayerState) -> bool:
        food = next((c for c in p.hand if c.type == CardType.FOOD), None)
        if food is None:
            return False
        p.hand.remove(food)
        self._heal(p, food.value)
        self.log.record(Event("heal", self.state.round_no, p.seat, "public",
                               {"food": food.id, "hp": p.hp}))
        return True

    def _maybe_heal(self, p: PlayerState):
        """Free additional action at the start of a turn:
        - downed (<=0 HP): eat food repeatedly to try to get back above 0;
        - wounded (HP at or below half of max): top up with one food.
        A healthy player keeps its food."""
        while p.hp <= 0:
            if not self._eat_one_food(p):
                break
        if 0 < p.hp <= p.character.hp_max // 2:
            self._eat_one_food(p)

    def resolve_deaths(self):
        """End-of-round: anyone still at <=0 HP is eliminated (credit kills, record order)."""
        dead_now = []
        dying = [p for p in self.state.players if p.alive and p.hp <= 0]
        while dying:                     # a Scimitar can drop its holder's killer too
            for p in dying:
                p.alive = False
                dead_now.append(p.seat)
                killer = self.last_attacker.get(p.seat)
                if killer is not None and killer != p.seat:
                    self.kills[killer] += 1
                    self.killer_of[p.seat] = killer
                weapons = ([p.equipped_weapon] if p.equipped_weapon else []) + \
                          [c for c in p.hand if c.type == CardType.WEAPON]
                self.died_with_advanced[p.seat] = sum(1 for w in weapons if w.value >= 3)
                self.log.record(Event("eliminated", self.state.round_no, p.seat, "public", {}))
                if killer is not None and killer != p.seat and any(w.name == config.SCIMITAR for w in weapons):
                    k = self._p(killer)
                    if k.alive:
                        k.hp -= config.SCIMITAR_DAMAGE
                        self.last_attacker[k.seat] = p.seat
                        self.log.record(Event("scimitar", self.state.round_no, p.seat, "public",
                                               {"target": k.seat, "damage": config.SCIMITAR_DAMAGE, "hp": k.hp}))
            dying = [p for p in self.state.players if p.alive and p.hp <= 0]
        if dead_now:
            self.deaths_by_round.append((self.state.round_no, dead_now))
        if not self.reached_final3:
            alive = self.alive_players()
            if len(alive) <= 3:
                self.reached_final3 = {q.seat for q in alive}


def build_observation(engine: Engine, seat: int) -> Observation:
    me = engine._p(seat)
    from .map import adjacent as _adjacent
    zones = engine._skill(me).attack_zones(me, _adjacent(me.zone))
    attackable = [q.seat for q in engine.alive_players()
                  if q.seat != seat and q.zone in zones]
    if engine.state.round_no == 1:
        # Round 1 has no fixed spawn: each player freely places their pawn in any open zone.
        moves = sorted(engine.state.open_zones, key=lambda z: z.value)
    else:
        moves = legal_moves(me.zone, engine.state.open_zones)
    return Observation(me=me, state=engine.state, legal_move_zones=moves,
                       attackable_seats=attackable, messages=engine.visible_messages(seat))
