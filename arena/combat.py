import random
from typing import Dict
from .models import PlayerState, CardType


def attack_value(attacker: PlayerState) -> int:
    bonus = attacker.equipped_weapon.value if attacker.equipped_weapon else 0
    return attacker.character.base_attack + bonus


def _take_armor(defender: PlayerState):
    for c in defender.hand:
        if c.type == CardType.ARMOR:
            defender.hand.remove(c)
            return c
    return None


def resolve_attack(attacker: PlayerState, defender: PlayerState,
                   rng: random.Random, armor_reduction: int) -> Dict:
    faces = max(1, attack_value(attacker))
    roll = rng.randint(1, faces)
    reduction = armor_reduction if _take_armor(defender) else 0
    damage = max(0, roll - reduction)
    defender.hp -= damage
    eliminated = defender.hp <= 0
    if eliminated:
        defender.alive = False
    return {"damage": damage, "roll": roll, "defender_eliminated": eliminated}
