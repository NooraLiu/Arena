import random
from typing import Dict, List
from .models import Zone, Card, CardType, Character

DEFAULT_CHARACTERS: List[Character] = [
    Character("Brawler", 7, 2), Character("Ranger", 5, 3),
    Character("Assassin", 3, 4), Character("Guard", 7, 2),
    Character("Scout", 5, 3), Character("Duelist", 3, 4),
]
WEAPONS = [("knife", 1), ("staff", 2), ("crossbow", 3), ("rifle", 4)]
DRAW_COUNT = 1
HAND_LIMIT = 4        # 🔧 max hand size WITHOUT skills; equipped weapon does NOT count. Tune later.
ARMOR_REDUCTION = 2   # flat damage reduction when armor spent
FOOD_HEAL = 2
SHRINK_TRIGGER = 5    # start shrinking when alive count <= this
ROUND_CAP = 100       # hard termination guarantee
BOMB_DAMAGE = 6       # everyone in the target zone; armor reduces
BOMB_FRAGMENTS = 3    # fragments to build a bomb (Garcia: 2)
MESSAGES_PER_ROUND = 2  # max messages a player may send in the negotiation phase
EVENT_ROUNDS = (4, 6, 7, 9)   # rounds on which a random event fires (roll d4 for the target outer zone)
EVENT_WOLF_DAMAGE = 4         # E01 变异狼群
EVENT_FIRE_DAMAGE = 3         # E06 Fire Balls
EVENT_DOGS_DAMAGE = 3         # E07 Hungry Dogs (if you can't pay 2 food)
EVENT_FEAST_BONUS = 2         # E08 The Feast: extra draws for center dwellers next round


def _weapon(name, bonus, i):
    return Card(id=f"{name}-{i}", type=CardType.WEAPON, value=bonus)


def build_region_decks(rng: random.Random) -> Dict[Zone, List[Card]]:
    decks: Dict[Zone, List[Card]] = {}
    outer = [Zone.N, Zone.E, Zone.S, Zone.W]
    for z in outer:
        cards = []
        for i in range(3):
            name, bonus = rng.choice(WEAPONS[:2])  # outer: weaker weapons
            cards.append(_weapon(name, bonus, f"{z.value}{i}"))
        cards += [Card(f"food-{z.value}{i}", CardType.FOOD, FOOD_HEAL) for i in range(3)]
        cards += [Card(f"armor-{z.value}{i}", CardType.ARMOR, ARMOR_REDUCTION) for i in range(2)]
        rng.shuffle(cards)
        decks[z] = cards
    center = []
    for i in range(4):
        name, bonus = rng.choice(WEAPONS[1:])  # center: stronger weapons
        center.append(_weapon(name, bonus, f"c{i}"))
    center += [Card(f"food-c{i}", CardType.FOOD, FOOD_HEAL) for i in range(3)]
    center += [Card(f"armor-c{i}", CardType.ARMOR, ARMOR_REDUCTION) for i in range(2)]
    rng.shuffle(center)
    decks[Zone.CENTER] = center
    return decks
