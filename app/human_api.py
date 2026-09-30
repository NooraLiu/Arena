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


def my_seats(local):
    """Human seats of the current game with their keys -- only for a visitor on this computer,
    so one person playing locally can open /play.html without a seat link."""
    if not local:
        return 403, {"error": "只有在运行服务器的这台电脑上才能直接进入,别的设备请用带口令的链接"}
    with LOCK:
        eng = S._load()
    return 200, {"seats": [{"seat": s, "key": k, "name": eng._p(s).character.name}
                           for s, k in sorted(getattr(eng, "humans", {}).items())]}


def new_live_game(local, humans, ai, force=False, seed=None):
    """Start a fresh live game with `humans` random human seats and `ai` AI seats.
    A game still in progress is never replaced silently: without `force` the answer is 409 and
    nothing changes. Whatever was there (finished or not) is archived first, never deleted.
    Only from this computer."""
    import argparse
    import contextlib
    import io
    import random
    if not local:
        return 403, {"error": "只有在运行服务器的这台电脑上才能开新局"}
    players = humans + ai
    if humans < 0 or ai < 0 or not 5 <= players <= 12:
        return 400, {"error": f"人类 + AI 一共要 5~12 人(现在 {players} 人)"}
    seed = random.randint(0, 10**6) if seed is None else seed
    with LOCK:
        cur = S.game_status()
        if cur and not cur["over"] and not force:
            return 409, {"error": "in_progress", **cur}
        archived = S.archive_current()
        with contextlib.redirect_stdout(io.StringIO()):     # init prints links meant for the CLI
            S.cmd_init(argparse.Namespace(players=players, seed=seed, humans=humans,
                                          human_seats=None, decisions=None))
        eng = S._load()
        eng.seed = seed
        S._save(eng)
    return 200, {"seed": seed, "all_human": _all_human(eng), "archived": archived,
                 "seats": [{"seat": s, "key": k, "name": eng._p(s).character.name}
                           for s, k in sorted(eng.humans.items())]}


def live_status():
    with LOCK:
        return 200, {"game": S.game_status()}
