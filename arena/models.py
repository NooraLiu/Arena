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


@dataclass
class Move:
    zone: Zone


@dataclass
class Draw:
    pass


@dataclass
class Attack:
    target_seat: int


@dataclass
class GameState:
    round_no: int
    players: List[PlayerState]
    decks: Dict[Zone, List[Card]]
    open_zones: Set[Zone]
    first_seat: int
