import argparse
import json
import os
import io
import contextlib


def _decide(live, seat, phase, eng):
    """A plain decision for any asked seat: attack someone in reach, else draw; stay put if legal."""
    from arena.engine import build_observation
    if phase == "reflect":
        return {"reflection": "gg"}
    p = eng._p(seat)
    moves = [live.NAME_BY_ZONE[z] for z in (live._legal_zones(eng, p) if phase == "move" else live._next_legal(eng, p))]
    d = {"move": moves[0]}
    if phase == "act":
        atk = build_observation(eng, seat).attackable_seats
        d["action"] = f"attack:{atk[0]}" if atk else "draw"
    return d


def test_board_mode_asks_one_seat_at_a_time_and_finishes(live):
    with contextlib.redirect_stdout(io.StringIO()):
        live.cmd_init(argparse.Namespace(players=5, seed=4, humans=0, human_seats=None, decisions=None, mode=live.BOARD))
    saw_earlier_turn = False
    for _ in range(3000):
        with contextlib.redirect_stdout(io.StringIO()):
            r = live.advance()
        if r["phase"] == "over":
            break
        eng = live._load()
        if r["phase"] == "act":
            assert len(r["waiting"]) == 1                     # strictly one seat's turn at a time
            if eng.act_done:
                prompt = open(f"{live.PROMPT_DIR}/s{r['waiting'][0]}.txt", encoding="utf-8").read()
                saw_earlier_turn |= "在你之前已经行动的: s" in prompt
        os.makedirs(live.DECISION_DIR, exist_ok=True)
        for s in r["waiting"]:
            json.dump(_decide(live, s, r["phase"], eng), open(f"{live.DECISION_DIR}/s{s}.json", "w"))
    else:
        raise AssertionError("board-mode game never ended")
    assert saw_earlier_turn
    assert live._load().check_winner() is not None


def test_human_dice_are_used_for_the_attack(live):
    from arena.models import Zone
    from play import human as H
    with contextlib.redirect_stdout(io.StringIO()):
        live.cmd_init(argparse.Namespace(players=5, seed=4, humans=0, human_seats="0", decisions=None, mode=live.BOARD))
    eng = live._load()
    for p in eng.state.players:
        p.zone = Zone.N
    a = eng._p(0)
    live._act_one(eng, a, {"action": "attack:1", "roll": [1]}, True)
    ev = [e for e in eng.log.events if e.type == "attack"][-1]
    assert ev.payload["dice"] == [1] and ev.payload["roll"] == 1
    live._act_one(eng, a, {"action": "attack:1", "roll": [99]}, True)   # out of range -> the engine rolls
    ev = [e for e in eng.log.events if e.type == "attack"][-1]
    assert 1 <= ev.payload["roll"] <= ev.payload["faces"]
