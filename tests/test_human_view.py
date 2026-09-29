import argparse
import json
import os

from arena.models import Zone
from play import human as H


def _ns(**kw):
    base = dict(players=6, seed=11, human_seats="0", humans=0, decisions=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _started(live, phase="move"):
    live.cmd_init(_ns())
    live.cmd_startround(_ns())
    live.cmd_plan(_ns(phase=phase))
    return live._load()


def test_view_hides_other_seats_secrets(live):
    eng = _started(live)
    me = eng.state.players[0]
    for q in eng.state.players[1:]:                  # give everyone a card we can look for
        q.hand.append(eng.state.decks[Zone.N].pop())
    eng.post_message(2, 3, "只给s3看的秘密")
    v = H.human_view(eng, 0)
    full = json.dumps(v, ensure_ascii=False)
    for q in eng.state.players[1:]:
        for c in q.hand:
            assert c.id not in full                  # nobody else's hand
    assert "只给s3看的秘密" not in full               # nobody else's private messages
    # identity names: the brief lists the public identity *pool*, so check every other field
    rest = json.dumps({k: v[k] for k in ("players", "messages", "events", "options")}, ensure_ascii=False)
    for q in eng.state.players[1:]:
        assert q.identity not in rest
    assert v["me"]["identity"] == me.identity


def test_round_one_move_hides_positions(live):
    eng = _started(live)
    v = H.human_view(eng, 0)
    assert v["status"] == "your_turn"
    assert all(p["zone"] is None for p in v["players"] if p["seat"] != 0)
    assert v["options"]["kind"] == "move" and "center" in v["options"]["moves"]


def test_auto_resolved_step_is_waiting_not_your_turn(live):
    eng = _started(live)
    for p in eng.state.players:
        p.zone = Zone.N
    eng.state.round_no = 2
    eng.state.open_zones = {Zone.N}                # only one legal place: nobody is asked to move
    eng.phase = "move"
    v = H.human_view(eng, 0)
    assert v["status"] == "waiting" and v["options"] is None


def test_submitted_status_once_decision_file_exists(live):
    eng = _started(live)
    os.makedirs(live.DECISION_DIR, exist_ok=True)
    open(f"{live.DECISION_DIR}/s0.json", "w").write('{"move":"center"}')
    assert H.human_view(eng, 0)["status"] == "submitted"


def test_dead_seat_gets_reflection_box(live):
    eng = _started(live)
    eng.state.players[0].alive = False
    v = H.human_view(eng, 0)
    assert v["status"] == "dead" and v["reflection"]["open"] is True and v["options"] is None


def _act_game(live, zones):
    eng = _started(live)
    for p, z in zip(eng.state.players, zones):
        p.zone = z
    eng.state.round_no = 2
    eng.phase = "act"
    return eng


def test_validate_move(live):
    eng = _started(live)
    assert H.validate_decision(eng, 0, "move", {"move": "center"}) == []
    assert H.validate_decision(eng, 0, "move", {"move": "moon"})


def test_validate_act_rules(live):
    eng = _act_game(live, [Zone.CENTER, Zone.CENTER, Zone.N, Zone.E, Zone.S, Zone.W])
    go = H._options(eng, 0, "act")["moves"][0]
    ok = {"action": "attack:1", "move": go}
    assert H.validate_decision(eng, 0, "act", ok) == []
    assert H.validate_decision(eng, 0, "act", {"action": "attack:s1", "move": go}) == []
    assert H.validate_decision(eng, 0, "act", {"action": "draw", "move": go})      # forced attack
    assert H.validate_decision(eng, 0, "act", {"action": "attack:2", "move": go})  # not here
    assert H.validate_decision(eng, 0, "act", {**ok, "move": "moon"})
    assert H.validate_decision(eng, 0, "act", {**ok, "say": [{"to": "all", "text": "a"}] * 3})
    assert H.validate_decision(eng, 0, "act", {**ok, "extra": ["steal:2"]})
    assert H.validate_decision(eng, 0, "act", {**ok, "extra": ["declare:s1=Nobody"]})


def test_trading_the_equipped_weapon_is_allowed(live):
    eng = _act_game(live, [Zone.N, Zone.N, Zone.E, Zone.S, Zone.W, Zone.CENTER])
    me = eng.state.players[0]
    w = next(c for c in eng.state.decks[Zone.N] if c.type.value == "weapon")
    me.equipped_weapon = w
    d = {"action": "draw", "move": H._options(eng, 0, "act")["moves"][0], "extra": [f"trade:1:{w.id}"]}
    assert H.validate_decision(eng, 0, "act", d) == []
    assert H.validate_decision(eng, 0, "act", {**d, "extra": ["trade:1:no-such-card"]})


def test_validate_reflection(live):
    eng = _started(live)
    assert H.validate_decision(eng, 0, "reflect", {"reflection": "好玩"}) == []
    assert H.validate_decision(eng, 0, "reflect", {"reflection": "  "})
