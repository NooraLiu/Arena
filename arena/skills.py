"""Character skills, implemented in code and keyed by character name.

The 人物 sheet's 特殊技能 column is the human-readable description; the engine
executes the effect via the Skill registered here under the same character name.
When a character's skill text changes, update the matching class below.

Batch 1 (implemented): passive / simple skills that need no new subsystems.
Batch 2 (pending new systems): Riley (steal), Garcia (bombs), Tobias / Michael
(item-granted abilities), Natalie (poison).  Batch 3 (needs v2 agents): Iris, Mira.
"""
from .models import Zone
from . import config


class Skill:
    """Default no-op hooks. Each hook is called by the engine at one point."""

    def damage_reduction(self, player, zone: Zone) -> int:
        """Extra flat damage reduction when this player is attacked (on top of armor)."""
        return 0

    def draw_count(self, player, alone: bool, zone: Zone) -> int:
        """How many cards a Draw action yields."""
        return config.DRAW_COUNT

    def hand_limit(self, player) -> int:
        return config.HAND_LIMIT

    def draws_after_attack(self, player, zone: Zone) -> int:
        """Bonus cards drawn on a turn the player chose to attack."""
        return 0

    def home_zone(self, player):
        """Zone where this skill pays off, so a bot knows to head there (or None)."""
        return None

    def ignores_armor(self, player) -> bool:
        """Whether this player's attacks bypass the target's armor."""
        return False


class NoSkill(Skill):
    pass


class Bram(Skill):
    # 蛮力:攻击时无视对方护甲(护甲不减伤,也不被消耗)。
    def ignores_armor(self, player):
        return True


class Elliot(Skill):
    # 如果同区域无人,一次可以捡两张卡,并且最多可以有 6 张手牌。
    def draw_count(self, player, alone, zone):
        return 2 if alone else 1

    def hand_limit(self, player):
        return 6


class Fae(Skill):
    # 在林区攻击的回合也可以拿一张手牌。
    def draws_after_attack(self, player, zone):
        return 1 if zone == Zone.N else 0

    def home_zone(self, player):
        return Zone.N


class Cato(Skill):
    # 无法使用碎片拼成炸药。(bomb system pending; flag consumed once bombs exist)
    can_make_bomb = False


_REGISTRY = {
    "Bram": Bram,
    "Elliot": Elliot,
    "Fae": Fae,
    "Cato": Cato,
}


def for_character(name: str) -> Skill:
    return _REGISTRY.get((name or "").strip(), NoSkill)()
