import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState, Move, Draw, Attack
from arena.players.base import Observation
from arena.players.bots import RandomBot, HeuristicBot


def _obs(legal_moves, attackable):
    ch = Character("X", 5, 3)
    me = PlayerState(seat=1, character=ch, hp=5, zone=Zone.N)
    # attackable seats must correspond to real players in the game state
    others = [PlayerState(seat=s, character=ch, hp=2 + s, zone=Zone.N) for s in attackable]
    st = GameState(round_no=1, players=[me] + others, decks={},
                   open_zones={Zone.N}, first_seat=0)
    return Observation(me=me, state=st, legal_move_zones=legal_moves, attackable_seats=attackable)


def test_random_bot_move_is_legal():
    bot = RandomBot(random.Random(0))
    obs = _obs([Zone.N, Zone.CENTER], [])
    mv = asyncio.run(bot.decide_move(obs))
    assert mv.zone in [Zone.N, Zone.CENTER]


def test_heuristic_attacks_lowest_hp_target():
    bot = HeuristicBot(random.Random(0))
    obs = _obs([Zone.N], attackable=[2, 3])  # seat 2 hp=4, seat 3 hp=5
    action = asyncio.run(bot.decide_action(obs))
    assert isinstance(action, Attack) and action.target_seat == 2  # lowest hp


def test_heuristic_draws_when_no_target():
    bot = HeuristicBot(random.Random(0))
    obs = _obs([Zone.N], attackable=[])
    action = asyncio.run(bot.decide_action(obs))
    assert isinstance(action, Draw)
