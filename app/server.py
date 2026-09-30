"""Minimal local web app for Arena: start a live human+AI game, watch it (/), play a seat (/play.html).

Zero dependencies (stdlib http.server). Reuses the real engine.
Run:  python3 app/server.py          (serves http://localhost:8000)
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# make the project importable and cwd-independent
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                              # play/session.py uses project-relative paths

from app import human_api                   # noqa: E402

DECK = os.path.join(ROOT, "Arena牌堆表.xlsx")
PORT = int(os.environ.get("ARENA_PORT", "8000"))
HOST = os.environ.get("ARENA_HOST", "127.0.0.1")


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
        elif u.path == "/api/live_status":
            code, body = human_api.live_status()
            self._send(code, json.dumps(body, ensure_ascii=False))
        elif u.path == "/api/my_seats":
            code, body = human_api.my_seats(self._local())
            self._send(code, json.dumps(body, ensure_ascii=False))
        elif u.path == "/api/view":
            seat, key = self._seat_key(u)
            code, body = (400, {"error": "缺少 seat"}) if seat is None else human_api.get_view(seat, key)
            self._send(code, json.dumps(body, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _seat_key(self, u):
        q = parse_qs(u.query)
        try:
            seat = int(q.get("seat", [""])[0])
        except ValueError:
            seat = None
        return seat, q.get("key", [""])[0]

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/new_live_game":
            q = parse_qs(u.query)
            try:
                humans, ai = int(q.get("humans", ["1"])[0]), int(q.get("ai", ["5"])[0])
            except ValueError:
                return self._send(400, json.dumps({"error": "人数要是数字"}, ensure_ascii=False))
            code, out = human_api.new_live_game(self._local(), humans, ai,
                                                force=q.get("force", ["0"])[0] == "1",
                                                mode=q.get("mode", ["simultaneous"])[0])
            return self._send(code, json.dumps(out, ensure_ascii=False))
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
