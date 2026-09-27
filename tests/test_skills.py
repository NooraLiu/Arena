import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState, Card, CardType, Move, Draw, Attack
from arena.players.base import Player
from arena.engine import Engine
from arena import skills


class Fixed(Player):
    def __init__(self, action):
        self.action = action

    async def decide_move(self, obs):
        return Move(obs.me.zone)

    async def decide_action(self, obs):
        return self.action


class FakeRNG:
    """Deterministic die: randint always returns `roll`."""
    def __init__(self, roll):
        self.roll = roll

    def randint(self, a, b):
        return self.roll


def _weapon(v, i=0):
    return Card(f"w{i}", CardType.WEAPON, v, name="knife")


def _food(i=0):
    return Card(f"f{i}", CardType.FOOD, 2, name="bread")


def _engine(players, actions, decks=None, first_seat=0, rng=None):
    st = GameState(round_no=2, players=players, decks=decks or {z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=first_seat)
    pbs = {p.seat: Fixed(actions[p.seat]) for p in players}
    return Engine(state=st, players_by_seat=pbs, rng=rng or random.Random(0))


# ---- unit: registry ----
def test_registry_maps_names_and_defaults_to_no_skill():
    assert isinstance(skills.for_character("Bram"), skills.Bram)
    assert isinstance(skills.for_character("Elliot"), skills.Elliot)
    assert isinstance(skills.for_character("Nobody"), skills.NoSkill)   # unknown -> no skill


# ---- Bram: -1 damage in the stone zone ----
def test_bram_takes_one_less_damage_in_stone_zone():
    atk = PlayerState(0, Character("A", 5, 4), 5, Zone.S)
    bram = PlayerState(1, Character("Bram", 15, 2), 15, Zone.S)
    eng = _engine([atk, bram], {0: Attack(1), 1: Draw()}, first_seat=0, rng=FakeRNG(3))
    asyncio.run(eng.action_phase())
    assert bram.hp == 15 - (3 - 1)          # roll 3, reduced by 1


def test_bram_takes_full_damage_outside_stone_zone():
    atk = PlayerState(0, Character("A", 5, 4), 5, Zone.N)
    bram = PlayerState(1, Character("Bram", 15, 2), 15, Zone.N)
    eng = _engine([atk, bram], {0: Attack(1), 1: Draw()}, first_seat=0, rng=FakeRNG(3))
    asyncio.run(eng.action_phase())
    assert bram.hp == 15 - 3


# ---- Elliot: alone -> draw 2, hand limit 6 ----
def test_elliot_draws_two_when_alone():
    elliot = PlayerState(0, Character("Elliot", 13, 2), 13, Zone.N)
    decks = {z: [] for z in Zone}
    decks[Zone.N] = [_food(1), _food(2), _food(3)]
    eng = _engine([elliot], {0: Draw()}, decks=decks)
    asyncio.run(eng.action_phase())
    assert len(elliot.hand) == 2 and len(decks[Zone.N]) == 1


def test_elliot_hand_limit_is_six():
    elliot = PlayerState(0, Character("Elliot", 13, 2), 13, Zone.N,
                         hand=[_food(i) for i in range(6)])
    decks = {z: [] for z in Zone}
    decks[Zone.N] = [_food(9)]
    eng = _engine([elliot], {0: Draw()}, decks=decks)
    asyncio.run(eng.action_phase())          # alone -> tries to draw 2, but deck has 1
    assert len(elliot.hand) == 6             # capped at 6, not 4


# ---- Fae: attack turn in forest also draws ----
def test_fae_draws_after_attacking_in_forest():
    fae = PlayerState(0, Character("Fae", 11, 2), 11, Zone.N)
    victim = PlayerState(1, Character("V", 13, 2), 13, Zone.N)
    decks = {z: [] for z in Zone}
    decks[Zone.N] = [_weapon(1)]
    eng = _engine([fae, victim], {0: Attack(1), 1: Draw()}, decks=decks, first_seat=0, rng=FakeRNG(1))
    asyncio.run(eng.action_phase())
    assert fae.equipped_weapon is not None    # drew the weapon after attacking
    assert decks[Zone.N] == []


def test_fae_does_not_draw_after_attacking_outside_forest():
    fae = PlayerState(0, Character("Fae", 11, 2), 11, Zone.E)
    victim = PlayerState(1, Character("V", 13, 2), 13, Zone.E)
    decks = {z: [] for z in Zone}
    decks[Zone.E] = [_weapon(1)]
    eng = _engine([fae, victim], {0: Attack(1), 1: Attack(0)}, decks=decks, first_seat=0, rng=FakeRNG(1))
    asyncio.run(eng.action_phase())
    assert fae.equipped_weapon is None and len(decks[Zone.E]) == 1   # Fae did not draw after attacking
