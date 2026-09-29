import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          Draw, RandomEvent)
from arena.players.base import Player
from arena.engine import Engine
from arena import config


class FixedRNG:
    def __init__(self, v): self.v = v
    def randint(self, a, b): return self.v
    def randrange(self, n): return 0
    def shuffle(self, x): pass


def _c(name, t, v):
    return Card(name, getattr(CardType, t), v, name=name)


def _engine(players, rng=None, round_no=4):
    st = GameState(round_no=round_no, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat={p.seat: Player() for p in players},
                  rng=rng or random.Random(0))


def _ev(eid, name="x"):
    return RandomEvent(id=eid, name=name)


def test_wolves_deal_4_to_the_target_zone_only():
    a = PlayerState(0, Character("A", 10, 2), 10, Zone.N)
    b = PlayerState(1, Character("B", 10, 2), 10, Zone.E)   # elsewhere
    eng = _engine([a, b])
    eng.apply_random_event(_ev("E01"), Zone.N)
    assert a.hp == 10 - config.EVENT_WOLF_DAMAGE and b.hp == 10


def test_fireballs_hit_all_zones_except_center_and_water():
    ppl = [PlayerState(0, Character("N", 10, 2), 10, Zone.N),
           PlayerState(1, Character("E", 10, 2), 10, Zone.E),
           PlayerState(2, Character("S", 10, 2), 10, Zone.S),
           PlayerState(3, Character("C", 10, 2), 10, Zone.CENTER)]
    eng = _engine(ppl)
    eng.apply_random_event(_ev("E06"), Zone.N)               # target arg ignored for E06
    d = config.EVENT_FIRE_DAMAGE
    assert ppl[0].hp == 10 - d and ppl[2].hp == 10 - d       # forest, stone burned
    assert ppl[1].hp == 10 and ppl[3].hp == 10               # water, center safe


def test_flood_discards_hand_weapons_but_keeps_equipped():
    p = PlayerState(0, Character("A", 10, 2), 10, Zone.S,
                    equipped_weapon=_c("好刀", "WEAPON", 4),
                    hand=[_c("木棍", "WEAPON", 2), _c("面包", "FOOD", 2)])
    eng = _engine([p])
    eng.apply_random_event(_ev("E02"), Zone.S)
    assert p.equipped_weapon is not None                     # equipped survives
    assert [c.name for c in p.hand] == ["面包"]               # hand weapon washed away


def test_ape_steals_the_equipped_weapon():
    p = PlayerState(0, Character("A", 10, 2), 10, Zone.W, equipped_weapon=_c("弓", "WEAPON", 2))
    eng = _engine([p])
    eng.apply_random_event(_ev("E03"), Zone.W)
    assert p.equipped_weapon is None


def test_sandstorm_freezes_the_zone():
    p = PlayerState(0, Character("A", 10, 2), 10, Zone.S)
    eng = _engine([p])
    eng.apply_random_event(_ev("E04"), Zone.S)
    assert Zone.S in eng.state.frozen_zones


def test_hungry_dogs_take_two_food_else_damage():
    fed = PlayerState(0, Character("A", 10, 2), 10, Zone.N,
                      hand=[_c("面包", "FOOD", 2), _c("苹果", "FOOD", 2), _c("刀", "WEAPON", 2)])
    starving = PlayerState(1, Character("B", 10, 2), 10, Zone.N, hand=[_c("面包", "FOOD", 2)])
    eng = _engine([fed, starving])
    eng.apply_random_event(_ev("E07"), Zone.N)
    assert [c.name for c in fed.hand] == ["刀"] and fed.hp == 10     # paid 2 food, no damage
    assert starving.hp == 10 - config.EVENT_DOGS_DAMAGE              # couldn't pay -> hurt


def test_feast_telegraphs_and_center_draws_extra_next():
    p = PlayerState(0, Character("A", 10, 2), 10, Zone.CENTER)
    eng = _engine([p])
    eng.state.decks[Zone.CENTER] = [_c("m1", "FOOD", 1), _c("m2", "FOOD", 1), _c("m3", "FOOD", 1)]
    eng.apply_random_event(_ev("E08"), Zone.N)
    assert eng.state.feast_next is True                       # telegraphed for NEXT round
    # simulate the round rollover that activates the telegraphed feast
    eng.state.feast_active, eng.state.feast_next = eng.state.feast_next, False
    eng._apply(p, Draw())                                     # 1 base + 2 feast bonus = 3
    assert len(p.hand) == 1 + config.EVENT_FEAST_BONUS


def test_maybe_event_only_fires_on_event_rounds_and_consumes_one():
    p = PlayerState(0, Character("A", 10, 2), 10, Zone.N)
    eng = _engine([p], rng=FixedRNG(1), round_no=5)           # 5 is NOT an event round
    eng.state.events = [_ev("E01")]
    assert eng.maybe_random_event() is None and len(eng.state.events) == 1
    eng.state.round_no = 4                                     # 4 IS an event round; d4=1 -> forest(N)
    fired = eng.maybe_random_event()
    assert fired is not None and len(eng.state.events) == 0
    assert p.hp == 10 - config.EVENT_WOLF_DAMAGE              # forest wolves hit the seat there


def test_event_only_targets_open_outer_zones_then_center():
    import random
    from arena.models import Zone
    from arena import config
    from arena.setup import new_game
    eng = new_game(6, random.Random(3), lambda: None, data_path="Arena牌堆表.xlsx")
    assert len(eng.state.events) >= 4
    eng.state.round_no = config.EVENT_ROUNDS[0]
    eng.state.open_zones = {Zone.CENTER, Zone.N}          # every outer zone but forest has closed
    for _ in range(3):
        _, zone = eng.maybe_random_event()
        assert zone == Zone.N
    eng.state.open_zones = {Zone.CENTER}
    _, zone = eng.maybe_random_event()
    assert zone == Zone.CENTER


def test_feast_draws_extra_center_cards_or_heals_once_the_center_is_empty():
    import random
    from arena.models import Zone, Draw
    from arena import config
    from arena.setup import new_game
    eng = new_game(6, random.Random(3), lambda: None, data_path="Arena牌堆表.xlsx")
    p = eng.state.players[0]
    for q in eng.state.players[1:]:
        q.zone = Zone.N
    p.zone = Zone.CENTER
    eng.state.feast_active = True
    left = len(eng.state.decks[Zone.CENTER])
    eng._apply(p, Draw())
    base = eng._skill(p).draw_count(p, True, Zone.CENTER)          # e.g. Elliot draws 2 when alone
    assert len(eng.state.decks[Zone.CENTER]) == left - base - config.EVENT_FEAST_BONUS
    eng.state.decks[Zone.CENTER] = []
    p.hand.clear()
    p.hp = 4
    eng._apply(p, Draw())
    assert p.hp == 4 + config.EVENT_FEAST_HEAL
    p.hp = p.character.hp_max - 1
    eng._apply(p, Draw())
    assert p.hp == p.character.hp_max                    # never above max
