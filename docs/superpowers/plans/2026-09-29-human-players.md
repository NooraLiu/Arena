# Human Players Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one or more humans take seats in an Arena game from a web page (`/play.html`), next to `arena-player` agents or with no agents at all.

**Architecture:** A human seat is just another way to produce `play/live/decisions/sN.json`. `play/session.py` gains human seats (with per-seat keys), a tracked `eng.phase`, and `advance()` (collect decisions → resolve → next step). A new `play/human.py` builds what one seat may see (`human_view`) and checks what it submits (`validate_decision`). `app/human_api.py` wraps those for HTTP; `app/server.py` routes `/play.html`, `GET /api/view`, `POST /api/decision`. With AI seats, Claude calls `advance()` from chat; with only humans, the server calls it after each submission.

**Tech Stack:** Python 3 stdlib only (`http.server`, `pickle`, `secrets`, `threading`), pytest, one static HTML page with inline JS (no libraries).

**Spec:** `docs/superpowers/specs/2026-09-29-human-players-design.md`

Two deliberate deviations from the spec (both simplify, neither changes behavior the user sees):
- The seat view is computed on each `GET /api/view` from the saved game instead of being written to `play/live/human/sN.json` — it can never be stale, and nothing on disk needs protecting.
- Seats are chosen with `--human-seats 2,4` (explicit) or `--humans 1` (random count) instead of one ambiguous `--human` flag.

## Global Constraints

- No new dependencies: stdlib + pytest only; the server stays zero-dependency.
- Engine rules (`arena/`) are not changed.
- A human decision file has exactly the agent format: `{"action","extra","move","say","memo"}` (act), `{"move","say","memo"}` (move); a human reflection is `{"reflection": "..."}`.
- The server listens on `127.0.0.1` unless `ARENA_HOST` is set (e.g. `ARENA_HOST=0.0.0.0` for LAN).
- `ARENA_SANDBOX=<dir>` must keep every file this feature writes under `<dir>` (tests rely on it via monkeypatching the same module constants).
- A seat's view never contains another seat's identity, hand, private messages, memo or thinking — until `phase == "over"`, when all identities and results are shown.
- All UI text is Chinese.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A human submits from a stale page after the step already resolved → server answers 409 with a readable message; the page shows it and refreshes. (Test in Task 4.)
2. The human seat's step is auto-resolved (e.g. alone with one legal move, or forced center attack with one target) → status `"waiting"`, no form; the game does not wait on them. (Test in Task 3.)
3. A link with seat B's number but seat A's key → 403, never seat A's or B's view. (Test in Task 4.)
4. Agent-style variants a human form might still produce — `attack:s2`, trading the *equipped* weapon's id — are accepted, not rejected. (Test in Task 3.)
5. A human who dies mid-round gets the reflection box at once, and the game never waits for it. (Tests in Tasks 2 and 4.)

---

## File Structure

- Modify `play/session.py` — human seats + keys at `init`, `eng.phase` bookkeeping, atomic `_save`, `_event_line` (shared event text), human reflections absorption, `advance()` + `advance` CLI command.
- Create `play/human.py` — `human_view(eng, seat) -> dict`, `validate_decision(eng, seat, phase, d) -> list[str]`. Pure functions over an engine; no file writes.
- Create `app/human_api.py` — `get_view(seat, key)`, `post_decision(seat, key, body)` returning `(status_code, dict)`; file writes and the all-human auto-advance live here.
- Modify `app/server.py` — `os.chdir(ROOT)`, routes, `do_POST`, `ARENA_HOST`.
- Create `app/play.html` — the player page.
- Create `tests/conftest.py` — `live` fixture pointing every session path at `tmp_path`.
- Create `tests/test_human_session.py`, `tests/test_human_view.py`, `tests/test_human_api.py`.

---

### Task 1: Human seats, game phase, atomic save

**Files:**
- Modify: `play/session.py` (`_save` ~l.49, `cmd_init` ~l.60, `cmd_endround` ~l.175, `_ask_reflections` call, `cmd_plan` ~l.714, `main` parser)
- Create: `tests/conftest.py`
- Create: `tests/test_human_session.py`

**Interfaces:**
- Produces:
  - `session.HUMAN_DIR: str` = `f"{PLAY_LIVE}/human"`
  - `eng.humans: dict[int, str]` (seat → key); absent on old saves → treat as `{}` via `getattr(eng, "humans", {})`
  - `eng.phase: str` ∈ `"start" | "move" | "act" | "reflect" | "over"`; `eng.game_over: bool`
  - `session.cmd_init(args)` with `args.human_seats: str|None`, `args.humans: int`
  - `cmd_plan` prints JSON with an extra key `"humans": [seats]` and writes no prompt file for human seats
  - `cmd_endround` never asks a human seat for a reflection
  - fixture `live` (in `tests/conftest.py`) → returns `session` module with paths redirected

- [ ] **Step 1: Write the sandbox fixture**

`tests/conftest.py`:

```python
import pytest

from play import session as S


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Point every file the session driver touches at tmp_path (like ARENA_SANDBOX)."""
    play_live = str(tmp_path / "play_live")
    app_live = str(tmp_path / "app_live")
    monkeypatch.setattr(S, "STATE", str(tmp_path / "game.pkl"))
    monkeypatch.setattr(S, "APP_LIVE", app_live)
    monkeypatch.setattr(S, "PLAY_LIVE", play_live)
    monkeypatch.setattr(S, "LIVE", play_live)
    monkeypatch.setattr(S, "PROMPT_DIR", f"{play_live}/prompts")
    monkeypatch.setattr(S, "DECISION_DIR", f"{play_live}/decisions")
    monkeypatch.setattr(S, "HUMAN_DIR", f"{play_live}/human")
    return S
```

- [ ] **Step 2: Write the failing tests**

`tests/test_human_session.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=. python3 -m pytest tests/test_human_session.py -q`
Expected: FAIL (`AttributeError: ... HUMAN_DIR` from the fixture, then missing `humans`/`phase`).

- [ ] **Step 4: Implement**

In `play/session.py`:

Add `import secrets` to the imports.

Replace `_save`:

