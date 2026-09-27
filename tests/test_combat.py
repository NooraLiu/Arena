import random
from arena.models import Character, PlayerState, Zone, Card, CardType
from arena.combat import attack_value, resolve_attack


def _p(seat, hp, atk, weapon=None, hand=None):
    ch = Character("X", hp, atk)
    return PlayerState(seat=seat, character=ch, hp=hp, zone=Zone.CENTER,
                       hand=hand or [], equipped_weapon=weapon)


def test_attack_value_adds_weapon():
    p = _p(1, 5, 3, weapon=Card("w", CardType.WEAPON, 4))
    assert attack_value(p) == 7


def test_resolve_attack_applies_damage_and_reports_downed_without_finalizing_death():
    atk = _p(1, 5, 4)                 # d4
    dfn = _p(2, 3, 3)
    rng = random.Random(1)            # deterministic roll
    res = resolve_attack(atk, dfn, rng, armor_reduction=2)
    assert 1 <= res["roll"] <= 4
    assert dfn.hp == 3 - res["damage"]
    assert res["downed"] == (dfn.hp <= 0)
    assert dfn.alive is True           # death is resolved later, not on the hit


class _MaxRoll:
    """Deterministic die that always rolls its highest face."""
    def randint(self, a, b):
        return b


def test_armor_reduction_uses_the_card_value():
    atk = _p(1, 5, 4)                              # d4 -> always rolls 4
    vest = Card("v", CardType.ARMOR, 3)            # 防弹背心 reduces 3, not the default 2
    dfn = _p(2, 10, 3, hand=[vest])
    res = resolve_attack(atk, dfn, _MaxRoll(), armor_reduction=2)
    assert res["roll"] == 4
    assert res["damage"] == 1                      # 4 - 3 (card value), not 4 - 2


def test_armor_is_spent_and_reduces_damage():
    atk = _p(1, 5, 4)
    armor = Card("a", CardType.ARMOR, 2)
    dfn = _p(2, 10, 3, hand=[armor])
    rng = random.Random(1)
    res = resolve_attack(atk, dfn, rng, armor_reduction=2)
    assert armor not in dfn.hand      # spent
    assert res["damage"] == max(0, res["roll"] - 2)
