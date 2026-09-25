import random
from arena.models import Zone, Card, CardType, Character, PlayerState, GameState
from arena import config
from arena.deck import draw, enforce_hand_limit


def test_draw_from_empty_returns_none():
    st = GameState(round_no=1, players=[], decks={Zone.N: []},
                   open_zones={Zone.N}, first_seat=0)
    assert draw(st, Zone.N) is None


def test_draw_pops_top_card():
    c = Card(id="w1", type=CardType.WEAPON, value=2)
    st = GameState(round_no=1, players=[], decks={Zone.N: [c]},
                   open_zones={Zone.N}, first_seat=0)
    assert draw(st, Zone.N) is c
    assert draw(st, Zone.N) is None


def test_hand_limit_discards_excess():
    ch = Character("X", 5, 3)
    hand = [Card(f"c{i}", CardType.FOOD, 1) for i in range(7)]
    p = PlayerState(seat=1, character=ch, hp=5, zone=Zone.N, hand=hand)
    discarded = enforce_hand_limit(p, hand_limit=5)
    assert len(p.hand) == 5 and len(discarded) == 2


def test_region_decks_cover_all_open_zones():
    rng = random.Random(42)
    decks = config.build_region_decks(rng)
    for z in [Zone.CENTER, Zone.N, Zone.E, Zone.S, Zone.W]:
        assert z in decks and len(decks[z]) > 0
