import asyncio
import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          Move, Draw, Attack, PlantBomb, TradeCard)
from arena.players.base import Player
from arena.engine import Engine
from arena import config, skills


class Scripted(Player):
    """Fixed main action + optional list of additional actions (once)."""
    def __init__(self, action, extras=None):
        self.action = action
        self.extras = list(extras or [])

    async def decide_move(self, obs):
        return Move(obs.me.zone)

    async def decide_action(self, obs):
        return self.action

    async def decide_additional_actions(self, obs):
        out, self.extras = self.extras, []
        return out


def _ammo(i):
    return Card(f"ammo{i}", CardType.AMMO, 1, name="碎片")


def _engine(players, bots, decks=None, first_seat=0, rng=None):
    st = GameState(round_no=2, players=players, decks=decks or {z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=first_seat)
    return Engine(state=st, players_by_seat=bots, rng=rng or random.Random(0))


# ---- fragment requirements ----
def test_normal_player_needs_three_fragments():
    assert skills.for_character("Nobody").bomb_fragments() == 3


def test_garcia_needs_two_fragments():
    assert skills.for_character("Garcia").bomb_fragments() == 2


def test_cato_cannot_make_bombs():
    assert skills.for_character("Cato").can_make_bomb() is False
    assert skills.for_character("Nobody").can_make_bomb() is True


# ---- planting consumes fragments and schedules a bomb ----
def test_plant_bomb_consumes_fragments_and_detonates_next_round():
    planter = PlayerState(0, Character("P", 13, 3), 13, Zone.N, hand=[_ammo(1), _ammo(2), _ammo(3)])
    victim = PlayerState(1, Character("V", 13, 2), 13, Zone.E)   # will be in E when it blows
    bots = {0: Scripted(Draw(), extras=[PlantBomb(Zone.E)]), 1: Scripted(Draw())}
    eng = _engine([planter, victim], bots, first_seat=0)
    asyncio.run(eng.action_phase())               # round 2: plant, scheduled for round 3
    assert len(planter.hand) == 0                 # 3 fragments spent
    assert len(eng.state.bombs) == 1 and eng.state.bombs[0].detonate_round == 3
    eng.state.round_no = 3                          # advance to the detonation round
    eng._detonate_bombs()
    assert victim.hp == 13 - config.BOMB_DAMAGE
    assert eng.state.bombs == []                  # consumed


def test_bomb_damage_reduced_by_armor_and_hits_the_planter_too():
    armor = Card("s", CardType.ARMOR, 2, name="盾")
    planter = PlayerState(0, Character("P", 13, 3), 13, Zone.E,
                          hand=[_ammo(1), _ammo(2), _ammo(3), armor])
    eng = _engine([planter], {0: Scripted(Draw(), extras=[PlantBomb(Zone.E)])}, first_seat=0)
    asyncio.run(eng.action_phase())               # round 2: plant in own zone E
    eng.state.round_no = 3
    eng._detonate_bombs()                          # planter still in E, no immunity
    assert planter.hp == 13 - (config.BOMB_DAMAGE - 2)   # armor reduces by its value


def test_cato_plant_bomb_is_ignored():
    cato = PlayerState(0, Character("Cato", 15, 4), 15, Zone.N, hand=[_ammo(i) for i in range(3)])
    eng = _engine([cato], {0: Scripted(Draw(), extras=[PlantBomb(Zone.E)])}, first_seat=0)
    asyncio.run(eng.action_phase())
    assert eng.state.bombs == [] and len(cato.hand) == 3   # nothing consumed, no bomb


# ---- trading cards ----
def test_trade_card_moves_it_to_the_other_player():
    card = Card("gift", CardType.FOOD, 2, name="面包")
    a = PlayerState(0, Character("A", 13, 3), 13, Zone.N, hand=[card])
    b = PlayerState(1, Character("B", 13, 3), 13, Zone.N)
    bots = {0: Scripted(Draw(), extras=[TradeCard(to_seat=1, card_id="gift")]), 1: Scripted(Draw())}
    eng = _engine([a, b], bots, first_seat=0)
    asyncio.run(eng.action_phase())
    assert card not in a.hand and card in b.hand
