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
    """Apply one attack's damage. Does NOT finalize death: a defender dropped to
    <=0 HP is 'downed' but stays on the board until end-of-round resolution, so
    they still get their action this round (heal / retaliate / draw)."""
    faces = max(1, attack_value(attacker))
    roll = rng.randint(1, faces)
    reduction = armor_reduction if _take_armor(defender) else 0
    damage = max(0, roll - reduction)
    defender.hp -= damage
    return {"damage": damage, "roll": roll, "downed": defender.hp <= 0}
