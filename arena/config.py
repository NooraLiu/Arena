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
HAND_LIMIT = 5
ARMOR_REDUCTION = 2   # flat damage reduction when armor spent
FOOD_HEAL = 2
SHRINK_TRIGGER = 5    # start shrinking when alive count <= this
ROUND_CAP = 100       # hard termination guarantee


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
