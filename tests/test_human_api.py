import argparse
import json
import os

import pytest

from app import human_api as A


def _ns(**kw):
    base = dict(players=6, seed=11, human_seats="0", humans=0, decisions=None)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def game(live):
    live.cmd_init(_ns())
    live.advance()                               # -> round 1 move, everyone asked
    return live


def _key(live, seat=0):
    return live._load().humans[seat]


def test_wrong_key_or_other_seats_key_is_403(game):
    assert A.get_view(0, "nope")[0] == 403
    assert A.get_view(1, _key(game))[0] == 403    # seat 1 is an AI seat: no key works
    assert A.post_decision(0, "nope", {"move": "center"})[0] == 403


def test_view_and_valid_submission_writes_agent_format(game):
    code, v = A.get_view(0, _key(game))
    assert code == 200 and v["status"] == "your_turn"
    code, r = A.post_decision(0, _key(game), {"move": "center", "memo": "先抢武器"})
    assert code == 200
    d = json.load(open(f"{game.DECISION_DIR}/s0.json", encoding="utf-8"))
    assert d == {"move": "center", "say": [], "memo": "先抢武器"}
    assert A.get_view(0, _key(game))[1]["status"] == "submitted"
    assert A.post_decision(0, _key(game), {"move": "forest"})[0] == 200   # may change before it resolves


def test_invalid_submission_is_400_and_writes_nothing(game):
    code, r = A.post_decision(0, _key(game), {"move": "moon"})
    assert code == 400 and r["errors"]
    assert not os.path.exists(f"{game.DECISION_DIR}/s0.json")


def test_stale_submission_after_step_resolved_is_409(game):
    eng = game._load()
    eng.phase = "over"
    game._save(eng)
    code, r = A.post_decision(0, _key(game), {"move": "center"})
    assert code == 409 and r["error"]


def test_dead_human_can_hand_in_reflection_once(game):
    eng = game._load()
    eng.state.players[0].alive = False
    game._save(eng)
    assert A.post_decision(0, _key(game), {"reflection": "下次不去中心"})[0] == 200
    assert os.path.exists(f"{game.HUMAN_DIR}/reflections/s0.json")
    assert A.post_decision(0, _key(game), {"reflection": "再来一次"})[0] == 409


def test_all_human_game_advances_by_itself(live):
    live.cmd_init(_ns(human_seats="0,1,2,3,4,5"))
    live.advance()
    keys = live._load().humans
    for s in range(6):
        assert A.post_decision(s, keys[s], {"move": "center"})[0] == 200
    eng = live._load()
    assert eng.phase == "act"                     # the last submission resolved the move step


def test_submission_for_a_step_that_already_resolved_is_409(game):
    k = _key(game)
    assert A.post_decision(0, k, {"move": "center", "round": 1, "phase": "act"})[0] == 409
    assert A.post_decision(0, k, {"move": "center", "round": 2, "phase": "move"})[0] == 409
    code, _ = A.post_decision(0, k, {"move": "center", "round": 1, "phase": "move"})
    assert code == 200
    d = json.load(open(f"{game.DECISION_DIR}/s0.json", encoding="utf-8"))
    assert "round" not in d and "phase" not in d


def test_all_human_game_starts_when_someone_opens_the_page(live):
    live.cmd_init(_ns(human_seats="0,1,2,3,4,5"))
    keys = live._load().humans
    code, v = A.get_view(0, keys[0])
    assert code == 200 and v["status"] == "your_turn"


def test_view_shows_what_was_submitted(game):
    k = _key(game)
    A.post_decision(0, k, {"move": "water", "memo": "去水区"})
    v = A.get_view(0, k)[1]
    assert v["submitted"] == {"move": "water", "say": [], "memo": "去水区"}


def test_reflection_after_game_over_reaches_the_record(game):
    eng = game._load()
    eng.state.players[0].alive = False
    eng.phase = "over"
    game._save(eng)
    assert A.post_decision(0, _key(game), {"reflection": "结束后才写"})[0] == 200
    assert game._load().reflections[0] == "结束后才写"


def test_local_visitor_can_list_human_seats_remote_cannot(game):
    code, r = A.my_seats(local=True)
    assert code == 200 and r["seats"] == [{"seat": 0, "key": _key(game), "name": game._load()._p(0).character.name}]
    assert A.my_seats(local=False)[0] == 403


def test_new_live_game_from_the_page_picks_humans_and_ai(live):
    code, r = A.new_live_game(local=True, humans=2, ai=5, seed=5)
    assert code == 200 and len(r["seats"]) == 2 and not r["all_human"] and r["archived"] is None
    eng = live._load()
    assert len(eng.state.players) == 7
    assert {s["seat"]: s["key"] for s in r["seats"]} == eng.humans
    exported = json.load(open(f"{live.APP_LIVE}/game.json", encoding="utf-8"))
    assert exported["humans"] == sorted(eng.humans)
    assert "key" not in json.dumps(exported["humans"])          # seat numbers only, never the keys


def test_new_live_game_is_local_only_and_checks_counts(live):
    assert A.new_live_game(local=False, humans=1, ai=5)[0] == 403
    assert A.new_live_game(local=True, humans=1, ai=3)[0] == 400      # 4 players
    assert A.new_live_game(local=True, humans=7, ai=6)[0] == 400      # 13 players
    assert A.new_live_game(local=True, humans=-1, ai=7)[0] == 400


def test_a_game_in_progress_is_never_replaced_without_asking(live):
    A.new_live_game(local=True, humans=2, ai=4, seed=1)
    live.advance()
    before = open(live.STATE, "rb").read()
    code, r = A.new_live_game(local=True, humans=1, ai=5, seed=2)
    assert code == 409 and r["error"] == "in_progress" and r["players"] == 6
    assert open(live.STATE, "rb").read() == before                   # untouched
    assert A.live_status()[1]["game"]["over"] is False


def test_replacing_a_game_archives_it_first(live):
    import os
    import pickle
    A.new_live_game(local=True, humans=2, ai=4, seed=1)
    old_keys = live._load().humans
    code, r = A.new_live_game(local=True, humans=1, ai=5, seed=2, force=True)
    assert code == 200 and r["archived"] and r["archived"].endswith("-unfinished")
    kept = pickle.load(open(os.path.join(r["archived"], "game.pkl"), "rb"))
    assert kept.humans == old_keys and len(kept.state.players) == 6
    assert os.path.exists(os.path.join(r["archived"], "app_live", "game.json"))
    assert len(live._load().state.players) == 6 and len(live._load().humans) == 1


def test_a_finished_game_is_archived_without_asking(live):
    A.new_live_game(local=True, humans=0, ai=5, seed=1)
    eng = live._load()
    eng.phase, eng.game_over = "over", True
    live._save(eng)
    code, r = A.new_live_game(local=True, humans=2, ai=3, seed=2)
    assert code == 200 and r["archived"] and not r["archived"].endswith("-unfinished")
