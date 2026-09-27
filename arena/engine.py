import random
from typing import Dict, List
from .models import Zone, PlayerState, GameState, Move, Draw, Attack, CardType
from .map import legal_moves
from .deck import draw as deck_draw, enforce_hand_limit
from .combat import resolve_attack
from .players.base import Observation, Player
from .events import Event, EventLog
from . import config
from . import skills


class Engine:
    def __init__(self, state: GameState, players_by_seat: Dict[int, Player],
                 rng: random.Random = None, log: EventLog = None):
        self.state = state
        self.players_by_seat = players_by_seat
        self.rng = rng or random.Random()
        self.log = log or EventLog()

    def alive_players(self) -> List[PlayerState]:
        return [p for p in self.state.players if p.alive]

    def _p(self, seat: int) -> PlayerState:
        return next(p for p in self.state.players if p.seat == seat)

    def _skill(self, p: PlayerState):
        return skills.for_character(p.character.name)

    async def movement_phase(self):
        chosen = {}
        for p in self.alive_players():
            obs = build_observation(self, p.seat)
            mv: Move = await self.players_by_seat[p.seat].decide_move(obs)
            zone = mv.zone if mv.zone in obs.legal_move_zones else p.zone
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

    def _lowest_hp(self, seats):
        return sorted(seats, key=lambda s: self._p(s).hp)[0]

    _SHRINK_ORDER = [Zone.W, Zone.S, Zone.E, Zone.N]

    def shrink_step(self):
        if len(self.alive_players()) > config.SHRINK_TRIGGER:
            return
        for z in self._SHRINK_ORDER:
            if z in self.state.open_zones:
                self.state.open_zones.discard(z)
                for p in self.alive_players():
                    if p.zone == z:
                        p.zone = Zone.CENTER
                self.log.record(Event("zone_closed", self.state.round_no, None,
                                       "public", {"zone": z.value}))
                break

    def check_winner(self):
        alive = self.alive_players()
        if len(alive) == 1:
            return alive[0].seat
        if len(alive) == 0:
            return -1
        return None

    async def play_round(self):
        await self.movement_phase()
        await self.action_phase()
        self.resolve_deaths()          # finalize deaths only after everyone has acted
        self.shrink_step()
        self.state.round_no += 1
        self.state.first_seat = (self.state.first_seat + 1) % len(self.state.players)

    async def play_game(self):
        elim_round = {}
        while True:
            w = self.check_winner()
            if w is not None:
                outcome = "draw" if w == -1 else "win"
                return {"winner": None if w == -1 else w,
                        "rounds": self.state.round_no - 1,
                        "outcome": outcome, "elim_round_by_seat": elim_round}
            if self.state.round_no > config.ROUND_CAP:
                survivors = self.alive_players()
                top = max(survivors, key=lambda p: p.hp).seat if survivors else None
                return {"winner": top, "rounds": self.state.round_no - 1,
                        "outcome": "capped", "elim_round_by_seat": elim_round}
            before = {p.seat for p in self.alive_players()}
            await self.play_round()
            after = {p.seat for p in self.alive_players()}
            for seat in before - after:
                elim_round[seat] = self.state.round_no - 1

    def _draw_one(self, p: PlayerState):
        """Draw the top card of p's zone (equip if it's a weapon upgrade, else hand). Returns the card."""
        card = deck_draw(self.state, p.zone)
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
            for _ in range(skill.draw_count(p, alone, p.zone)):
                self._draw_one(p)
            enforce_hand_limit(p, skill.hand_limit(p))
        elif isinstance(action, Attack):
            defender = self._p(action.target_seat)
            bonus = self._skill(defender).damage_reduction(defender, defender.zone)
            res = resolve_attack(p, defender, self.rng, config.ARMOR_REDUCTION, bonus_reduction=bonus)
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
        """End-of-round: anyone still at <=0 HP is eliminated."""
        for p in self.state.players:
            if p.alive and p.hp <= 0:
                p.alive = False
                self.log.record(Event("eliminated", self.state.round_no, p.seat, "public", {}))


def build_observation(engine: Engine, seat: int) -> Observation:
    me = engine._p(seat)
    attackable = [q.seat for q in engine.alive_players()
                  if q.seat != seat and q.zone == me.zone]
    if engine.state.round_no == 1:
        # Round 1 has no fixed spawn: each player freely places their pawn in any open zone.
        moves = sorted(engine.state.open_zones, key=lambda z: z.value)
    else:
        moves = legal_moves(me.zone, engine.state.open_zones)
    return Observation(me=me, state=engine.state,
                       legal_move_zones=moves, attackable_seats=attackable)
