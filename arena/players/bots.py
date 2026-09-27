import random
from typing import Union
from collections import Counter
from ..models import Zone, Move, Draw, Attack, CardType, PlantBomb
from ..combat import attack_value
from .. import skills
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


def _skill_home_zone(player):
    return skills.for_character(player.character.name).home_zone(player)


class SmartBot(Player):
    """Utility-based bot (no LLM). Reasons about the visible state:
    secures reachable kills, arms up when unarmed, and avoids the forced-combat
    center while weak. It never inspects hidden deck contents — only whether a
    zone's deck still has cards and the public positions/HP of others.
    """

    def __init__(self, rng: random.Random):
        self.rng = rng

    def _enemies_in(self, obs: Observation, zone: Zone) -> int:
        return sum(1 for p in obs.state.players
                   if p.alive and p.seat != obs.me.seat and p.zone == zone)

    def _deck_size(self, obs: Observation, zone: Zone) -> int:
        return len(obs.state.decks.get(zone, []))

    async def decide_move(self, obs: Observation) -> Move:
        me = obs.me
        weak = me.hp <= me.character.hp_max // 2
        unarmed = me.equipped_weapon is None
        cautious = weak or unarmed

        home = _skill_home_zone(me)               # zone where my skill pays off, if any

        def score(z: Zone) -> float:
            s = 0.0
            enemies = self._enemies_in(obs, z)
            if z == Zone.CENTER:
                s += -5.0 if cautious else 3.0        # center forces combat
            if cautious and self._deck_size(obs, z) > 0:
                s += 2.0                              # go somewhere I can arm up
            if z == home:
                s += 3.0                              # my skill's zone (Bram/Fae/Tobias/…)
            s += (-2.0 if cautious else 1.0) * enemies  # flee crowds when weak, seek when strong
            return s

        best = max(obs.legal_move_zones, key=score)
        return Move(best)

    async def decide_action(self, obs: Observation) -> Union[Draw, Attack]:
        me = obs.me
        targets = obs.attackable_seats
        hp_of = {p.seat: p.hp for p in obs.state.players}
        my_reach = attack_value(me)   # max roll = damage ceiling this turn

        # 1) secure a reachable kill (weakest target within reach)
        killable = [s for s in targets if hp_of.get(s, 0) <= my_reach]
        if killable:
            return Attack(min(killable, key=lambda s: hp_of[s]))

        # 2) arm up: unarmed (or no target) and the local deck still has cards
        deck_has = self._deck_size(obs, me.zone) > 0
        if deck_has and (me.equipped_weapon is None or not targets):
            return Draw()

        # 3) armed but no sure kill -> chip the weakest target
        if targets:
            return Attack(min(targets, key=lambda s: hp_of[s]))

        # 4) nothing else useful -> draw
        return Draw()

    async def decide_additional_actions(self, obs: Observation):
        me = obs.me
        skill = skills.for_character(me.character.name)
        if not skill.can_make_bomb():
            return []
        frags = sum(1 for c in me.hand if c.type == CardType.AMMO)
        if frags < skill.bomb_fragments():
            return []
        # bomb the most-crowded enemy zone that isn't mine
        counts = Counter(p.zone for p in obs.state.players
                         if p.alive and p.seat != me.seat and p.zone != me.zone)
        if counts and counts.most_common(1)[0][1] >= 2:
            return [PlantBomb(counts.most_common(1)[0][0])]
        return []
