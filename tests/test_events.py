import json
from arena.events import Event, EventLog


def test_event_log_serializes_to_jsonl():
    log = EventLog()
    log.record(Event(type="attack", round_no=2, actor=1,
                      visibility="public", payload={"target": 3, "damage": 4}))
    log.record(Event(type="eliminated", round_no=2, actor=3,
                      visibility="public", payload={}))
    lines = log.to_jsonl().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "attack" and first["payload"]["damage"] == 4


def test_monkeys_and_flood_put_weapons_back_into_the_zone_deck():
    import random
    from arena.models import Zone, Character, PlayerState, GameState, Card, CardType, RandomEvent
    from arena.engine import Engine
    w = lambda i, v: Card(f"w{i}", CardType.WEAPON, v)
    a = PlayerState(0, Character("A", 10, 2), 10, Zone.W, hand=[w(1, 1)], equipped_weapon=w(2, 2))
    b = PlayerState(1, Character("B", 10, 2), 10, Zone.N, equipped_weapon=w(3, 2))
    st = GameState(round_no=4, players=[a, b], decks={z: [] for z in Zone}, open_zones=set(Zone), first_seat=0)
    eng = Engine(state=st, players_by_seat={}, rng=random.Random(0))
    eng.apply_random_event(RandomEvent("E03", "猴群"), Zone.W)
    assert a.equipped_weapon is None and b.equipped_weapon is not None      # only the city was hit
    assert [c.id for c in st.decks[Zone.W]] == ["w2"]                          # back in the city deck
    eng.apply_random_event(RandomEvent("E02", "洪水"), Zone.W)
    assert a.hand == [] and sorted(c.id for c in st.decks[Zone.W]) == ["w1", "w2"]
