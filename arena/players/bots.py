import random
from typing import Union
from ..models import Zone, Move, Draw, Attack
from .base import Player, Observation


class RandomBot(Player):
    def __init__(self, rng: random.Random):
        self.rng = rng

    async def decide_move(self, obs: Observation) -> Move:
        return Move(self.rng.choice(obs.legal_move_zones))

    async def decide_action(self, obs: Observation) -> Union[Draw, Attack]:
        if obs.attackable_seats and self.rng.random() < 0.5:
            return Attack(self.rng.choice(obs.attackable_seats))
        return Draw()


class HeuristicBot(Player):
    def __init__(self, rng: random.Random):
        self.rng = rng

    async def decide_move(self, obs: Observation) -> Move:
        healthy = obs.me.hp > obs.me.character.hp_max // 2
        if healthy and Zone.CENTER in obs.legal_move_zones:
            return Move(Zone.CENTER)
        outer = [z for z in obs.legal_move_zones if z != Zone.CENTER]
        return Move(self.rng.choice(outer) if outer else obs.legal_move_zones[0])

    async def decide_action(self, obs: Observation) -> Union[Draw, Attack]:
        targets = obs.attackable_seats
        if targets:
            hp_of = {p.seat: p.hp for p in obs.state.players}
            by_hp = sorted(targets, key=lambda s: hp_of.get(s, 0))
            return Attack(by_hp[0])
        return Draw()
