import argparse
import json
import os


def _ns(**kw):
    base = dict(players=6, seed=3, human_seats=None, humans=0, decisions=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_init_assigns_chosen_human_seats_with_distinct_keys(live):
    live.cmd_init(_ns(human_seats="1,4"))
    eng = live._load()
    assert set(eng.humans) == {1, 4}
    assert len(set(eng.humans.values())) == 2 and all(len(k) >= 8 for k in eng.humans.values())
    assert eng.phase == "start"


def test_init_random_human_count(live):
    live.cmd_init(_ns(humans=2))
    assert len(live._load().humans) == 2


def test_same_seed_deals_same_identities_with_or_without_humans(live):
    live.cmd_init(_ns())
    a = [p.identity for p in live._load().state.players]
    live.cmd_init(_ns(humans=3))
    b = [p.identity for p in live._load().state.players]
    assert a == b


def test_plan_skips_prompt_files_for_humans_and_reports_them(live, capsys):
    live.cmd_init(_ns(human_seats="0"))
    live.cmd_startround(_ns())
    capsys.readouterr()
    live.cmd_plan(_ns(phase="move"))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["humans"] == [0] and 0 in out["ask"]
    assert not os.path.exists(f"{live.PROMPT_DIR}/s0.txt")
    assert os.path.exists(f"{live.PROMPT_DIR}/s1.txt")
    assert live._load().phase == "move"


def test_save_leaves_no_temp_file(live):
    live.cmd_init(_ns())
    assert not os.path.exists(live.STATE + ".tmp")


def test_endround_never_asks_a_human_for_a_reflection(live):
    live.cmd_init(_ns(human_seats="0"))
    eng = live._load()
    eng.state.players[0].hp = -1
    eng.state.players[1].hp = -1
    live._save(eng)
    live.cmd_endround(_ns())
    eng = live._load()
    assert set(eng.pending_reflect) == {1}
    assert eng.phase == "reflect"
    assert not os.path.exists(f"{live.PROMPT_DIR}/s0.txt")


from arena.engine import build_observation
from arena.models import Zone


def _answer(live, seat, phase):
    """A legal, fight-seeking decision so a test game always ends."""
    eng = live._load()
    p = eng._p(seat)
    if phase == "reflect":
        d = {"reflection": "测试感悟"}
    elif phase == "move":
        legal = live._legal_zones(eng, p)
        z = Zone.CENTER if Zone.CENTER in legal else legal[0]
        d = {"move": live.NAME_BY_ZONE[z]}
    else:
        atk = build_observation(eng, seat).attackable_seats
        nxt = live._next_legal(eng, p)
        z = Zone.CENTER if Zone.CENTER in nxt else nxt[0]
        d = {"action": f"attack:{atk[0]}" if atk else "draw", "move": live.NAME_BY_ZONE[z]}
    os.makedirs(live.DECISION_DIR, exist_ok=True)
    with open(f"{live.DECISION_DIR}/s{seat}.json", "w", encoding="utf-8") as f:
        json.dump(d, f)


def test_advance_waits_and_names_human_and_ai_seats(live):
    live.cmd_init(_ns(human_seats="0"))
    r = live.advance()
    assert r["phase"] == "move"
    assert r["humans"] == [0] and sorted(r["ai"]) == [1, 2, 3, 4, 5]
    assert live.advance() == r                      # nothing changes until someone answers


def test_advance_plays_a_whole_game(live):
    live.cmd_init(_ns(human_seats="0"))
    for _ in range(400):
        r = live.advance()
        if r["phase"] == "over":
            break
        for s in r["waiting"]:
            _answer(live, s, r["phase"])
    eng = live._load()
    assert eng.phase == "over" and eng.check_winner() is not None


def test_human_reflection_is_absorbed_without_blocking(live):
    live.cmd_init(_ns(human_seats="0"))
    eng = live._load()
    eng.state.players[0].hp = -1
    live._save(eng)
    live.cmd_endround(_ns())
    r = live.advance()                              # no AI died: straight on to the next round
    assert r["phase"] == "move" and 0 not in r["waiting"]
    os.makedirs(f"{live.HUMAN_DIR}/reflections", exist_ok=True)
    with open(f"{live.HUMAN_DIR}/reflections/s0.json", "w", encoding="utf-8") as f:
        json.dump({"reflection": "我太早进中心了"}, f)
    live.advance()
    assert live._load().reflections[0] == "我太早进中心了"


def test_agents_are_told_a_human_is_among_them_and_their_guesses_are_kept(live):
    live.cmd_init(_ns(human_seats="3"))
    live.cmd_startround(_ns())
    eng = live._load()
    assert "人类" in live._prompt(eng, 0, "move")
    live._apply_talk(eng, 0, {"human_guess": "s3"}, "move")
    live._apply_talk(eng, 1, {"human_guess": 2}, "move")
    assert eng.human_guesses == {0: [(1, 3)], 1: [(1, 2)]}


def test_no_human_hint_without_humans(live):
    live.cmd_init(_ns())
    live.cmd_startround(_ns())
    assert "人类玩家" not in live._prompt(live._load(), 0, "move")


def test_reflection_with_unescaped_quotes_is_still_read(live):
    os.makedirs(live.DECISION_DIR, exist_ok=True)
    with open(f"{live.DECISION_DIR}/s4.json", "w", encoding="utf-8") as f:
        f.write('{"reflection":"我太"贪心"了,下次先回血"}')
    got = live._load_decisions(_ns())
    assert got[4]["reflection"] == '我太"贪心"了,下次先回血'
