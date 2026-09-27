import asyncio
import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          Move, Draw, Attack, StealCard, CraftWeapon, PoisonFood)
from arena.players.base import Player
from arena.engine import Engine, build_observation


class FixedRNG:
    def __init__(self, v):
        self.v = v
    def randint(self, a, b):
        return self.v
    def randrange(self, n):
        return 0


def _engine(players, rng=None):
    st = GameState(round_no=2, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat={p.seat: Player() for p in players}, rng=rng or random.Random(0))


def _c(name, t, v, **kw):
    return Card(f"{name}", getattr(CardType, t), v, name=name, **kw)


# ---- Riley: steal on a d4 roll of 4 ----
def test_riley_steals_on_a_four():
    riley = PlayerState(0, Character("Riley", 13, 3), 13, Zone.N)
    victim = PlayerState(1, Character("V", 13, 2), 13, Zone.N, hand=[_c("面包", "FOOD", 2)])
    eng = _engine([riley, victim], rng=FixedRNG(4))
    eng._apply_additional(riley, StealCard(1))
    assert len(riley.hand) == 1 and len(victim.hand) == 0


def test_riley_fails_to_steal_on_low_roll():
    riley = PlayerState(0, Character("Riley", 13, 3), 13, Zone.N)
    victim = PlayerState(1, Character("V", 13, 2), 13, Zone.N, hand=[_c("面包", "FOOD", 2)])
    eng = _engine([riley, victim], rng=FixedRNG(2))
    eng._apply_additional(riley, StealCard(1))
    assert len(riley.hand) == 0 and len(victim.hand) == 1


# ---- Tobias: trident + water zone => draw an extra card ----
def test_tobias_draws_extra_with_trident_in_water():
    tob = PlayerState(0, Character("Tobias", 15, 3), 15, Zone.E,
                      equipped_weapon=_c("三叉戟", "WEAPON", 3))
    eng = _engine([tob])
    eng.state.decks[Zone.E] = [_c("鱼", "FOOD", 2), _c("虾", "FOOD", 1)]
    eng._apply(tob, Draw())
    assert len(tob.hand) == 2      # base 1 + 1 for trident-in-water


# ---- Michael: bow lets him attack an adjacent zone ----
def test_michael_can_target_adjacent_zone_with_bow():
    mic = PlayerState(0, Character("Michael", 11, 3), 11, Zone.N,
                      equipped_weapon=_c("弓", "WEAPON", 2))
    foe = PlayerState(1, Character("F", 13, 2), 13, Zone.CENTER)   # adjacent to forest
    eng = _engine([mic, foe])
    assert 1 in build_observation(eng, 0).attackable_seats


def test_without_bow_only_same_zone_is_attackable():
    mic = PlayerState(0, Character("Michael", 11, 3), 11, Zone.N)
    foe = PlayerState(1, Character("F", 13, 2), 13, Zone.CENTER)
    eng = _engine([mic, foe])
    assert build_observation(eng, 0).attackable_seats == []


# ---- Agatha: craft two basic weapons into a summed weapon ----
def test_agatha_crafts_two_basic_weapons_into_a_stronger_one():
    ag = PlayerState(0, Character("Agatha", 13, 2), 13, Zone.N,
                     hand=[_c("木棍", "WEAPON", 2), _c("石头", "WEAPON", 2)])
    eng = _engine([ag])
    eng._apply_additional(ag, CraftWeapon())
    assert ag.equipped_weapon is not None and ag.equipped_weapon.value == 4   # 2 + 2
    assert not [c for c in ag.hand if c.type == CardType.WEAPON]               # both consumed


# ---- Natalie: poison food card deals -4 on draw ----
def test_natalie_makes_poison_and_it_hurts_whoever_draws_it():
    nat = PlayerState(0, Character("Natalie", 13, 2), 13, Zone.N,
                      hand=[_c("面包", "FOOD", 2), _c("苹果", "FOOD", 2)])
    eng = _engine([nat])
    eng._apply_additional(nat, PoisonFood())
    assert len(nat.hand) == 0                       # two food spent
    poison = [c for c in eng.state.decks[Zone.N] if getattr(c, "poison", False)]
    assert len(poison) == 1
    # someone draws it
    victim = PlayerState(1, Character("V", 13, 2), 13, Zone.N)
    eng.state.players.append(victim)
    eng._draw_one(victim)
    assert victim.hp == 13 - 4 and victim.hand == []   # poison triggers on draw, not kept
