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
                   rng: random.Random, armor_reduction: int, bonus_reduction: int = 0, ignore_armor: bool = False,
                   rolls: int = 1) -> Dict:
    """Apply one attack's damage. Does NOT finalize death: a defender dropped to
    <=0 HP is 'downed' but stays on the board until end-of-round resolution, so
    they still get their action this round (heal / retaliate / draw)."""
    faces = max(1, attack_value(attacker))
    roll = max(rng.randint(1, faces) for _ in range(max(1, rolls)))   # e.g. Bram rolls twice, keeps the higher
    if ignore_armor:                                               # e.g. Bram smashes through armor
        reduction = bonus_reduction
    else:
        armor = _take_armor(defender)
        reduction = (armor.value or armor_reduction) if armor else 0   # the card's own value; default if unset
        reduction += bonus_reduction                               # skill-based reduction, if any
    damage = max(0, roll - reduction)
    defender.hp -= damage
    return {"damage": damage, "roll": roll, "downed": defender.hp <= 0}
