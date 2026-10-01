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
    poison: bool = False    # a poison-food trap (Natalie): deals damage on draw


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
class StealCard:          # Riley
    target_seat: int


@dataclass
class CraftWeapon:        # Agatha: combine two basic weapons -> summed weapon
    pass


@dataclass
class CraftShield:        # Agatha: combine two basic weapons -> a shield (armor 2)
    pass


@dataclass
class PoisonFood:         # Natalie: spend 2 food -> a poison card into her zone deck
    pass


@dataclass
class PeekIdentity:       # Iris: once per game, in the city, secretly see a same-zone player's identity
    target_seat: int


@dataclass
class EatFood:            # anyone: eat one of your food cards now (additional action)
    card_id: str


@dataclass
class FeedFood:           # Mira: feed one of her foods to a same-zone player (+2 extra HP)
    target_seat: int
    card_id: Optional[str] = None     # which food; None = her smallest food


@dataclass
class Message:
    round_no: int
    sender: int
    to: Optional[int]        # None = public broadcast; else recipient seat
    text: str


@dataclass
class Bomb:
    zone: Zone
    detonate_round: int
    planter_seat: int


@dataclass
class RandomEvent:
    id: str                  # e.g. "E01"
    name: str                # 事件名, e.g. "变异狼群"
    description: str = ""     # flavor text
    target: str = ""         # 影响区域 (raw text, for display)
    effect: str = ""         # 效果 (raw text, for display)
    count: int = 1           # 张数 (copies in the event deck)


@dataclass
class GameState:
    round_no: int
    players: List[PlayerState]
    decks: Dict[Zone, List[Card]]
    open_zones: Set[Zone]
    first_seat: int
    bombs: List["Bomb"] = field(default_factory=list)
    events: List["RandomEvent"] = field(default_factory=list)   # remaining random-event deck
    frozen_zones: Set["Zone"] = field(default_factory=set)      # can't move OUT this round (sandstorm)
    frozen_next: Set["Zone"] = field(default_factory=set)       # a sandstorm this round: locked next round
    feast_next: bool = False                                     # the Feast telegraphed this round
    feast_active: bool = False                                   # center draws +2 THIS round (Feast in effect)
