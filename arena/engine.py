import random
from collections import Counter, defaultdict
from typing import Dict, List
from .models import (Zone, PlayerState, GameState, Move, Draw, Attack, CardType, Card,
                     PlantBomb, TradeCard, Bomb, Message, StealCard, CraftWeapon, CraftShield, PoisonFood)
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
        self.ever_attacked = set()           # seats that ever chose Attack
        self.trade_partners = defaultdict(set)   # seat -> set of trade partners
        self.pair_trades = defaultdict(int)      # frozenset({a,b}) -> trade count
        self.reached_final3 = set()          # seats alive when count first <= 3
        self.messages = []                   # dialogue log (public + private)
        self.declarations = {}               # seat -> list of (guess_seat, guess_identity)

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
            forced = (p.zone == Zone.CENTER and obs.attackable_seats)
            if forced:
                action = Attack(self._lowest_hp(obs.attackable_seats))
            else:
                action = await self.players_by_seat[p.seat].decide_action(obs)
                if isinstance(action, Attack) and action.target_seat not in obs.attackable_seats:
                    action = Draw()
            self._apply(p, action)
            if forced:      # center: you must fight, and you also grab a card from the rich stash
                self._draw_one(p)
                enforce_hand_limit(p, self._skill(p).hand_limit(p))
            for extra in await self.players_by_seat[p.seat].decide_additional_actions(obs):
                self._apply_additional(p, extra)

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

    def check_winner(self):
        alive = self.alive_players()
        if len(alive) == 1:
            return alive[0].seat
        if len(alive) == 0:
            return -1
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
                self.trade_partners[p.seat].add(target.seat)
                self.trade_partners[target.seat].add(p.seat)
                self.pair_trades[frozenset({p.seat, target.seat})] += 1
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
        target = self._D4_ZONES[self.rng.randint(1, 4) - 1]
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
        elif eid == "E02":                              # 洪水: discard HAND weapons (equipped survives)
            for p in victims:
                p.hand[:] = [c for c in p.hand if c.type != CardType.WEAPON]
        elif eid == "E03":                              # 猴群: steal the equipped weapon
            for p in victims:
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
                outcome = "draw" if w == -1 else "win"
                return {"winner": None if w == -1 else w,
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
                p.equipped_weapon = card          # equip slot, not the hand
            else:
                p.hand.append(card)
        self.log.record(Event("draw", self.state.round_no, p.seat, "public",
                               {"got": card.id if card else None}))
        return card

    def _apply(self, p: PlayerState, action):
        skill = self._skill(p)
        if isinstance(action, Draw):
            alone = not any(q.alive and q.seat != p.seat and q.zone == p.zone
                            for q in self.state.players)
            draws = skill.draw_count(p, alone, p.zone)
            if self.state.feast_active and p.zone == Zone.CENTER:   # the Feast: bonus center draws
                draws += config.EVENT_FEAST_BONUS
            for _ in range(draws):
                self._draw_one(p)
            enforce_hand_limit(p, skill.hand_limit(p))
        elif isinstance(action, Attack):
            defender = self._p(action.target_seat)
            bonus = self._skill(defender).damage_reduction(defender, defender.zone)
            res = resolve_attack(p, defender, self.rng, config.ARMOR_REDUCTION,
                                 bonus_reduction=bonus, ignore_armor=skill.ignores_armor(p))
            self.ever_attacked.add(p.seat)
            self.last_attacker[defender.seat] = p.seat
            self.log.record(Event("attack", self.state.round_no, p.seat, "public",
                                   {"target": defender.seat, **res}))
            # death is not finalized here; end-of-round resolve_deaths() handles it
            for _ in range(skill.draws_after_attack(p, p.zone)):   # e.g. Fae in the forest
                self._draw_one(p)
            enforce_hand_limit(p, skill.hand_limit(p))

    def _eat_one_food(self, p: PlayerState) -> bool:
        food = next((c for c in p.hand if c.type == CardType.FOOD), None)
        if food is None:
            return False
        p.hand.remove(food)
        p.hp += food.value
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
        for p in self.state.players:
            if p.alive and p.hp <= 0:
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