```python
def _save(eng):
    tmp = STATE + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(eng, f)
    os.replace(tmp, STATE)             # atomic: the web server may be reading it right now
    _export(eng)                       # keep the spectator page (app/live/game.json) live
```

Next to `PROMPT_DIR` / `DECISION_DIR` add:

```python
HUMAN_DIR = f"{PLAY_LIVE}/human"        # human seats' reflections (play/human.py, app/human_api.py)
```

Add above `cmd_init`:

```python
def _pick_humans(n, seats, count, rng):
    """-> {seat: key}. `seats` like "2,4" wins over a random `count`."""
    if seats:
        chosen = sorted({int(s) for s in str(seats).split(",") if s.strip()})
    else:
        chosen = sorted(rng.sample(range(n), count)) if count else []
    bad = [s for s in chosen if not 0 <= s < n]
    if bad:
        sys.exit(f"! 人类座位超出范围: {bad}")
    return {s: secrets.token_urlsafe(8) for s in chosen}
```

In `cmd_init`, after `eng.briefs = ...` and before the `shutil` cleanup:

```python
    eng.humans = _pick_humans(n, getattr(args, "human_seats", None), getattr(args, "humans", 0) or 0, rng)
    eng.phase = "start"
    eng.game_over = False
```

and extend the cleanup loop to `for d in (PROMPT_DIR, DECISION_DIR, HUMAN_DIR):`. After the final `print(...)` add:

```python
    port = os.environ.get("ARENA_PORT", "8000")
    for s, k in sorted(eng.humans.items()):
        print(f"人类座位 s{s}: http://localhost:{port}/play.html?seat={s}&key={k}")
```

Replace the body of `cmd_endround` from `before = ...` through `_save(eng)` and the `w = ...` line with:

```python
    before = {p.seat for p in eng.alive_players()}
    eng.resolve_deaths()
    eng.shrink_step()
    dead_seats = sorted(before - {p.seat for p in eng.alive_players()})
    dead = [eng._p(s).character.name for s in dead_seats]
    humans = getattr(eng, "humans", {})
    ask = [s for s in dead_seats if s not in humans]
    _ask_reflections(eng, ask)                        # one last call per fallen AI seat
    eng.state.round_no += 1
    eng.state.first_seat = (eng.state.first_seat + 1) % len(eng.state.players)
    w = eng.check_winner()
    eng.game_over = w is not None
    pending = bool(ask and getattr(eng, "pending_reflect", None))
    eng.phase = "reflect" if pending else ("over" if eng.game_over else "start")
    _save(eng)
```

keep the message building, and change the last two lines to

```python
    if ask:
        print(json.dumps({"reflect": ask}))
```

Replace `cmd_plan` with:

```python
def cmd_plan(args):
    """Decide who must be asked, and write each asked AI seat's private prompt to its own file."""
    import shutil
    eng = _load()
    if getattr(eng, "pending_reflect", None):
        _absorb_reflections(eng)
    auto, ask = _plan(eng, args.phase)
    humans = getattr(eng, "humans", {})
    for d in (PROMPT_DIR, DECISION_DIR):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    for seat in ask:
        if seat in humans:
            continue                                   # humans read /api/view instead
        with open(f"{PROMPT_DIR}/s{seat}.txt", "w", encoding="utf-8") as f:
            f.write(_prompt(eng, seat, args.phase))
    eng.phase = args.phase
    _save(eng)
    print(json.dumps({"auto": {str(k): v for k, v in auto.items()}, "ask": ask,
                      "humans": [s for s in ask if s in humans]}, ensure_ascii=False))
```

In `main()`, extend the `init` parser:

