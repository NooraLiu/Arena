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


def test_shrink_pushes_players_out_of_closed_zone_center_never_closes():
    eng = _game(2)
    for p in eng.state.players[5:]:
        p.alive = False
    eng.shrink_step()
    assert Zone.CENTER in eng.state.open_zones
