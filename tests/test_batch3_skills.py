import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          PeekIdentity, FeedFood)
from arena.players.base import Player
from arena.engine import Engine


def _engine(players):
    st = GameState(round_no=2, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat={p.seat: Player() for p in players}, rng=random.Random(0))


def _p(seat, name, zone, hp=10, hand=None, identity=None):
    p = PlayerState(seat, Character(name, 10, 2), hp, zone, hand=hand or [])
    p.identity = identity
    return p


def _food(cid, v):
    return Card(cid, CardType.FOOD, v, name="面包")


# ---- Iris: once per game, in the city, secretly learn a same-zone player's identity ----
def test_iris_peeks_in_city_and_only_she_learns_it():
    iris, v = _p(0, "Iris", Zone.W), _p(1, "V", Zone.W, identity="Vendetta")
    eng = _engine([iris, v])
    eng._apply_additional(iris, PeekIdentity(1))
    assert eng.known_identities[0] == {1: "Vendetta"}
    ev = [e for e in eng.log.events if e.type == "peek"]
    assert len(ev) == 1 and ev[0].visibility == "private" and ev[0].actor == 0


def test_iris_peek_is_once_per_game():
    iris = _p(0, "Iris", Zone.W)
    a, b = _p(1, "A", Zone.W, identity="Warrior"), _p(2, "B", Zone.W, identity="Lovers")
    eng = _engine([iris, a, b])
    eng._apply_additional(iris, PeekIdentity(1))
    eng._apply_additional(iris, PeekIdentity(2))
    assert eng.known_identities[0] == {1: "Warrior"}


def test_iris_cannot_peek_outside_city_or_across_zones():
    iris, a = _p(0, "Iris", Zone.N), _p(1, "A", Zone.N, identity="Warrior")
    eng = _engine([iris, a])
    eng._apply_additional(iris, PeekIdentity(1))            # not in the city
    assert not eng.known_identities.get(0)
    iris.zone = Zone.W                                      # city, but target elsewhere
    eng._apply_additional(iris, PeekIdentity(1))
    assert not eng.known_identities.get(0)
    a.zone = Zone.W                                         # failed tries don't burn the use
    eng._apply_additional(iris, PeekIdentity(1))
    assert eng.known_identities[0] == {1: "Warrior"}


def test_only_iris_can_peek():
    x, a = _p(0, "Cato", Zone.W), _p(1, "A", Zone.W, identity="Warrior")
    eng = _engine([x, a])
    eng._apply_additional(x, PeekIdentity(1))
    assert not eng.known_identities.get(0)


# ---- Mira: feed own food to a same-zone player, who heals food value + 2 ----
def test_mira_feeds_ally_plus_two():
    mira = _p(0, "Mira", Zone.N, hand=[_food("f1", 2)])
    ally = _p(1, "A", Zone.N, hp=4)
    eng = _engine([mira, ally])
    eng._apply_additional(mira, FeedFood(1))
    assert ally.hp == 4 + 2 + 2 and mira.hand == []
    assert any(e.type == "feed" and e.payload["to"] == 1 for e in eng.log.events)


def test_mira_feeds_a_chosen_card_and_can_revive_a_downed_ally():
    mira = _p(0, "Mira", Zone.N, hand=[_food("small", 1), _food("big", 3)])
    ally = _p(1, "A", Zone.N, hp=-2)
    eng = _engine([mira, ally])
    eng._apply_additional(mira, FeedFood(1, "big"))
    assert ally.hp == -2 + 3 + 2 and [c.id for c in mira.hand] == ["small"]


def test_mira_cannot_feed_other_zone_self_or_without_food():
    mira = _p(0, "Mira", Zone.N, hand=[_food("f1", 2)])
    far = _p(1, "A", Zone.E, hp=4)
    eng = _engine([mira, far])
    eng._apply_additional(mira, FeedFood(1))
    eng._apply_additional(mira, FeedFood(0))
    assert far.hp == 4 and mira.hp == 10 and len(mira.hand) == 1
    far.zone = Zone.N
    mira.hand = []
    eng._apply_additional(mira, FeedFood(1))
    assert far.hp == 4


def test_only_mira_can_feed():
    x = _p(0, "Cato", Zone.N, hand=[_food("f1", 2)])
    ally = _p(1, "A", Zone.N, hp=4)
    eng = _engine([x, ally])
    eng._apply_additional(x, FeedFood(1))
    assert ally.hp == 4


# ---- healing never goes past max HP, and never lowers HP ----
def test_feeding_stops_at_max_hp():
    mira, ally = _p(0, "Mira", Zone.N, hand=[_food("f", 3)]), _p(1, "A", Zone.N, hp=8)
    eng = _engine([mira, ally])
    eng._apply_additional(mira, FeedFood(1, "f"))
    assert ally.hp == 10                                  # 8 + 3 + 2 would be 13


def test_eating_stops_at_max_hp():
    p = _p(0, "A", Zone.N, hp=4, hand=[_food("f", 9)])
    eng = _engine([p])
    eng._eat_one_food(p)
    assert p.hp == 10


def test_feast_heal_never_lowers_hp():
    p = _p(0, "A", Zone.CENTER, hp=12)                    # already above max (e.g. an old save)
    eng = _engine([p])
    eng.state.feast_active = True
    eng._feast(p)
    assert p.hp == 12


# ---- anyone may choose to eat a food card (extra action), capped at max HP ----
def test_eating_a_chosen_food_heals_and_uses_the_card():
    from arena.models import EatFood
    a, b = _food("a", 1), _food("b", 2)
    p = _p(0, "X", Zone.N, hp=5, hand=[a, b])
    eng = _engine([p])
    eng._apply_additional(p, EatFood("b"))
    assert p.hp == 7 and b not in p.hand and a in p.hand
    assert any(e.type == "heal" and e.actor == 0 for e in eng.log.events)


def test_eating_needs_that_food_in_hand_and_stops_at_max():
    from arena.models import EatFood
    w = Card("w", CardType.WEAPON, 2, name="棍")
    p = _p(0, "X", Zone.N, hp=9, hand=[w, _food("f", 4)])
    eng = _engine([p])
    eng._apply_additional(p, EatFood("w"))            # not food: nothing happens
    eng._apply_additional(p, EatFood("nope"))
    assert p.hp == 9 and w in p.hand
    eng._apply_additional(p, EatFood("f"))
    assert p.hp == 10
