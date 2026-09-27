from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set


class Zone(Enum):
    CENTER = "center"
    N = "n"
    E = "e"
    S = "s"
    W = "w"


class CardType(Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    FOOD = "food"
    AMMO = "ammo"


@dataclass
class Card:
    id: str
    type: CardType
    value: int  # weapon: +attack; food: +hp; armor: damage reduced; ammo: fragment count
    name: str = ""          # display name, e.g. "蘑菇"
    description: str = ""   # flavor text, e.g. "看上去有点毒的蘑菇"
    effect: str = ""        # 特殊效果 / extra function (free text, used by v2+ agents)
    synergy: str = ""       # 角色协同 / character-specific bonus (free text)


@dataclass
class Character:
    name: str
    hp_max: int
    base_attack: int


@dataclass
class PlayerState:
    seat: int
    character: Character
    hp: int
    zone: Zone
    hand: List[Card] = field(default_factory=list)
    equipped_weapon: Optional[Card] = None
    alive: bool = True
    identity: Optional[str] = None   # hidden-identity card name (secret to other players)


@dataclass
class Move:
    zone: Zone


@dataclass
class Draw:
    pass


@dataclass
class Attack:
    target_seat: int


# ---- additional actions (taken in addition to the main draw/attack) ----
@dataclass
class PlantBomb:
    target_zone: "Zone"


@dataclass
class TradeCard:
    to_seat: int
    card_id: str


@dataclass
class Bomb:
    zone: Zone
    detonate_round: int
    planter_seat: int


@dataclass
class GameState:
    round_no: int
    players: List[PlayerState]
    decks: Dict[Zone, List[Card]]
    open_zones: Set[Zone]
    first_seat: int
    bombs: List["Bomb"] = field(default_factory=list)
