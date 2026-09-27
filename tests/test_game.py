import asyncio
import random
from arena.setup import new_game
from arena.players.bots import HeuristicBot
from arena.models import Zone


def _game(seed, n=6):
    rng = random.Random(seed)
    return new_game(num_players=n, rng=rng, players_factory=lambda: HeuristicBot(rng))


def test_game_terminates_and_reports_rounds():
    result = asyncio.run(_game(1).play_game())
    assert result["outcome"] in ("win", "draw", "capped")
    assert result["rounds"] >= 1


def test_winner_is_last_survivor_when_win():
    for seed in range(5):
        eng = _game(seed)
        result = asyncio.run(eng.play_game())
        if result["outcome"] == "win":
            alive = [p.seat for p in eng.state.players if p.alive]
            assert alive == [result["winner"]]


def test_shrink_closes_a_zone_without_teleporting_occupants():
    eng = _game(2)
    for p in eng.state.players[5:]:
        p.alive = False
    # put a survivor in an outer zone that will close (W = city is first in shrink order)
    from arena.map import legal_moves
    victim = eng.alive_players()[0]
    victim.zone = Zone.W
    eng.shrink_step()
    assert Zone.W not in eng.state.open_zones        # zone removed from the map
    assert Zone.CENTER in eng.state.open_zones        # center never closes
    assert victim.zone == Zone.W                      # NOT teleported — still standing there
    # next round the occupant of the closed zone must move out (can't stay)
    moves = legal_moves(victim.zone, eng.state.open_zones)
    assert Zone.W not in moves and len(moves) >= 1     # only adjacent OPEN zones, no "stay"
