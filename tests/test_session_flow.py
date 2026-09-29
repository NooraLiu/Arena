"""Combined turn: the action-phase decision also carries next round's move."""
import random

from arena.setup import new_game
from arena.models import Zone
from play import session as S

DECK = "Arena牌堆表.xlsx"


def _game(zones):
    eng = new_game(len(zones), random.Random(1), lambda: None, data_path=DECK)
    for p, z in zip(eng.state.players, zones):
        p.zone = z
    return eng


def test_act_plan_asks_a_lone_seat_because_it_still_picks_a_move():
    eng = _game([Zone.N, Zone.E, Zone.S, Zone.W, Zone.CENTER, Zone.CENTER])
    auto, ask = S._plan(eng, "act")
    assert 0 in ask                      # alone in forest: action forced, but 3 places to go next


def test_planned_moves_are_used_next_round_without_asking():
    eng = _game([Zone.N, Zone.E, Zone.S, Zone.W, Zone.CENTER, Zone.CENTER])
    S._store_planned(eng, {0: {"action": "draw", "move": "water"}}, {})
    eng.state.round_no += 1
    auto, ask = S._plan(eng, "move")
    assert auto[0] == {"move": "water"} and 0 not in ask


def test_move_that_became_illegal_is_asked_again():
    eng = _game([Zone.N, Zone.E, Zone.S, Zone.W, Zone.CENTER, Zone.CENTER])
    S._store_planned(eng, {1: {"action": "draw", "move": "stone"}}, {})
    eng.state.open_zones.discard(Zone.S)          # stone closed at end of round
    eng.state.round_no += 1
    auto, ask = S._plan(eng, "move")
    assert 1 in ask
    assert "stone" in S._prompt(eng, 1, "move")   # told why it is being asked again


def test_certain_closure_is_not_offered_as_next_move():
    eng = _game([Zone.W, Zone.CENTER, Zone.N, Zone.E, Zone.S])   # 5 alive -> city closes this round
    nxt = [S.NAME_BY_ZONE[z] for z in S._next_legal(eng, eng.state.players[1])]
    assert "city" not in nxt and "center" in nxt
    assert S.NAME_BY_ZONE[S._closing_zone(eng)] == "city"


def test_illegal_planned_move_is_not_stored():
    eng = _game([Zone.N, Zone.E, Zone.S, Zone.W, Zone.CENTER, Zone.CENTER])
    S._store_planned(eng, {0: {"action": "draw", "move": "stone"}}, {})   # forest -> stone not adjacent
    assert 0 not in eng.planned_moves
    eng.state.round_no += 1
    assert 0 in S._plan(eng, "move")[1]
    assert "stone" in S._prompt(eng, 0, "move")          # told its plan was illegal


def test_sandbox_keeps_trial_games_away_from_the_live_game(tmp_path):
    import os, subprocess, sys
    live = "app/live/game.json"
    before = os.path.getmtime(live) if os.path.exists(live) else None
    env = dict(os.environ, ARENA_SANDBOX=str(tmp_path), PYTHONPATH=".")
    env.pop("ARENA_STATE", None)
    for cmd in (["init", "--players", "6", "--seed", "2"], ["plan", "move"]):
        subprocess.run([sys.executable, "play/session.py", *cmd], env=env, check=True, capture_output=True)
    assert (tmp_path / "game.pkl").exists()
    assert (tmp_path / "app_live" / "game.json").exists()
    assert len(list((tmp_path / "play_live" / "prompts").glob("s*.txt"))) == 6
    assert (os.path.getmtime(live) if os.path.exists(live) else None) == before


def _seat_with(eng, identity):
    return next(p.seat for p in eng.state.players if p.identity == identity)


def test_progress_tells_vendetta_its_kill_counted_or_was_stolen():
    eng = _game([Zone.N] * 6)
    v = _seat_with(eng, "Vendetta")
    t = (v + 1) % 6
    assert "还活着" in S._progress(eng, v)
    eng._p(t).alive = False
    eng.killer_of[t] = v
    assert "✅" in S._progress(eng, v)
    eng.killer_of[t] = (v + 2) % 6
    assert "❌" in S._progress(eng, v)


def test_progress_never_names_other_identities():
    eng = _game([Zone.N] * 6)
    for p in eng.state.players:
        line = S._progress(eng, p.seat)
        others = {q.identity for q in eng.state.players if q.identity != p.identity}
        assert not any(i in line for i in others), line
