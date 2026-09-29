"""HTTP-facing logic for human seats, kept free of http.server so tests can call it directly.

Only the server writes a human seat's decision/reflection files. It rewrites the saved game
(via session.advance) only when every seat is human -- otherwise Claude drives the game from
chat and is the only writer of the save.
"""
import json
import os
import threading

from play import session as S
from play import human as H

LOCK = threading.Lock()


def _authorized(eng, seat, key):
    return bool(key) and getattr(eng, "humans", {}).get(seat) == key


def _clean(d, phase):
    """Keep only the keys the session driver reads, in the agents' format."""
    if phase == "reflect":
        return {"reflection": str(d["reflection"]).strip()}
    out = {"move": d["move"], "say": d.get("say") or [], "memo": d.get("memo", "")}
    if phase == "act":
        out = {"action": d.get("action", "draw"), "extra": d.get("extra") or [], **out}
    return out


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _all_human(eng):
    return len(getattr(eng, "humans", {})) == len(eng.state.players)


def get_view(seat, key):
    with LOCK:
        eng = S._load()
        if not _authorized(eng, seat, key):
            return 403, {"error": "链接不对:座位号或口令不匹配"}
        if _all_human(eng) and getattr(eng, "phase", "start") == "start":
            S.advance()                          # all-human game: the first visitor starts it
            eng = S._load()
    return 200, H.human_view(eng, seat)


def post_decision(seat, key, body):
    with LOCK:
        eng = S._load()
        if not _authorized(eng, seat, key):
            return 403, {"error": "链接不对:座位号或口令不匹配"}
        status = H.human_view(eng, seat)["status"]
        if status in ("dead", "over") and not eng._p(seat).alive:
            if H._reflection_text(eng, seat):
                return 409, {"error": "出局感悟已经交过了"}
            errs = H.validate_decision(eng, seat, "reflect", body)
            if errs:
                return 400, {"errors": errs}
            _write(f"{S.HUMAN_DIR}/reflections/s{seat}.json", _clean(body, "reflect"))
            if _all_human(eng):
                S.advance()
            elif eng.phase == "over":            # the orchestrator is done: record it here
                eng = S._load()
                if S._absorb_human_reflections(eng):
                    S._save(eng)
            return 200, {"ok": True}
        stale = ("round" in body and body.get("round") != eng.state.round_no) or \
                ("phase" in body and body.get("phase") != eng.phase)
        if stale or status not in ("your_turn", "submitted"):
            return 409, {"error": "这一步已经结算了,你的提交没有生效。页面已刷新,请看新的局面再决定。"}
        errs = H.validate_decision(eng, seat, eng.phase, body)
        if errs:
            return 400, {"errors": errs}
        _write(f"{S.DECISION_DIR}/s{seat}.json", _clean(body, eng.phase))
        if _all_human(eng):
            S.advance()                          # nobody else will: no AI seats, no Claude needed
        return 200, {"ok": True}
