"""The web app plays the AI seats itself: rule bots here (Claude seats fall back to the bot without a key)."""
import pytest

from app import human_api as A, ai_driver as D


@pytest.fixture
def no_thread(monkeypatch):
    monkeypatch.setattr(D, "kick", lambda: None)          # tests drive the worker's steps by hand
    monkeypatch.setattr(A.ai_driver, "kick", lambda: None)


def _run(live):
    for _ in range(200):
        if not D._step(A):
            return live.advance()
    raise AssertionError("driver never stopped")


def _human_turns(live, eng, adv):
    from play import human as H
    for s in adv["humans"]:
        v = H.human_view(eng, s)
        o = v["options"]
        body = {"move": o["moves"][0], "say": [], "memo": "", "round": v["round"], "phase": v["phase"]}
        if o["kind"] == "act":
            body.update(action=f"attack:{o['attack'][0]}" if o["forced_attack"] else "draw", extra=[])
        code, out = A.post_decision(s, eng.humans[s], body)
        assert code == 200, out


def test_bot_seats_play_until_the_humans_are_asked(live, no_thread):
    code, out = A.new_live_game(True, humans=2, ai=5, seed=3, bot=5, mode="simultaneous")
    assert code == 200
    eng = live._load()
    assert sorted(eng.ai_kinds.values()) == ["bot"] * 5
    adv = _run(live)
    assert adv["phase"] == "move" and adv["ai"] == [] and sorted(adv["humans"]) == sorted(eng.humans)


def test_a_whole_game_runs_with_only_human_clicks(live, no_thread):
    A.new_live_game(True, humans=1, ai=5, seed=5, bot=5, mode="simultaneous")
    for _ in range(80):
        adv = _run(live)
        if adv["phase"] == "over":
            break
        eng = live._load()
        if adv["phase"] == "reflect":                       # an out human: write a reflection
            for s in adv["humans"]:
                assert A.post_decision(s, eng.humans[s], {"reflection": "下次小心"})[0] == 200
            continue
        _human_turns(live, eng, adv)
    assert adv["phase"] == "over"


def test_claude_seats_need_a_key(live, no_thread, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    code, out = A.new_live_game(True, humans=2, ai=5, claude=2, bot=3)
    assert code == 400


def test_chat_driven_games_are_left_alone(live, no_thread):
    A.new_live_game(True, humans=2, ai=5, seed=3)            # no claude/bot: the chat session drives
    assert not D._step(A)
    assert live._load().phase == "start"


def test_claude_answer_is_parsed_and_failures_fall_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fb = {"move": "center", "say": [], "memo": ""}
    monkeypatch.setattr(D, "_ask_claude", lambda p: '```json\n{"move": "forest", "say": [], "memo": "去林区"}\n```')
    assert D._answer("claude", "prompt", fb)["move"] == "forest"
    def boom(p):
        raise RuntimeError("network down")
    monkeypatch.setattr(D, "_ask_claude", boom)
    assert D._answer("claude", "prompt", fb) == fb            # the game never stalls on the API
    assert D._answer("bot", "prompt", fb) == fb
