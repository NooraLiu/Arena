import asyncio
import random
import arena.config as config
from arena.setup import new_game
from arena.players.bots import HeuristicBot


def _game(seed, n=6):
    rng = random.Random(seed)
    return new_game(num_players=n, rng=rng, players_factory=lambda: HeuristicBot(rng))


def test_check_winner_one_and_zero_survivors():
    eng = _game(0)
    for p in eng.state.players[1:]:
        p.alive = False
    assert eng.check_winner() == eng.state.players[0].seat   # exactly one -> that seat
    eng.state.players[0].alive = False
    assert eng.check_winner() == -1                          # zero -> sentinel


def test_zero_survivors_reports_draw_not_crash():
    eng = _game(0, n=2)
    for p in eng.state.players:
        p.alive = False
    result = asyncio.run(eng.play_game())
    assert result["outcome"] == "draw" and result["winner"] is None


def test_round_cap_forces_termination(monkeypatch):
    # A very low cap guarantees the game ends by the backstop while many are still alive.
    monkeypatch.setattr(config, "ROUND_CAP", 2)
    rng = random.Random(0)
    eng = new_game(num_players=6, rng=rng, players_factory=lambda: HeuristicBot(rng))
    result = asyncio.run(eng.play_game())
    assert result["outcome"] == "capped"
    assert result["winner"] is not None        # highest-HP survivor recorded
    assert result["rounds"] == 2


def test_only_the_two_lovers_left_ends_the_game():
    import random
    from arena.setup import new_game
    eng = new_game(6, random.Random(1), lambda: None)
    lovers = [p for p in eng.state.players if p.identity == "Lovers"]
    assert len(lovers) == 2
    for p in eng.state.players:
        p.alive = p in lovers
    assert eng.check_winner() == eng.LOVERS_WIN
    lovers[0].alive = False
    assert eng.check_winner() == lovers[1].seat
