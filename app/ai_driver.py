"""Plays the AI seats of a live game inside the web app, so a game runs with nobody driving it from chat.

Each AI seat is one of:
  "claude"  Claude, through the Anthropic API: it gets the same private prompt the chat agents read
            (play/live/prompts/sN.txt) and answers with the same JSON decision.
  "bot"     the rule-based SmartBot: instant and free, but it never talks or reasons about identities.
  "agent"   left alone: a Claude Code session drives it from chat (the arena-drive skill).
A game made before seats had kinds (no eng.ai_kinds) is left entirely to chat, as before.

kick() wakes one background worker; it advances the game until it has to wait for a human (or is
over), answering every AI seat on the way. The save file is only touched under human_api.LOCK, and
never while waiting on the API: decisions are written only if the game is still at the same step.
"""
import asyncio
import json
import os
import random
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from play import session as S
from play import human as H
from arena.engine import build_observation
from arena.players.bots import SmartBot

MODEL = os.environ.get("ARENA_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("ARENA_EFFORT", "low")
KINDS = ("claude", "bot", "agent")

SYSTEM = """你在玩桌游 Arena,扮演一个角色,目标是赢。规则、你的角色、秘密身份、推荐打法和本回合局面都在用户消息里。
按消息末尾的决策格式,只回复决策 JSON 本身(不要代码块,不要其他文字)。
- 移动只能选"可去"列出的区。行动阶段的决策里也要填 move(下回合去哪)。
- say 最多 2 条,to 填 "all" 或座位号(私聊)。
- memo(≤200 字)写你的推理、怀疑和计划——下回合你只能看到它。"""

_client = None
_wake = threading.Event()
_thread = None
status = {"busy": False, "error": None}       # shown on the start page


def claude_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def driven(eng):
    """Does this app play the game's AI seats (rather than a chat session)?"""
    kinds = getattr(eng, "ai_kinds", None)
    return bool(kinds) and any(k in ("claude", "bot") for k in kinds.values())


def kick():
    """Ask the worker to look at the game again (cheap; safe to call any time)."""
    global _thread
    _wake.set()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_worker, name="arena-ai", daemon=True)
        _thread.start()


def _worker():
    from app import human_api as A
    while True:
        _wake.wait()
        _wake.clear()
        try:
            while _step(A):
                pass
            status["error"] = None
        except Exception as ex:                # keep the worker alive; show the error on the start page
            status["error"] = f"{type(ex).__name__}: {ex}"
            traceback.print_exc()
        finally:
            status["busy"] = False


def _step(A):
    """Advance once and answer the AI seats it stopped for. -> True if there is more to do now."""
    with A.LOCK:
        eng = S._load() if os.path.exists(S.STATE) else None
        if eng is None or not driven(eng):
            return False
        adv = S.advance()
        kinds = getattr(eng, "ai_kinds", {})
        mine = [s for s in adv["ai"] if kinds.get(s) in ("claude", "bot")]
        if adv["phase"] == "over" or not mine:
            return False
        eng = S._load()
        mark = (getattr(eng, "game_id", None), eng.state.round_no, eng.phase)
        jobs = {}
        for s in mine:
            fp = f"{S.PROMPT_DIR}/s{s}.txt"
            prompt = open(fp, encoding="utf-8").read() if os.path.exists(fp) else ""
            jobs[s] = (kinds[s], prompt, _bot_decision(eng, s, adv["phase"]))
    status["busy"] = True
    with ThreadPoolExecutor(max_workers=8) as ex:
        answers = dict(zip(jobs, ex.map(lambda s: _answer(*jobs[s]), jobs)))
    with A.LOCK:
        eng = S._load()
        if (getattr(eng, "game_id", None), eng.state.round_no, eng.phase) != mark:
            return True                        # the game moved on meanwhile (new game?): look again
        for s, d in answers.items():
            A._write(f"{S.DECISION_DIR}/s{s}.json", d)
    return True


def _answer(kind, prompt, fallback):
    if kind != "claude" or not prompt or not claude_available():
        return fallback
    try:
        text = _ask_claude(prompt)
        d = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return d if isinstance(d, dict) else fallback
    except Exception as ex:                    # a failed call never stalls the game: the bot answers
        status["error"] = f"Claude 调用失败,这一步由规则机器人代打:{type(ex).__name__}: {ex}"
        return fallback


def _ask_claude(prompt):
    import anthropic
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    resp = _client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                   # a declined request is re-run on a fallback model
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("模型拒绝了这一步")
    return "".join(b.text for b in resp.content if b.type == "text")


def _bot_decision(eng, seat, phase):
    """A SmartBot decision, already in the agents' JSON format."""
    if phase == "reflect":
        return {"reflection": "(规则机器人)按血量和局面行动,没有更多想法。"}
    p, bot = eng._p(seat), SmartBot(random.Random())
    obs = build_observation(eng, seat)
    opts = H._options(eng, seat, phase)
    run = asyncio.run
    want = S.NAME_BY_ZONE.get(run(bot.decide_move(obs)).zone)
    move = want if want in opts["moves"] else (S.NAME_BY_ZONE[p.zone] if S.NAME_BY_ZONE[p.zone] in opts["moves"] else opts["moves"][0])
    if phase == "move":
        return {"move": move, "say": [], "memo": ""}
    act = run(bot.decide_action(obs))
    tgt = getattr(act, "target_seat", None)
    action = f"attack:{tgt}" if tgt in opts["attack"] else "draw"
    return {"action": action, "extra": [], "move": move, "say": [], "memo": ""}