```python
    pi = sub.add_parser("init"); pi.add_argument("--players", type=int, default=5); pi.add_argument("--seed", type=int, default=0)
    pi.add_argument("--human-seats", dest="human_seats", default=None, help="e.g. 2,4")
    pi.add_argument("--humans", type=int, default=0, help="number of random human seats")
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=. python3 -m pytest -q`
Expected: all pass (the previous 123 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add play/session.py tests/conftest.py tests/test_human_session.py
git commit -m "feat(play): human seats with keys, tracked game phase, atomic save

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `advance()` — one call moves the game as far as it can

**Files:**
- Modify: `play/session.py` (new helpers near `cmd_reflect`; `main`; module docstring)
- Test: `tests/test_human_session.py`

**Interfaces:**
- Consumes: `eng.phase`, `eng.humans`, `eng.game_over`, `HUMAN_DIR` (Task 1)
- Produces:
  - `session.advance(max_steps: int = 500) -> dict` with keys `phase: str`, `waiting: list[int]`, `ai: list[int]`, `humans: list[int]` (the last three empty when `phase == "over"`)
  - `session._absorb_human_reflections(eng) -> bool` — reads `{HUMAN_DIR}/reflections/sN.json`
  - CLI: `python3 play/session.py advance` prints the dict as JSON

- [ ] **Step 1: Write the failing tests** (append to `tests/test_human_session.py`)

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. python3 -m pytest tests/test_human_session.py -q`
Expected: FAIL with `AttributeError: module 'play.session' has no attribute 'advance'`.

- [ ] **Step 3: Implement**

In `play/session.py`, below `cmd_reflect`:

```python
def _ns(**kw):
    return argparse.Namespace(decisions=None, **kw)


def _absorb_human_reflections(eng):
    """Human seats hand in reflections whenever they like (never blocking the game):
    app/human_api.py writes {HUMAN_DIR}/reflections/sN.json; pick them up here."""
    if not hasattr(eng, "reflections"):
        eng.reflections = {}
    got = False
    for seat in getattr(eng, "humans", {}):
        fp = f"{HUMAN_DIR}/reflections/s{seat}.json"
        if seat in eng.reflections or not os.path.exists(fp):
            continue
        try:
            text = str(json.load(open(fp, encoding="utf-8")).get("reflection") or "").strip()
        except Exception:
            continue
        if text:
            died = next((r for r, seats in eng.deaths_by_round if seat in seats), eng.state.round_no)
            eng.reflections[seat] = text
            _record_thinking(eng, seat, "reflect", text, round_no=died)
            got = True
    return got


def advance(max_steps=500):
    """Move the game forward until someone has to answer, or it is over.
    -> {"phase", "waiting": seats still to answer, "ai": those that are agents, "humans": those that are people}.
    Every step reuses the cmd_* functions, so the rules are exactly the manual flow's."""
    for _ in range(max_steps):
        eng = _load()
        if _absorb_human_reflections(eng):
            _save(eng)
        ph = getattr(eng, "phase", "start")
        humans = getattr(eng, "humans", {})
        if ph == "over":
            return {"phase": "over", "waiting": [], "ai": [], "humans": []}
        if ph == "start":
            cmd_startround(_ns())
            cmd_plan(_ns(phase="move"))
            continue
        need = sorted(getattr(eng, "pending_reflect", {}) or {}) if ph == "reflect" else _plan(eng, ph)[1]
        have = set(_load_decisions(_ns()))
        missing = [s for s in need if s not in have]
        if missing:
            return {"phase": ph, "waiting": missing,
                    "ai": [s for s in missing if s not in humans],
                    "humans": [s for s in missing if s in humans]}
        if ph == "reflect":
            _absorb_reflections(eng)
            eng.phase = "over" if getattr(eng, "game_over", False) else "start"
            _save(eng)
        elif ph == "move":
            cmd_movephase(_ns())
            cmd_plan(_ns(phase="act"))
        else:
            cmd_actphase(_ns())
            cmd_endround(_ns())
    raise RuntimeError("advance(): too many steps without anyone to ask")


def cmd_advance(args):
    print(json.dumps(advance(), ensure_ascii=False))
```

Also make `cmd_reflect` pick up human reflections — change its first lines to:

```python
def cmd_reflect(args):
    eng = _load()
    _absorb_reflections(eng)
    _absorb_human_reflections(eng)
    _save(eng)
```

In `main()` add `sub.add_parser("advance")` and `"advance": cmd_advance` to the dispatch dict.

At the end of the module docstring add:

```
  python3 play/session.py init --players 6 --seed 7 --humans 1     # 1 random human seat (prints its link)
  python3 play/session.py advance     # resolve whatever is ready; prints who must answer next:
                                      # {"phase","waiting","ai","humans"} — ask the "ai" seats' agents,
                                      # humans answer on /play.html; call advance again
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=. python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add play/session.py tests/test_human_session.py
git commit -m "feat(play): advance() drives a game step by step; human reflections never block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: What a human seat sees, and checking what it submits

**Files:**
- Modify: `play/session.py` — extract `_event_line(e) -> str|None` from `_prompt`
- Create: `play/human.py`
- Create: `tests/test_human_view.py`

**Interfaces:**
- Consumes: `session._plan`, `_extras`, `_next_legal`, `_legal_zones`, `_progress`, `_card_str`, `_memos`, `_seat`, `NAME_BY_ZONE`, `ZONE_BY_NAME`, `WIN_COND`, `SKILL_TXT`, `DECISION_DIR`, `HUMAN_DIR`, `eng.phase`, `eng.humans`
- Produces:
  - `session._event_line(e) -> str | None` (e.g. `"r3 s1→s4 伤3"`)
  - `human.human_view(eng, seat: int) -> dict` — keys: `seat, round, phase, status, open_zones, deck_left, feast_active, feast_next, frozen, players, me, messages, events, options, brief, reflection, result`
    - `status` ∈ `"your_turn" | "submitted" | "waiting" | "dead" | "over"`
    - `options` is `None` unless status is `your_turn`/`submitted`; move: `{"kind":"move","moves":[zone]}`; act: `{"kind":"act","attack":[seat],"forced_attack":bool,"extras":[{"kind",...}],"moves":[zone],"say_to":[seat],"identities":[name]}`
    - `reflection` is `None` unless dead: `{"open": bool, "text": str|None}`
  - `human.validate_decision(eng, seat, phase, d: dict) -> list[str]` (empty = OK); `phase` ∈ `"move" | "act" | "reflect"`

- [ ] **Step 1: Extract `_event_line`** (pure refactor)

In `play/session.py` add above `_prompt`:

```python
def _event_line(e):
    """One public event as short text for prompts and the player page (None = not shown)."""
    pl = e.payload or {}
    r = f"r{e.round_no}"
    if e.type == "attack":
        return f"{r} s{e.actor}→s{pl['target']} 伤{pl['damage']}"
    if e.type == "eliminated":
        return f"{r} ☠ s{e.actor} 淘汰"
    if e.type == "random_event":
        return f"{r} ⚡{pl['name']}@{pl['zone']} 命中{pl['hits']}"
    if e.type == "zone_closed":
        return f"{r} 关闭 {pl['zone']}"
    if e.type == "bomb":
        return f"{r} 💥{pl['zone']} 炸到 s{pl['hit']}"
    if e.type == "feed":
        return f"{r} s{e.actor} 喂 s{pl['to']} 吃东西(→{pl['hp']}血)"
    if e.type == "feast_heal":
        return f"{r} s{e.actor} 盛宴回血(→{pl['hp']}血)"
    if e.type in PUBLIC_EV:
        return f"{r} s{e.actor} {e.type}"
    return None
```

and in `_prompt` replace the `for e in recent[-15:]:` loop body (the whole `pl = ...` / `if e.type == ...` chain) with:

```python
        for e in recent[-15:]:
            L.append("  " + _event_line(e))
```

Run: `PYTHONPATH=. python3 -m pytest -q` — Expected: all pass (behavior unchanged).

- [ ] **Step 2: Write the failing tests**

`tests/test_human_view.py`:

```python
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
```

- [ ] **Step 3: Run to verify failure**

Run: `PYTHONPATH=. python3 -m pytest tests/test_human_view.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'play.human'`.

- [ ] **Step 4: Implement `play/human.py`**

```python
"""What one human seat may see, and checking what it submits.

Pure functions over an engine: nothing here writes files. The rules for what is legal come from
play/session.py (the same helpers that build the agents' prompts), so a human and an agent in
the same seat are offered exactly the same choices.
"""
import os

from arena.engine import build_observation
from arena.models import Zone, CardType
from play import session as S

MAX_SAY = 2
MAX_TEXT = 200
MAX_MEMO = 400


def _names(zones):
    return [S.NAME_BY_ZONE[z] for z in sorted(zones, key=lambda z: z.value)]


def _card(c):
    return {"id": c.id, "name": c.name, "type": c.type.value, "value": c.value, "label": S._card_str(c)}


def _asked(eng, seat, phase):
    return phase in ("move", "act") and seat in S._plan(eng, phase)[1]


def _has_decision(seat):
    return os.path.exists(f"{S.DECISION_DIR}/s{seat}.json")


def _reflection_text(eng, seat):
    text = getattr(eng, "reflections", {}).get(seat)
    if text:
        return text
    fp = f"{S.HUMAN_DIR}/reflections/s{seat}.json"
    if os.path.exists(fp):
        import json
        try:
            return json.load(open(fp, encoding="utf-8")).get("reflection")
        except Exception:
            return None
    return None


def _status(eng, seat):
    ph = getattr(eng, "phase", "start")
    if ph == "over":
        return "over"
    if not eng._p(seat).alive:
        return "dead"
    if _asked(eng, seat, ph):
        return "submitted" if _has_decision(seat) else "your_turn"
    return "waiting"


def _extra_options(eng, p):
    mates = [q.seat for q in eng.alive_players() if q.seat != p.seat and q.zone == p.zone]
    out = []
    for x in S._extras(eng, p):
        kind = x.split(":")[0].split("(")[0]
        o = {"kind": kind}
        if kind == "trade":
            cards = [_card(c) for c in p.hand]
            if p.equipped_weapon:
                cards.append({**_card(p.equipped_weapon), "label": "已装备 " + S._card_str(p.equipped_weapon)})
            o.update(targets=mates, cards=cards)
        elif kind == "steal":
            o["targets"] = [s for s in mates if eng._p(s).hand]
        elif kind == "peek":
            o["targets"] = mates
        elif kind == "feed":
            o.update(targets=mates, cards=[_card(c) for c in p.hand if c.type == CardType.FOOD])
        elif kind == "bomb":
            o["zones"] = _names(eng.state.open_zones)
        out.append(o)
    return out


def _options(eng, seat, phase):
    p = eng._p(seat)
    if phase == "move":
        return {"kind": "move", "moves": _names(S._legal_zones(eng, p))}
    atk = build_observation(eng, seat).attackable_seats
    return {"kind": "act", "attack": list(atk),
            "forced_attack": p.zone == Zone.CENTER and bool(atk),
            "extras": _extra_options(eng, p),
            "moves": _names(S._next_legal(eng, p)),
            "say_to": [q.seat for q in eng.alive_players() if q.seat != seat],
            "identities": sorted({q.identity for q in eng.state.players if q.identity})}


def human_view(eng, seat):
    st, p = eng.state, eng._p(seat)
    ph = getattr(eng, "phase", "start")
    status = _status(eng, seat)
    blind = ph == "move" and st.round_no == 1
    players = []
    for q in st.players:
        eq = q.equipped_weapon
        players.append({"seat": q.seat, "name": q.character.name, "hp": q.hp, "hp_max": q.character.hp_max,
                        "alive": q.alive,
                        "zone": None if (blind and q.seat != seat) else S.NAME_BY_ZONE[q.zone],
                        "weapon": eq.name if eq else None, "weapon_value": eq.value if eq else 0})
    lover = None
    if p.identity == "Lovers":
        lover = next((q.seat for q in st.players if q.identity == "Lovers" and q.seat != seat), None)
    known = getattr(eng, "known_identities", {}).get(seat, {})
    me = {"name": p.character.name, "hp": p.hp, "hp_max": p.character.hp_max,
          "base_attack": p.character.base_attack, "attack": S._atk(p),
          "skill": S.SKILL_TXT.get(p.character.name, ""), "zone": S.NAME_BY_ZONE[p.zone],
          "hand": [_card(c) for c in p.hand],
          "equipped": _card(p.equipped_weapon) if p.equipped_weapon else None,
          "identity": p.identity, "win_condition": S.WIN_COND.get(p.identity, ""),
          "progress": S._progress(eng, seat), "lover": lover,
          "known": {str(k): v for k, v in known.items()},
          "declared": [[s, i] for s, i in eng.declarations.get(seat, [])],
          "memo": S._memos(eng).get(seat, "")}
    messages = [{"round": m.round_no, "from": m.sender, "to": m.to, "text": m.text}
                for m in eng.visible_messages(seat)][-40:]
    events = [line for line in (S._event_line(e) for e in eng.log.events) if line][-30:]
    view = {"seat": seat, "round": st.round_no, "phase": ph, "status": status,
            "open_zones": _names(st.open_zones),
            "deck_left": {S.NAME_BY_ZONE[z]: len(st.decks.get(z, [])) for z in st.open_zones},
            "feast_active": st.feast_active, "feast_next": st.feast_next,
            "frozen": _names(st.frozen_zones),
            "players": players, "me": me, "messages": messages, "events": events,
            "options": _options(eng, seat, ph) if status in ("your_turn", "submitted") else None,
            "brief": getattr(eng, "briefs", {}).get(seat, ""),
            "reflection": None, "result": None}
    if status == "dead":
        text = _reflection_text(eng, seat)
        view["reflection"] = {"open": not text, "text": text}
    if status == "over":
        wins = eng.identity_winners()
        view["result"] = {"identities": {str(q.seat): q.identity for q in st.players},
                          "winners": {str(s): t for s, t in wins.items() if t}}
        text = _reflection_text(eng, seat)
        view["reflection"] = {"open": not p.alive and not text, "text": text}
    return view


def _check_say(say, opts, errs):
    if not isinstance(say, list) or len(say) > MAX_SAY:
        errs.append(f"最多 {MAX_SAY} 条喊话")
        return
    for m in say:
        if not isinstance(m, dict):
            errs.append("喊话格式不对")
            continue
        to = m.get("to", "all")
        if to not in ("all", None):
            try:
                ok = S._seat(to) in opts["say_to"]
            except ValueError:
                ok = False
            if not ok:
                errs.append(f"不能私聊 {to}")
        text = str(m.get("text") or "").strip()
        if not text or len(text) > MAX_TEXT:
            errs.append(f"喊话要有内容且不超过 {MAX_TEXT} 字")


def _check_extra(eng, seat, x, opts, errs):
    kind, _, rest = str(x).partition(":")
    if kind == "declare":
        for pair in [s for s in rest.split(",") if s.strip()]:
            s, _, ident = pair.partition("=")
            try:
                target = S._seat(s)
            except ValueError:
                errs.append(f"声明写法不对: {pair}")
                continue
            if target == seat or not 0 <= target < len(eng.state.players) or ident.strip() not in opts["identities"]:
                errs.append(f"声明写法不对: {pair}")
        return
    o = next((o for o in opts["extras"] if o["kind"] == kind), None)
    if o is None:
        errs.append(f"现在不能用 {kind}")
        return
    try:
        if kind in ("trade", "feed"):
            to, _, cid = rest.partition(":")
            if S._seat(to) not in o["targets"] or cid not in {c["id"] for c in o["cards"]}:
                errs.append(f"{kind} 的对象或牌不对: {rest}")
        elif kind in ("steal", "peek"):
            if S._seat(rest.split("(")[0]) not in o["targets"]:
                errs.append(f"{kind} 的对象不对: {rest}")
        elif kind == "bomb":
            if rest.strip() not in o["zones"]:
                errs.append(f"炸弹的区不对: {rest}")
    except ValueError:
        errs.append(f"{kind} 写法不对: {rest}")


def validate_decision(eng, seat, phase, d):
    errs = []
    if not isinstance(d, dict):
        return ["决策必须是一个 JSON 对象"]
    if phase == "reflect":
        text = str(d.get("reflection") or "").strip()
        if not text:
            errs.append("感悟不能为空")
        elif len(text) > 2000:
            errs.append("感悟太长了(最多 2000 字)")
        return errs
    opts = _options(eng, seat, phase)
    if d.get("move") not in opts["moves"]:
        errs.append(f"去不了 {d.get('move')},可去: {', '.join(opts['moves'])}")
    memo = d.get("memo", "")
    if not isinstance(memo, str) or len(memo) > MAX_MEMO:
        errs.append(f"备忘最多 {MAX_MEMO} 字")
    if phase == "act":
        _check_say(d.get("say") or [], opts, errs)
        act = str(d.get("action", "draw"))
        if act == "draw":
            if opts["forced_attack"]:
                errs.append("在中心有别人时必须攻击")
        elif act.startswith("attack:"):
            try:
                ok = S._seat(act.split(":", 1)[1]) in opts["attack"]
            except ValueError:
                ok = False
            if not ok:
                errs.append(f"不能攻击 {act.split(':', 1)[1]}(可攻击: {opts['attack'] or '无'})")
        else:
            errs.append("主行动只能是 draw 或 attack:座位")
        extra = d.get("extra") or []
        if not isinstance(extra, list):
            errs.append("附加行动格式不对")
        else:
            for x in extra:
                _check_extra(eng, seat, x, opts, errs)
    else:
        say_opts = {"say_to": [q.seat for q in eng.alive_players() if q.seat != seat]}
        _check_say(d.get("say") or [], say_opts, errs)
    return errs
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=. python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add play/session.py play/human.py tests/test_human_view.py
git commit -m "feat(play): human seat view and decision validation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: HTTP API for human seats

**Files:**
- Create: `app/human_api.py`
- Create: `app/__init__.py` (empty, so tests can `from app import human_api`)
- Modify: `app/server.py` (top of file: `os.chdir(ROOT)`; `do_GET`; new `do_POST`; `__main__`)
- Create: `tests/test_human_api.py`

**Interfaces:**
- Consumes: `human.human_view`, `human.validate_decision`, `session._load`, `session.advance`, `session.DECISION_DIR`, `session.HUMAN_DIR`, `eng.humans`, `eng.phase`
- Produces:
  - `human_api.get_view(seat: int, key: str) -> tuple[int, dict]`
  - `human_api.post_decision(seat: int, key: str, body: dict) -> tuple[int, dict]`
  - HTTP: `GET /play.html`, `GET /api/view?seat=N&key=K`, `POST /api/decision?seat=N&key=K` (JSON body)

- [ ] **Step 1: Write the failing tests**

`tests/test_human_api.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. python3 -m pytest tests/test_human_api.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.human_api'` (if `app` is not importable, also create an empty `app/__init__.py` in Step 3).

- [ ] **Step 3: Implement `app/human_api.py`** (and an empty `app/__init__.py` if missing)

```python
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


def get_view(seat, key):
    with LOCK:
        eng = S._load()
    if not _authorized(eng, seat, key):
        return 403, {"error": "链接不对:座位号或口令不匹配"}
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
            if len(eng.humans) == len(eng.state.players):
                S.advance()
            return 200, {"ok": True}
        if status not in ("your_turn", "submitted"):
            return 409, {"error": "现在不需要你提交(这一步可能已经结算了),页面会自动刷新"}
        errs = H.validate_decision(eng, seat, eng.phase, body)
        if errs:
            return 400, {"errors": errs}
        _write(f"{S.DECISION_DIR}/s{seat}.json", _clean(body, eng.phase))
        if len(eng.humans) == len(eng.state.players):
            S.advance()                          # nobody else will: no AI seats, no Claude needed
        return 200, {"ok": True}
```

- [ ] **Step 4: Wire the routes in `app/server.py`**

Right after `sys.path.insert(0, ROOT)` add:

```python
os.chdir(ROOT)                              # play/session.py uses project-relative paths
```

After the existing imports add:

```python
from app import human_api                   # noqa: E402

HOST = os.environ.get("ARENA_HOST", "127.0.0.1")
```

In `do_GET`, before the final `else`, add:

```python
        elif u.path == "/play.html":
            with open(os.path.join(os.path.dirname(__file__), "play.html"), encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif u.path == "/api/view":
            seat, key = self._seat_key(u)
            code, body = (400, {"error": "缺少 seat"}) if seat is None else human_api.get_view(seat, key)
            self._send(code, json.dumps(body, ensure_ascii=False))
```

Add to `Handler`:

```python
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
```

Change `__main__` to:

```python
if __name__ == "__main__":
    print(f"Arena app on http://{HOST}:{PORT}  (deck: {DECK})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=. python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/human_api.py app/server.py app/__init__.py tests/test_human_api.py
git commit -m "feat(app): /api/view and /api/decision for human seats; all-human games advance themselves

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The player page `/play.html`

**Files:**
- Create: `app/play.html`

**Interfaces:**
- Consumes: `GET /api/view?seat=N&key=K` (Task 3's view dict), `POST /api/decision?seat=N&key=K`

- [ ] **Step 1: Write the page**

`app/play.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arena 玩家席</title>
<style>
  :root{--bg:#0f1220;--card:#191d33;--card2:#12162a;--ink:#e8eaf2;--dim:#9aa0bd;--line:#2a2f4a;
        --hit:#ff6b6b;--win:#ffd166;--zone:#6ea8fe;--ok:#7ee787;--dm:#c3a6ff;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.5 -apple-system,"PingFang SC",system-ui,sans-serif}
  header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  h1{font-size:17px;margin:0 8px 0 0}
  .pill{padding:3px 10px;border-radius:999px;background:var(--card);border:1px solid var(--line);font-size:13px}
  .pill.turn{background:#2b5a33;border-color:#3f8a4b;color:#dfffe4;font-weight:600}
  main{max-width:1080px;margin:0 auto;padding:14px 16px}
  .grid{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:12px}
  .panel h3{margin:0 0 8px;font-size:14px;color:var(--dim)}
  .map{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,minmax(76px,auto));gap:8px}
  .zone{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:8px}
  .zone.closed{opacity:.3} .zone.here{border-color:var(--ok)}
  .zone .zt{font-size:12px;color:var(--dim);margin-bottom:4px}
  .zc{grid-column:2;grid-row:2}.zn{grid-column:2;grid-row:1}.ze{grid-column:3;grid-row:2}.zs{grid-column:2;grid-row:3}.zw{grid-column:1;grid-row:2}
  .tok{display:inline-block;margin:2px;padding:2px 7px;border-radius:8px;border:1px solid var(--line);background:#0e1226;font-size:12.5px}
  .tok.me{border-color:var(--ok)} .tok.dead{opacity:.4;text-decoration:line-through}
  .row{margin:3px 0} .k{color:var(--dim);font-size:12px}
  .card{display:inline-block;margin:2px;padding:2px 7px;border-radius:6px;background:var(--card2);border:1px solid var(--line);font-size:12.5px}
  .msg{padding:3px 0;border-bottom:1px solid #22273f;font-size:13px} .msg.dm{color:var(--dm)}
  .scroll{max-height:260px;overflow:auto}
  select,input,textarea,button{font:inherit;color:var(--ink);background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:6px 9px}
  textarea{width:100%;min-height:60px}
  button{cursor:pointer;background:#2b3566;border-color:#3a469a;font-weight:600}
  button:disabled{opacity:.5;cursor:default}
  .field{margin:8px 0} .field label{display:block;color:var(--dim);font-size:12.5px;margin-bottom:3px}
  .extra{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:4px 0}
  .err{color:var(--hit);white-space:pre-wrap;margin:6px 0}
  .ok{color:var(--ok)}
  details pre{white-space:pre-wrap;font:12.5px/1.5 inherit;color:#cdd3f0;max-height:420px;overflow:auto}
  .big{font-size:15px;color:var(--win)}
</style>
</head>
<body>
<header>
  <h1>⚔️ Arena 玩家席</h1>
  <span id="who" class="pill">连接中…</span>
  <span id="round" class="pill"></span>
  <span id="status" class="pill"></span>
  <span id="zones" style="color:var(--dim);font-size:13px"></span>
</header>
<main>
  <div id="fatal" class="err"></div>
  <div class="grid">
    <div>
      <div class="panel"><h3>地图</h3><div class="map" id="map"></div></div>
      <div class="panel" id="formPanel" style="display:none"><h3 id="formTitle">你的决定</h3><div id="form"></div></div>
      <div class="panel" id="reflectPanel" style="display:none"><h3>出局感悟</h3><div id="reflect"></div></div>
      <div class="panel" id="resultPanel" style="display:none"><h3>对局结果</h3><div id="result"></div></div>
    </div>
    <div>
      <div class="panel"><h3>我</h3><div id="me"></div></div>
      <div class="panel"><h3>消息</h3><div id="msgs" class="scroll"></div></div>
      <div class="panel"><h3>公开事件</h3><div id="events" class="scroll"></div></div>
      <div class="panel"><details><summary>规则与我的开局简报</summary><pre id="brief"></pre></details></div>
    </div>
  </div>
</main>
<script>
const Q = new URLSearchParams(location.search);
const SEAT = Q.get("seat"), KEY = Q.get("key");
const API = (p) => `${p}?seat=${encodeURIComponent(SEAT)}&key=${encodeURIComponent(KEY)}`;
const ZN = {center:"中心",forest:"林",water:"水",stone:"石",city:"城"};
const ZC = {center:"zc",forest:"zn",water:"ze",stone:"zs",city:"zw"};
const STATUS = {your_turn:"轮到你了",submitted:"已提交,等待其他人",waiting:"等待其他人",dead:"你已出局",over:"游戏结束"};
let V = null, SIG = "", EDITING = false;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const nm = (s) => { const p = V.players.find(p => p.seat === +s); return p ? `s${p.seat} ${p.name}` : `s${s}`; };

async function poll() {
  try {
    const r = await fetch(API("/api/view"), {cache: "no-store"});
    const d = await r.json();
    if (!r.ok) { $("fatal").textContent = d.error || "读取失败"; return; }
    $("fatal").textContent = "";
    const sig = JSON.stringify(d);
    if (sig === SIG) return;
    const stepChanged = !V || V.round !== d.round || V.phase !== d.phase || V.status !== d.status;
    SIG = sig; V = d;
    render(stepChanged);
  } catch (e) { $("fatal").textContent = "连不上服务器,重试中…"; }
}

function render(stepChanged) {
  const me = V.me;
  $("who").textContent = `s${V.seat} ${me.name}`;
  $("round").textContent = `第 ${V.round} 回合 · ${V.phase === "move" ? "移动" : V.phase === "act" ? "行动" : V.phase}`;
  $("status").textContent = STATUS[V.status] || V.status;
  $("status").className = "pill" + (V.status === "your_turn" ? " turn" : "");
  const extra = [V.feast_active ? "盛宴生效中" : "", V.feast_next ? "下回合盛宴" : "", V.frozen.length ? "沙尘暴:" + V.frozen.map(z => ZN[z]).join("、") : ""].filter(Boolean);
  $("zones").textContent = "剩余牌:" + Object.entries(V.deck_left).map(([z, n]) => `${ZN[z]} ${n}`).join(" · ") + (extra.length ? " · " + extra.join(" · ") : "");
  renderMap(); renderMe(); renderMsgs();
  $("brief").textContent = V.brief;
  if (stepChanged || !EDITING) renderForm();
  renderReflect(); renderResult();
}

function renderMap() {
  $("map").innerHTML = Object.keys(ZN).map(z => {
    const here = V.players.filter(p => p.zone === z);
    const closed = !V.open_zones.includes(z);
    const toks = here.map(p => `<span class="tok ${p.seat === V.seat ? "me" : ""} ${p.alive ? "" : "dead"}">s${p.seat} ${esc(p.name)} ${p.hp}/${p.hp_max}${p.weapon ? " · " + esc(p.weapon) + "+" + p.weapon_value : ""}</span>`).join("");
    return `<div class="zone ${ZC[z]} ${closed ? "closed" : ""} ${V.me.zone === z ? "here" : ""}"><div class="zt">${ZN[z]}${closed ? "(已关闭)" : ""}</div>${toks}</div>`;
  }).join("");
  const unknown = V.players.filter(p => p.zone === null);
  if (unknown.length) $("map").insertAdjacentHTML("beforeend", `<div class="k" style="grid-column:1/4">位置未知(第一回合同时暗选):${unknown.map(p => "s" + p.seat + " " + esc(p.name)).join("、")}</div>`);
}

function renderMe() {
  const m = V.me;
  const known = Object.entries(m.known).map(([s, i]) => `${nm(s)} = ${esc(i)}`).join(";");
  $("me").innerHTML = `
    <div class="row">${m.hp}/${m.hp_max} 血 · 攻击 ${m.base_attack}+武器 = ${m.attack} · 在 ${ZN[m.zone]}</div>
    <div class="row"><span class="k">技能</span> ${esc(m.skill)}</div>
    <div class="row"><span class="k">装备</span> ${m.equipped ? `<span class="card">${esc(m.equipped.label)}</span>` : "无"}</div>
    <div class="row"><span class="k">手牌</span> ${m.hand.map(c => `<span class="card">${esc(c.label)}</span>`).join("") || "无"}</div>
    <div class="row big">秘密身份:${esc(m.identity)}</div>
    <div class="row"><span class="k">胜利条件</span> ${esc(m.win_condition)}</div>
    <div class="row">${esc(m.progress)}</div>
    ${m.lover !== null ? `<div class="row">你的恋人:${nm(m.lover)}</div>` : ""}
    ${known ? `<div class="row">你已确认:${known}</div>` : ""}
    ${m.declared.length ? `<div class="row">你已声明:${m.declared.map(([s, i]) => nm(s) + "=" + esc(i)).join(",")}</div>` : ""}
    ${m.memo ? `<div class="row"><span class="k">你的备忘</span> ${esc(m.memo)}</div>` : ""}`;
}

function renderMsgs() {
  $("msgs").innerHTML = V.messages.slice().reverse().map(x => {
    const tag = x.to === null ? "公开" : (x.to === V.seat ? "私聊给你" : `你私聊 ${nm(x.to)}`);
    return `<div class="msg ${x.to === null ? "" : "dm"}">r${x.round} <b>${nm(x.from)}</b> [${tag}]:${esc(x.text)}</div>`;
  }).join("") || `<div class="k">还没有消息</div>`;
  $("events").innerHTML = V.events.slice().reverse().map(e => `<div class="msg">${esc(e)}</div>`).join("") || `<div class="k">还没有事件</div>`;
}

function opt(v, label, sel) { return `<option value="${esc(v)}" ${sel ? "selected" : ""}>${esc(label)}</option>`; }

function renderForm() {
  EDITING = false;
  const o = V.options;
  if (!o) { $("formPanel").style.display = "none"; return; }
  $("formPanel").style.display = "";
  $("formTitle").textContent = V.status === "submitted" ? "已提交(结算前可以修改)" : "你的决定";
  let h = "";
  if (o.kind === "act") {
    h += `<div class="field"><label>主行动${o.forced_attack ? "(你在中心,必须攻击)" : ""}</label><select id="f_action">
      ${o.forced_attack ? "" : opt("draw", "抽一张本区牌")}
      ${o.attack.map(s => opt("attack:" + s, "攻击 " + nm(s))).join("")}</select></div>`;
    h += `<div class="field"><label>附加行动(可选)</label>${o.extras.map(extraRow).join("") || `<span class="k">现在没有可用的附加行动</span>`}
      <div class="extra"><label><input type="checkbox" data-x="declare"> 声明身份</label>
      ${V.players.filter(p => p.seat !== V.seat).map(p => `<span>${nm(p.seat)} <select data-decl="${p.seat}">${opt("", "—")}${o.identities.map(i => opt(i, i)).join("")}</select></span>`).join("")}</div></div>`;
  }
  h += `<div class="field"><label>${o.kind === "act" ? "下回合去哪" : "这回合去哪"}</label><select id="f_move">${o.moves.map(z => opt(z, ZN[z])).join("")}</select></div>`;
  const to = (o.say_to || V.players.filter(p => p.alive && p.seat !== V.seat).map(p => p.seat));
  for (const i of [0, 1]) {
    h += `<div class="field"><label>喊话 ${i + 1}(可空)</label><div class="extra"><select id="f_to${i}">${opt("all", "公开")}${to.map(s => opt(s, "私聊 " + nm(s))).join("")}</select>
      <input id="f_say${i}" maxlength="200" style="flex:1;min-width:200px"></div></div>`;
  }
  h += `<div class="field"><label>备忘(只有你自己下回合能看到)</label><textarea id="f_memo" maxlength="400">${esc(V.me.memo)}</textarea></div>`;
  h += `<div id="f_err" class="err"></div><button id="f_go">${V.status === "submitted" ? "修改提交" : "提交"}</button> <span id="f_ok" class="ok"></span>`;
  $("form").innerHTML = h;
  $("form").oninput = () => { EDITING = true; };
  $("f_go").onclick = submit;
}

function extraRow(x) {
  const k = x.kind;
  const label = {trade:"交换(给同区玩家一张牌)",steal:"偷牌(掷 d4 出 4 成功)",craft:"合成武器",poison:"下毒(2 食物→毒食物)",peek:"偷看身份(每局一次)",feed:"喂食",bomb:"做炸弹"}[k] || k;
  let h = `<div class="extra"><label><input type="checkbox" data-x="${k}"> ${label}</label>`;
  if (x.targets) h += `<select data-t="${k}">${x.targets.map(s => opt(s, nm(s))).join("")}</select>`;
  if (x.cards) h += `<select data-c="${k}">${x.cards.map(c => opt(c.id, c.label)).join("")}</select>`;
  if (x.zones) h += `<select data-z="${k}">${x.zones.map(z => opt(z, ZN[z])).join("")}</select>`;
  return h + `</div>`;
}

function collect() {
  const o = V.options, d = {move: $("f_move").value, memo: $("f_memo").value.trim(), say: []};
  for (const i of [0, 1]) {
    const t = $("f_say" + i).value.trim();
    if (t) { const to = $("f_to" + i).value; d.say.push({to: to === "all" ? "all" : +to, text: t}); }
  }
  if (o.kind === "act") {
    d.action = $("f_action").value;
    d.extra = [];
    document.querySelectorAll("[data-x]").forEach(cb => {
      if (!cb.checked) return;
      const k = cb.dataset.x;
      if (k === "declare") {
        const pairs = [...document.querySelectorAll("[data-decl]")].filter(s => s.value).map(s => `s${s.dataset.decl}=${s.value}`);
        if (pairs.length) d.extra.push("declare:" + pairs.join(","));
        return;
      }
      const t = document.querySelector(`[data-t="${k}"]`), c = document.querySelector(`[data-c="${k}"]`), z = document.querySelector(`[data-z="${k}"]`);
      d.extra.push([k, t && t.value, c && c.value, z && z.value].filter(v => v !== null && v !== undefined && v !== "").join(":"));
    });
  }
  return d;
}

async function post(body) {
  const r = await fetch(API("/api/decision"), {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  return [r.status, await r.json()];
}

async function submit() {
  $("f_go").disabled = true; $("f_err").textContent = ""; $("f_ok").textContent = "";
  const [code, r] = await post(collect());
  $("f_go").disabled = false;
  if (code === 200) { EDITING = false; $("f_ok").textContent = "已提交 ✓"; SIG = ""; poll(); }
  else $("f_err").textContent = (r.errors || [r.error]).join("\n");
  if (code === 409) { SIG = ""; poll(); }
}

function renderReflect() {
  const r = V.reflection;
  if (!r) { $("reflectPanel").style.display = "none"; return; }
  $("reflectPanel").style.display = "";
  if (!r.open) { $("reflect").innerHTML = `<div class="row">${esc(r.text || "")}</div>`; return; }
  if ($("r_text")) return;
  $("reflect").innerHTML = `<div class="k">写写你的计划、哪里失误了、对游戏节奏的看法。之后你只能看公开信息,等游戏结束。</div>
    <textarea id="r_text" maxlength="2000"></textarea><div id="r_err" class="err"></div><button id="r_go">提交感悟</button>`;
  $("r_go").onclick = async () => {
    const [code, res] = await post({reflection: $("r_text").value});
    if (code === 200) { SIG = ""; $("reflect").innerHTML = ""; poll(); } else $("r_err").textContent = (res.errors || [res.error]).join("\n");
  };
}

function renderResult() {
  const r = V.result;
  if (!r) { $("resultPanel").style.display = "none"; return; }
  $("resultPanel").style.display = "";
  $("result").innerHTML = V.players.map(p => {
    const w = r.winners[p.seat];
    return `<div class="row">${nm(p.seat)} · ${esc(r.identities[p.seat])} · ${p.alive ? "存活" : "出局"}${w ? ` · <span class="big">赢得 ${esc(w.join("、"))}</span>` : ""}</div>`;
  }).join("") + `<div class="row"><a href="/" style="color:var(--zone)">打开观战页看完整回放和所有人的思考 →</a></div>`;
}

if (!SEAT || !KEY) $("fatal").textContent = "链接缺少 seat 或 key 参数";
else { poll(); setInterval(poll, 2000); }
</script>
</body>
</html>
```

- [ ] **Step 2: Try it in the browser**

```bash
PYTHONPATH=. ARENA_SANDBOX=/private/tmp/arena_ui_check python3 play/session.py init --players 6 --seed 5 --humans 1
PYTHONPATH=. ARENA_SANDBOX=/private/tmp/arena_ui_check python3 play/session.py advance
```

Start the app server with the same `ARENA_SANDBOX` (add a launch configuration `arena-app-sandbox` to `.claude/launch.json` with `"env": {"ARENA_SANDBOX": "/private/tmp/arena_ui_check"}`, or run it in the terminal with that env var), open the printed link, and check:
- the map shows positions as unknown in round 1; the form offers every zone;
- submitting a move shows "已提交" and the view status becomes `submitted`;
- write the AI seats' decisions (e.g. with `_answer` from Task 2's test or by hand), run `advance`, and the page moves to the action form within 2 s; an illegal choice made with the browser dev tools (e.g. editing the move option value) shows the server's error text;
- no console errors (`read_console_messages`); take a screenshot.

- [ ] **Step 3: Commit**

```bash
git add app/play.html .claude/launch.json
git commit -m "feat(app): player page /play.html

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Running a game with a human (for the Claude driving it)

1. `python3 play/session.py init --players 6 --seed S --humans 1` → give the printed link to the user; do not post identities.
2. Loop: `python3 play/session.py advance` →
   - for each seat in `"ai"`: run the `arena-player` agent on `play/live/prompts/sN.txt`;
   - if `"humans"` is non-empty: wait for `play/live/decisions/sN.json` (Monitor with an until-loop on the file), telling the user "第 N 回合,等你提交";
   - call `advance` again; stop when `phase == "over"`, then `python3 play/session.py reflect` to collect late human reflections.
3. In chat, report only public events until the game is over.
