"""Minimal local web app for Arena: a button to run a new bot game and watch it.

Zero dependencies (stdlib http.server). Reuses the real engine.
Run:  python3 app/server.py          (serves http://localhost:8000)
"""
import asyncio
import json
import os
import random
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# make the project importable and cwd-independent
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                              # play/session.py uses project-relative paths

from arena.setup import new_game            # noqa: E402
from arena.players.bots import SmartBot     # noqa: E402
from app import human_api                   # noqa: E402

DECK = os.path.join(ROOT, "Arena牌堆表.xlsx")
PORT = int(os.environ.get("ARENA_PORT", "8000"))
HOST = os.environ.get("ARENA_HOST", "127.0.0.1")


ZONE_NAME = {"center": "center", "n": "forest", "e": "water", "s": "stone", "w": "city"}


def _snapshot(eng, round_no):
    return {"round": round_no, "open_zones": [z.value for z in eng.state.open_zones],
            "players": [{"seat": p.seat, "zone": p.zone.value, "hp": p.hp, "alive": p.alive,
                         "equipped": p.equipped_weapon.name if p.equipped_weapon else None,
                         "eq_atk": p.equipped_weapon.value if p.equipped_weapon else 0,
                         "hand": [c.name for c in p.hand]} for p in eng.state.players]}


def run_game(players: int, seed: int) -> dict:
    from arena import config
    rng = random.Random(seed)
    eng = new_game(players, rng, lambda: SmartBot(rng), data_path=DECK)
    roster = [{"seat": p.seat, "name": p.character.name,
               "hp_max": p.character.hp_max, "attack": p.character.base_attack,
               "identity": p.identity} for p in eng.state.players]

    # play round by round, capturing a state snapshot after each round
    snapshots = [_snapshot(eng, 0)]                      # round 0 = starting placement
    outcome, survivor = "capped", None
    while True:
        w = eng.check_winner()
        if w is not None:
            outcome, survivor = {-1: ("draw", None), eng.LOVERS_WIN: ("lovers", None)}.get(w, ("win", w))
            break
        if eng.state.round_no > config.ROUND_CAP:
            alive = eng.alive_players()
            survivor = max(alive, key=lambda p: p.hp).seat if alive else None
            outcome = "capped"
            break
        asyncio.run(eng.play_round())
        snapshots.append(_snapshot(eng, eng.state.round_no - 1))

    events = [{"type": e.type, "round": e.round_no, "actor": e.actor,
               "visibility": e.visibility, "payload": e.payload} for e in eng.log.events]
    winners = eng.identity_winners()
    return {
        "roster": roster,
        "events": events,
        "snapshots": snapshots,
        "winners": {str(k): v for k, v in winners.items()},
        "outcome": outcome,
        "rounds": eng.state.round_no - 1,
        "survivor": survivor,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif u.path == "/api/new_game":
            q = parse_qs(u.query)
            players = max(5, min(12, int(q.get("players", ["6"])[0])))
            seed = int(q.get("seed", [str(random.randint(0, 10**6))])[0])
            try:
                self._send(200, json.dumps({"seed": seed, **run_game(players, seed)}, ensure_ascii=False))
            except Exception as ex:  # surface engine errors to the page
                self._send(500, json.dumps({"error": str(ex)}, ensure_ascii=False))
        elif u.path.startswith("/live/"):
            fp = os.path.join(os.path.dirname(__file__), "live", os.path.basename(u.path))
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    self._send(200, f.read(), "application/json; charset=utf-8")
            else:
                self._send(404, json.dumps({"error": "no live game yet — 用 session.py export 生成"}, ensure_ascii=False))
        elif u.path == "/play.html":
            with open(os.path.join(os.path.dirname(__file__), "play.html"), encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif u.path == "/api/view":
            seat, key = self._seat_key(u)
            code, body = (400, {"error": "缺少 seat"}) if seat is None else human_api.get_view(seat, key)
            self._send(code, json.dumps(body, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def _seat_key(self, u):
        q = parse_qs(u.query)
        try:
            seat = int(q.get("seat", [""])[0])
        except ValueError:
            seat = None
        return seat, q.get("key", [""])[0]

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/decision":
            return self._send(404, json.dumps({"error": "not found"}))
        seat, key = self._seat_key(u)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, json.dumps({"errors": ["请求不是合法 JSON"]}, ensure_ascii=False))
        code, out = (400, {"errors": ["缺少 seat"]}) if seat is None else human_api.post_decision(seat, key, body)
        self._send(code, json.dumps(out, ensure_ascii=False))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Arena app on http://{HOST}:{PORT}  (deck: {DECK})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
