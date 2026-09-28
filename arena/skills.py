"""Character skills, implemented in code and keyed by character name.

The 人物 sheet's 特殊技能 column is the human-readable description; the engine
executes the effect via the Skill registered here under the same character name.
When a character's skill text changes, update the matching class below.

Batch 1 (implemented): passive / simple skills that need no new subsystems.
Batch 2 (pending new systems): Riley (steal), Garcia (bombs), Tobias / Michael
(item-granted abilities), Natalie (poison).  Batch 3 (implemented, used by LLM agents):
Iris (peek), Mira (feed).
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

    def can_make_bomb(self) -> bool:
        return True

    def bomb_fragments(self) -> int:
        return config.BOMB_FRAGMENTS

    def can_steal(self) -> bool:
        return False

    def can_craft(self) -> bool:
        return False

    def can_poison(self) -> bool:
        return False

    def can_peek(self) -> bool:
        return False

    def can_feed(self) -> bool:
        return False

    def feed_bonus(self) -> int:
        """Extra HP when this player feeds someone else a food."""
        return 0

    def attack_zones(self, player, adjacent):
        """Zones whose occupants this player may attack. Default: own zone only."""
        return {player.zone}


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
    # 15/4,但无法用碎片拼成炸弹。
    def can_make_bomb(self):
        return False


class Garcia(Skill):
    # 只需要 2 枚碎片就可以制成一个炸弹。
    def bomb_fragments(self):
        return 2


class Riley(Skill):
    # 小偷: 附加行动,d4 出 4 则偷同区一人一张手牌(不偷已装备武器)。
    def can_steal(self):
        return True


class Tobias(Skill):
    # 三叉戟在手且在水区时,每回合多抽一张。
    def draw_count(self, player, alone, zone):
        w = player.equipped_weapon
        base = 2 if alone else 1
        if w is not None and w.name == "三叉戟" and zone == Zone.E:
            return base + 1
        return base


class Michael(Skill):
    # 拿到弓时,可攻击相邻区域的玩家。
    def attack_zones(self, player, adjacent):
        w = player.equipped_weapon
        if w is not None and w.name == "弓":
            return {player.zone} | set(adjacent)
        return {player.zone}


class Agatha(Skill):
    # 合成: 两张初级武器 -> 攻击相加的武器,或减伤 2 的护盾。
    def can_craft(self):
        return True


class Natalie(Skill):
    # 下毒: 2 张食物 -> 1 张毒食物洗入本区牌堆,抽到者 -4。
    def can_poison(self):
        return True


class Iris(Skill):
    # 在城区时,每局一次,可以秘密查看同区域一名玩家的隐藏身份。
    def can_peek(self):
        return True

    def home_zone(self, player):
        return Zone.W


class Mira(Skill):
    # 附加行动:把自己的食物给同区域另一名玩家吃,回血效果 +2。
    def can_feed(self):
        return True

    def feed_bonus(self):
        return 2


_REGISTRY = {
    "Iris": Iris,
    "Mira": Mira,
    "Bram": Bram,
    "Elliot": Elliot,
    "Fae": Fae,
    "Cato": Cato,
    "Garcia": Garcia,
    "Riley": Riley,
    "Tobias": Tobias,
    "Michael": Michael,
    "Agatha": Agatha,
    "Natalie": Natalie,
}


def for_character(name: str) -> Skill:
    return _REGISTRY.get((name or "").strip(), NoSkill)()
