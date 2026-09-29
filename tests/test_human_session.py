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
