"""Step-through play harness: drive a real Arena game one phase at a time,
so an LLM (or a human) can play every seat. State is pickled between calls.

Usage:
  python3 play/session.py init --players 5 --seed 7
  ARENA_SANDBOX=<dir> python3 play/session.py ...   # trial game: all files under <dir>
  python3 play/session.py snapshot            # public + (for the driver) private state as JSON
  python3 play/session.py move '{"0":"forest","1":"center",...}'   # simultaneous movement
  python3 play/session.py detonate            # blow up bombs due this round
  python3 play/session.py act 0 draw
  python3 play/session.py act 1 attack 3
  python3 play/session.py act 2 bomb city
  python3 play/session.py act 2 trade 3 <card_id>
  python3 play/session.py init --players 6 --seed 7 --humans 1     # 1 random human seat (prints its link)
  python3 play/session.py advance     # resolve whatever is ready; prints who must answer next:
                                      # {"phase","waiting","ai","humans"} — ask the "ai" seats' agents,
                                      # humans answer on /play.html; call advance again
  python3 play/session.py endround            # resolve deaths, shrink, next round;
                                              # prints {"reflect":[seats]}: ask each fallen seat once
  python3 play/session.py reflect             # collect reflections (startround/plan also do this)
"""
import argparse
import json
import os
import pickle
import random
import secrets
import sys

from arena.setup import new_game
from arena.models import (Zone, Draw, Attack, PlantBomb, TradeCard, CardType,
                          StealCard, CraftWeapon, CraftShield, PoisonFood,
                          PeekIdentity, FeedFood, EatFood)
from arena import config
from arena.map import legal_moves
from arena.engine import build_observation
from play.briefing import load_table, brief as _brief, zone_guide

# ARENA_SANDBOX=<dir> puts everything a game writes (state, spectator export, seat files) under
# <dir>, so tests / trial games never touch the real live game. Unset = the usual paths.
_SANDBOX = os.environ.get("ARENA_SANDBOX")
STATE = os.environ.get("ARENA_STATE") or (os.path.join(_SANDBOX, "game.pkl") if _SANDBOX else "/tmp/arena_game.pkl")
APP_LIVE = os.path.join(_SANDBOX, "app_live") if _SANDBOX else "app/live"      # spectator page reads this
PLAY_LIVE = os.path.join(_SANDBOX, "play_live") if _SANDBOX else "play/live"   # per-seat prompt/decision files
DECK = "Arena牌堆表.xlsx"

ZONE_BY_NAME = {"forest": Zone.N, "林": Zone.N, "water": Zone.E, "水": Zone.E,
                "stone": Zone.S, "石": Zone.S, "city": Zone.W, "城": Zone.W,
                "center": Zone.CENTER, "中": Zone.CENTER,
                "n": Zone.N, "e": Zone.E, "s": Zone.S, "w": Zone.W, "c": Zone.CENTER}
NAME_BY_ZONE = {Zone.N: "forest", Zone.E: "water", Zone.S: "stone", Zone.W: "city", Zone.CENTER: "center"}


def _save(eng):
    tmp = STATE + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(eng, f)
    os.replace(tmp, STATE)             # atomic: the web server may be reading it right now
    _export(eng)                       # keep the spectator page (app/live/game.json) live


def _load():
    with open(STATE, "rb") as f:
        return pickle.load(f)


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


def cmd_init(args):
    rng = random.Random(args.seed)
    eng = new_game(args.players, rng, lambda: None, data_path=DECK)   # assigns identities
    table = load_table()
    names = list(table["打法倾向"])
    n = len(eng.state.players)
    styles = rng.sample(names, n) if len(names) >= n else [rng.choice(names) for _ in range(n)]
    eng.styles = {p.seat: st for p, st in zip(eng.state.players, styles)}
    guide = zone_guide(eng.state.decks)                      # counted from the fresh decks
    eng.briefs = {p.seat: _brief(eng, p.seat, guide, eng.styles[p.seat], table) for p in eng.state.players}
    eng.card_names = {c.id: c.name for cards in eng.state.decks.values() for c in cards}
    eng.humans = _pick_humans(n, getattr(args, "human_seats", None), getattr(args, "humans", 0) or 0, rng)
    eng.phase = "start"
    eng.game_over = False
    import shutil
    for d in (PROMPT_DIR, DECISION_DIR, HUMAN_DIR):
        shutil.rmtree(d, ignore_errors=True)
    if os.path.exists(f"{APP_LIVE}/think.json"):
        os.remove(f"{APP_LIVE}/think.json")
    _save(eng)
    print(f"initialized {args.players}-player game (seed {args.seed}); identities dealt secretly.")
    port = os.environ.get("ARENA_PORT", "8000")
    for s, k in sorted(eng.humans.items()):
        print(f"人类座位 s{s}: http://localhost:{port}/play.html?seat={s}&key={k}")


def _zone(name):
    return ZONE_BY_NAME[name.strip().lower()]


def _neighbors(eng, seat):
    n = len(eng.state.players)
    return {"left": (seat - 1) % n, "right": (seat + 1) % n}


def cmd_snapshot(args):
    eng = _load()
    st = eng.state
    out = {"round": st.round_no, "open_zones": [NAME_BY_ZONE[z] for z in st.open_zones],
           "bombs": [{"zone": NAME_BY_ZONE[b.zone], "detonate_round": b.detonate_round} for b in st.bombs],
           "players": []}
    for p in st.players:
        out["players"].append({
            "seat": p.seat, "name": p.character.name, "hp": p.hp, "alive": p.alive,
            "zone": NAME_BY_ZONE[p.zone], "attack": p.character.base_attack,
            "equipped": p.equipped_weapon.name if p.equipped_weapon else None,
            "hand": [c.name for c in p.hand],
            "hand_ids": [c.id for c in p.hand],
            "identity": p.identity, "neighbors": _neighbors(eng, p.seat),
            "skill": p.character.__dict__.get("_skill_text", ""),
        })
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_move(args):
    eng = _load()
    st = eng.state
    choices = json.loads(args.mapping)
    for seat_s, zname in choices.items():
        p = eng._p(int(seat_s))
        if not p.alive:
            continue
        target = _zone(zname)
        allowed = set(st.open_zones) if st.round_no == 1 else set(legal_moves(p.zone, st.open_zones))
        if target not in allowed:
            target = p.zone if p.zone in st.open_zones else (allowed[0] if allowed else p.zone)
            print(f"! seat {p.seat} illegal move to {zname}; using {NAME_BY_ZONE[target]}")
        p.zone = target
        from arena.events import Event as _Ev
        eng.log.record(_Ev("move", st.round_no, p.seat, "public", {"to": target.value}))
    _save(eng)
    print("moved. positions: " + ", ".join(f"{p.character.name}={NAME_BY_ZONE[p.zone]}"
                                            for p in eng.alive_players()))


def cmd_event(args):
    eng = _load()
    fired = eng.maybe_random_event()
    _save(eng)
    if fired is None:
        from arena import config as _cfg
        print(f"no event this round (round {eng.state.round_no}; events fire on {_cfg.EVENT_ROUNDS}; deck left {len(eng.state.events)})")
        return
    ev, zone = fired
    print(f"⚡ 随机事件 {ev.id} 「{ev.name}」→ {NAME_BY_ZONE[zone]} 区。效果: {ev.effect}")
    if eng.state.frozen_zones:
        print(f"  沙尘暴锁定区域(本轮不能移动): {[NAME_BY_ZONE[z] for z in eng.state.frozen_zones]}")
    if eng.state.feast_next:
        print("  盛宴预告:下回合待在中心区的人多抽 2 张牌(中心没牌了就改为回 3 血)。")
    print("  当前血量: " + ", ".join(f"{p.character.name}={p.hp}" for p in eng.alive_players()))


def cmd_detonate(args):
    eng = _load()
    before = {p.seat: p.hp for p in eng.state.players}
    eng._detonate_bombs()
    hits = [f"{eng._p(s).character.name} {before[s]}->{eng._p(s).hp}"
            for s in before if eng._p(s).hp != before[s]]
    _save(eng)
    print("detonated. " + ("; ".join(hits) if hits else "no one hit"))


def cmd_act(args):
    eng = _load()
    p = eng._p(args.seat)
    verb = args.rest[0] if args.rest else "draw"
    if verb == "draw":
        eng._apply(p, Draw())
    elif verb == "attack":
        eng._apply(p, Attack(int(args.rest[1])))
    elif verb == "bomb":
        eng._apply_additional(p, PlantBomb(_zone(args.rest[1])))
    elif verb == "trade":
        eng._apply_additional(p, TradeCard(int(args.rest[1]), args.rest[2]))
    else:
        print(f"! unknown action {verb}")
        return
    _save(eng)
    print(f"{p.character.name}: {' '.join(args.rest)} -> hp {p.hp}, "
          f"equipped {p.equipped_weapon.name if p.equipped_weapon else '-'}, hand {[c.name for c in p.hand]}")


def cmd_endround(args):
    eng = _load()
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
    msg = f"round -> {eng.state.round_no}. "
    msg += f"eliminated: {dead}. " if dead else "no eliminations. "
    msg += f"alive: {[p.character.name for p in eng.alive_players()]}."
    if w is not None:
        end = {-1: "draw", eng.LOVERS_WIN: "only the Lovers are left"}.get(w) or eng._p(w).character.name + " survives"
        msg += f"  *** GAME OVER: {end} ***"
    print(msg)
    if ask:
        print(json.dumps({"reflect": ask}))


def cmd_say(args):
    eng = _load()
    to = None if args.to.lower() in ("public", "all", "-") else int(args.to)
    eng.post_message(args.seat, to, " ".join(args.text))
    _save(eng)
    tag = "public" if to is None else f"->seat{to}"
    print(f"seat{args.seat} says [{tag}]: {' '.join(args.text)}")


def cmd_inbox(args):
    eng = _load()
    for m in eng.visible_messages(args.seat):
        tag = "public" if m.to is None else ("private->me" if m.to == args.seat else f"private->seat{m.to}")
        print(f"r{m.round_no} seat{m.sender} [{tag}]: {m.text}")


def cmd_declare(args):
    eng = _load()
    guesses = [(int(g.split(":")[0]), g.split(":")[1]) for g in args.guesses]
    eng.declare(args.seat, guesses)
    _save(eng)
    print(f"seat{args.seat} declared: {guesses}")


def cmd_result(args):
    eng = _load()
    idw = eng.identity_winners()
    for p in eng.state.players:
        tracks = idw.get(p.seat, [])
        print(f"  s{p.seat} {p.character.name:8} [{p.identity}] alive={p.alive} -> {tracks or '-'}")



_T = load_table()
SKILL_TXT = {k: v.get("技能", "") for k, v in _T["角色"].items()}
WIN_COND = {k: v.get("胜利条件", "") for k, v in _T["身份"].items()}
LIVE = PLAY_LIVE

def cmd_board(args):
    move_view = getattr(args, "phase", None) == "move"

    import os as _os
    eng = _load(); st = eng.state
    _os.makedirs(LIVE, exist_ok=True)
    # public board
    phase_note = " · 移动决策阶段:只能依据【上一回合位置+公开喊话】,本回合去向是同时暗选的" if move_view else ""
    lines = [f"# Arena 实时战况(公开) — 第 {st.round_no} 回合{phase_note}",
             f"开放区域: {', '.join(NAME_BY_ZONE[z] for z in st.open_zones)}", "", "## 场上(公开)"]
    hide_pos = move_view and st.round_no == 1   # round-1 placement is blind & simultaneous
    for p in st.players:
        tag = "存活" if p.alive else "已淘汰"
        eqp = p.equipped_weapon.name if p.equipped_weapon else "无"
        zone = "位置未知(第一轮同时暗选,谁都不知道别人去哪)" if hide_pos else NAME_BY_ZONE[p.zone]
        lines.append(f"- s{p.seat} {p.character.name}: {p.hp}血 | {zone} | 装备:{eqp} | {tag}")
    pool = sorted(set(pp.identity for pp in st.players if pp.identity))
    lines += ["", "## 本局在场身份池(公开,不含归属——谁是谁要靠推理)", "  " + " / ".join(pool)]
    lines += ["", "## 公开喊话"]
    for m in eng.messages:
        if m.to is None:
            lines.append(f"- r{m.round_no} s{m.sender}: {m.text}")
    lines += ["", "## 最近公开事件(攻击/淘汰/炸弹)"]
    for e in eng.log.events[-40:]:
        if e.type == "attack":
            lines.append(f"- r{e.round_no} s{e.actor} 攻击 s{e.payload['target']}: 伤害{e.payload['damage']}")
        elif e.type == "eliminated":
            lines.append(f"- r{e.round_no} ☠ s{e.actor} 被淘汰")
        elif e.type == "bomb":
            lines.append(f"- r{e.round_no} 炸弹在 {e.payload['zone']} 命中 s{e.payload['hit']}")
        elif e.type == "random_event":
            hits = e.payload.get("hits") or []
            who = ("命中 " + ",".join(f"s{s}" for s in hits)) if hits else "无人在该区"
            lines.append(f"- r{e.round_no} ⚡随机事件 {e.payload['id']}「{e.payload['name']}」@{e.payload['zone']} — {who}")
    open(f"{LIVE}/board.md","w",encoding="utf-8").write("\n".join(lines)+"\n")
    # private files
    for p in st.players:
        nb = _neighbors(eng, p.seat)
        pl = [f"# 你是 s{p.seat} {p.character.name}(私密,只有你能看)",
              f"数值: {p.hp}血 / 攻击{p.character.base_attack} | 位置:{NAME_BY_ZONE[p.zone]}",
              f"你的技能: {SKILL_TXT.get(p.character.name,'(无)')}  ← 记得在合适时机用它!",
              f"左邻 s{nb['left']} · 右邻 s{nb['right']}",
              f"手牌: {[c.name for c in p.hand]} | 装备:{p.equipped_weapon.name if p.equipped_weapon else '无'}",
              "", f"## 你的秘密身份: {p.identity}", f"胜利条件: {WIN_COND.get(p.identity,'?')}",
              "", "## 你收到/发出的私聊"]
        for m in eng.messages:
            if m.to == p.seat or (m.sender == p.seat and m.to is not None):
                who = f"s{m.sender}->你" if m.to==p.seat else f"你->s{m.to}"
                pl.append(f"- r{m.round_no} {who}: {m.text}")
        open(f"{LIVE}/seat_{p.seat}.md","w",encoding="utf-8").write("\n".join(pl)+"\n")
    print(f"wrote {LIVE}/board.md and seat_0..{len(st.players)-1}.md")



def cmd_export(args):
    _export(_load())


def _export(eng):
    """Write {APP_LIVE}/game.json for the spectator page (called after every phase)."""
    import os as _os, json as _json
    st=eng.state; n=len(st.players)
    _os.makedirs(APP_LIVE, exist_ok=True)
    roster=[{"seat":p.seat,"name":p.character.name,"hp_max":p.character.hp_max,
             "attack":p.character.base_attack,"identity":p.identity} for p in st.players]
    # reconstruct per-round snapshots from the event log
    pos={p.seat:NAME_BY_ZONE[p.zone] for p in st.players}   # will be overwritten by round-1 moves
    hp={p.seat:p.character.hp_max for p in st.players}
    alive={p.seat:True for p in st.players}
    open_zones={z.value for z in [Zone.CENTER,Zone.N,Zone.E,Zone.S,Zone.W]}
    final_hand={p.seat:[c.name for c in p.hand] for p in st.players}
    final_eq={p.seat:(p.equipped_weapon.name if p.equipped_weapon else None) for p in st.players}
    final_eqa={p.seat:(p.equipped_weapon.value if p.equipped_weapon else 0) for p in st.players}
    by_round={}
    for e in eng.log.events:
        by_round.setdefault(e.round_no,[]).append(e)
    snaps=[]
    for r in sorted(by_round):
        for e in by_round[r]:
            pl=e.payload or {}
            if e.type=="move": pos[e.actor]=pl.get("to")
            elif e.type=="attack" and pl.get("target") is not None: hp[pl["target"]]-=pl.get("damage",0)
            elif e.type in ("heal","poison") and "hp" in pl: hp[e.actor]=pl["hp"]
            elif e.type=="feed": hp[pl["to"]]=pl["hp"]
            elif e.type=="bomb" and "hit" in pl: hp[pl["hit"]]=pl.get("hp",hp.get(pl["hit"],0))
            elif e.type=="eliminated": alive[e.actor]=False
            elif e.type=="zone_closed": open_zones.discard(pl.get("zone"))
        snaps.append({"round":r,"open_zones":sorted(open_zones),
                      "players":[{"seat":s2,"zone":pos[s2],"hp":hp[s2],"alive":alive[s2],
                                  "equipped":final_eq[s2],"eq_atk":final_eqa[s2],"hand":final_hand[s2]} for s2 in range(n)]})
    if not snaps:                              # fresh game: nothing logged yet
        snaps.append({"round":0,"open_zones":sorted(open_zones),
                      "players":[{"seat":s2,"zone":None,"hp":hp[s2],"alive":True,"equipped":final_eq[s2],
                                  "eq_atk":final_eqa[s2],"hand":final_hand[s2]} for s2 in range(n)]})
    events=[{"type":e.type,"round":e.round_no,"actor":e.actor,"visibility":e.visibility,
             "payload":e.payload} for e in eng.log.events]
    thinking={}
    tf=f"{APP_LIVE}/think.json"
    if _os.path.exists(tf):
        try: thinking={int(k):{int(rr):tt for rr,tt in v.items()} for k,v in _json.load(open(tf,encoding="utf-8")).items()}
        except Exception: thinking={}
    w=eng.check_winner()
    over = w is not None                       # winners are only judged at game end
    out={"roster":roster,"snapshots":snaps,"events":events,
         "winners":({str(k):v for k,v in eng.identity_winners().items()} if over else {}),
         "thinking":{str(k):{str(rr):tt for rr,tt in v.items()} for k,v in thinking.items()},
         "outcome":("进行中" if not over else {-1:"draw",eng.LOVERS_WIN:"lovers"}.get(w,"win")),
         "rounds":st.round_no-1,"survivor":(None if not over or w<0 else w),
         "reflections":{str(k):v for k,v in getattr(eng,"reflections",{}).items()}}
    _json.dump(out, open(f"{APP_LIVE}/game.json","w",encoding="utf-8"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Lean agent protocol: one fresh `arena-player` agent per decision, fed a compact
# prompt built here (rules live in .claude/agents/arena-player.md). Only seats with
# a real choice are asked; the rest are auto-resolved.
# ---------------------------------------------------------------------------
TYPE_ZH = {"weapon": "武器", "food": "食物", "armor": "护甲", "ammo": "碎片"}
PROMPT_DIR = f"{PLAY_LIVE}/prompts"      # one private file per seat: s{seat}.txt
DECISION_DIR = f"{PLAY_LIVE}/decisions"  # the seat's agent writes s{seat}.json here
HUMAN_DIR = f"{PLAY_LIVE}/human"        # human seats' reflections (play/human.py, app/human_api.py)

PUBLIC_EV = ("attack", "eliminated", "random_event", "zone_closed", "bomb", "craft", "poison", "feed", "feast_heal")


def _memos(eng):
    if not hasattr(eng, "memos"):
        eng.memos = {}
    return eng.memos


def _atk(p):
    return p.character.base_attack + (p.equipped_weapon.value if p.equipped_weapon else 0)


def _legal_zones(eng, p):
    st = eng.state
    if p.zone in st.frozen_zones:
        return [p.zone]
    if st.round_no == 1:
        return sorted(st.open_zones, key=lambda z: z.value)
    return list(legal_moves(p.zone, st.open_zones))


def _closing_zone(eng):
    """Zone certain to close at the end of this round (shrinking already on: alive <= trigger)."""
    if len(eng.alive_players()) > config.SHRINK_TRIGGER:
        return None
    return next((z for z in eng._SHRINK_ORDER if z in eng.state.open_zones), None)


def _next_legal(eng, p):
    """Where p may go next round, as far as is knowable during this round's action phase."""
    closing = _closing_zone(eng)
    opens = {z for z in eng.state.open_zones if z != closing}
    return list(legal_moves(p.zone, opens)) or list(legal_moves(p.zone, eng.state.open_zones))


def _planned(eng):
    if not hasattr(eng, "planned_moves"):
        eng.planned_moves = {}
    return eng.planned_moves


def _store_planned(eng, decisions, auto):
    """After the action phase: remember each seat's (legal) move for next round."""
    plan = _planned(eng)
    plan.clear()
    eng.rejected_moves = {}
    for p in eng.alive_players():
        want = (decisions.get(p.seat) or auto.get(p.seat) or {}).get("move")
        try:
            z = _zone(want) if want and want != "stay" else p.zone
        except KeyError:
            eng.rejected_moves[p.seat] = want
            continue
        if z in _next_legal(eng, p):
            plan[p.seat] = NAME_BY_ZONE[z]
        else:
            eng.rejected_moves[p.seat] = want


def _extras(eng, p):
    """Additional actions this seat can actually take right now (declare excluded)."""
    sk = eng._skill(p)
    mates = [q for q in eng.alive_players() if q.seat != p.seat and q.zone == p.zone]
    out = []
    if any(c.type == CardType.FOOD for c in p.hand):
        out.append("eat:食物牌ID")
    if mates and (p.hand or p.equipped_weapon):
        out.append("trade:座位:牌ID")
    if sk.can_steal() and any(q.hand for q in mates):
        out.append("steal:座位")
    if sk.can_craft() and len([c for c in p.hand if c.type == CardType.WEAPON and c.value <= 2]) >= 2:
        out.append("craft")
    if sk.can_poison() and len([c for c in p.hand if c.type == CardType.FOOD]) >= 2:
        out.append("poison")
    if sk.can_peek() and p.seat not in getattr(eng, "peek_used", set()) and p.zone == Zone.W and mates:
        out.append("peek:座位(每局一次)")
    if sk.can_feed() and mates and any(c.type == CardType.FOOD for c in p.hand):
        out.append("feed:座位:食物牌ID")
    if sk.can_make_bomb() and len([c for c in p.hand if c.type == CardType.AMMO]) >= sk.bomb_fragments():
        out.append("bomb:区名")
    return out


def _plan(eng, phase):
    """-> (auto: {seat: decision}, ask: [seats])"""
    auto, ask = {}, []
    for p in eng.alive_players():
        if phase == "move":
            legal = _legal_zones(eng, p)
            planned = _planned(eng).get(p.seat)
            if len(legal) == 1:
                auto[p.seat] = {"move": NAME_BY_ZONE[legal[0]]}
            elif planned and _zone(planned) in legal:
                auto[p.seat] = {"move": planned}                    # decided during last action phase
            else:
                ask.append(p.seat)
        else:
            # one call covers this round's action AND next round's move
            atk = build_observation(eng, p.seat).attackable_seats
            extras = _extras(eng, p)
            nxt = _next_legal(eng, p)
            if p.zone == Zone.CENTER and len(atk) == 1 and not extras:
                act = f"attack:{atk[0]}"                            # forced, no choice of target
            elif not atk and not extras:
                act = "draw"                                        # alone, nothing else to do
            else:
                act = None
            if act and len(nxt) == 1:
                auto[p.seat] = {"action": act, "move": NAME_BY_ZONE[nxt[0]]}
            else:
                ask.append(p.seat)
    return auto, ask


def _card_str(c):
    return f"{c.name}[{c.id}]({TYPE_ZH.get(c.type.value, c.type.value)}{c.value})"


def _progress(eng, seat):
    """One line on how this seat's identity goal stands. Built only from what the seat already
    knows (its own identity, public deaths, who dealt each finishing blow) -- never others' identities."""
    st, p = eng.state, eng._p(seat)
    n = len(st.players)
    name = lambda s: f"s{s} {eng._p(s).character.name}"
    mine = [v for v, k in eng.killer_of.items() if k == seat]
    parts = [f"你亲手击杀: {', '.join(name(v) for v in mine) or '无'}"]
    ident = p.identity
    if ident == "Vendetta":
        t = (seat + 1) % n
        if eng._p(t).alive:
            parts.append(f"复仇目标 {name(t)} 还活着({eng._p(t).hp} 血),要你亲手补最后一刀")
        elif eng.killer_of.get(t) == seat:
            parts.append(f"✅ 你已亲手杀死复仇目标 {name(t)},Vendetta 胜利已到手(终局结算),接下来尽量活下去")
        else:
            k = eng.killer_of.get(t)
            parts.append(f"❌ 复仇目标 {name(t)} 已被{name(k) if k is not None else '事件/炸弹'}杀死,"
                         "Vendetta 胜利已不可能,改为争取活到最后")
    elif ident == "Lovers":
        mate = next((q for q in st.players if q.identity == "Lovers" and q.seat != seat), None)
        if mate is not None:
            parts.append(f"恋人 {name(mate.seat)} 还活着({mate.hp} 血),两人都活到最后才算恋人胜利" if mate.alive
                         else f"❌ 恋人 {name(mate.seat)} 已死,恋人胜利已不可能,改为争取做最后的存活者")
    elif ident == "Warrior":
        others = max((k for s2, k in eng.kills.items() if s2 != seat), default=0)
        me = eng.kills.get(seat, 0)
        state = "暂时唯一最多 ✅" if me > others else ("和别人并列,并列不算赢" if me == others and me else "落后")
        parts.append(f"击杀数: 你 {me},其他人最多 {others} —— {state}")
    elif ident == "Pacifist":
        parts.append("你还没主动攻击过 ✅" if seat not in eng.ever_attacked else "❌ 你已主动攻击过,Pacifist 胜利已不可能")
    elif ident == "Myrtle":
        if eng.deaths_by_round:
            parts.append("❌ 已经有人比你先死,Myrtle 胜利已不可能,改为争取活到最后")
    elif ident == "Negotiator":
        need = n - 2
        parts.append(f"已和 {len(eng.trade_partners.get(seat, ()))}/{need} 名不同玩家交换过")
    elif ident == "Judas":
        best = max((c for pair, c in eng.pair_trades.items() if seat in pair), default=0)
        parts.append(f"和同一个人最多交换过 {best}/3 次")
    elif ident == "Social Butterfly":
        parts.append("已声明,终局按声明结算(可以更新)" if seat in eng.declarations
                     else "还没声明身份——用 declare 写下你的猜测,被淘汰前记得声明")
    return "【身份进度】" + ";".join(parts)


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


def _prompt(eng, seat, phase):
    st, p = eng.state, eng._p(seat)
    r = st.round_no
    head = "移动阶段" if phase == "move" else "行动阶段(位置已公开)"
    briefs = getattr(eng, "briefs", None) or {}
    L = [briefs.get(seat) or _brief(eng, seat, zone_guide(st.decks), getattr(eng, "styles", {}).get(seat)), "",
         f"=== 第 {r} 回合 · {head} ==="]
    eq = f"{p.equipped_weapon.name}(+{p.equipped_weapon.value})" if p.equipped_weapon else "无"
    L.append(f"【你】{p.hp}/{p.character.hp_max}血 · 攻击 {p.character.base_attack}+武器={_atk(p)} · 装备 {eq}")
    L.append(f"手牌: {', '.join(_card_str(c) for c in p.hand) or '无'}")
    if seat in eng.declarations:
        L.append(f"你已声明: {eng.declarations[seat]}")
    L.append(_progress(eng, seat))
    known = getattr(eng, "known_identities", {}).get(seat)
    if known:
        L.append("【你已秘密确认的身份】" + ", ".join(f"s{k} {eng._p(k).character.name}={v}" for k, v in known.items()))
    for b in st.bombs:
        if b.planter_seat == seat:
            L.append(f"💣 你埋的炸弹: {NAME_BY_ZONE[b.zone]},第 {b.detonate_round} 回合移动后引爆"
                     f"(该区所有人 -6,包括你自己)——那回合别待在 {NAME_BY_ZONE[b.zone]}!")
    blind = phase == "move" and r == 1
    L.append("【场上】" + ("(第 1 回合,位置未知)" if blind else "位置为" + ("上回合结束时" if phase == "move" else "本回合")))
    for q in st.players:
        if not q.alive:
            L.append(f"  s{q.seat} {q.character.name}: 已淘汰")
            continue
        zq = "?" if blind else NAME_BY_ZONE[q.zone]
        eqq = f"{q.equipped_weapon.name}+{q.equipped_weapon.value}" if q.equipped_weapon else "无"
        L.append(f"  s{q.seat} {q.character.name}: {q.hp}/{q.character.hp_max}血 · {zq} · 武器 {eqq}")
    L.append(f"开放区: {', '.join(sorted(NAME_BY_ZONE[z] for z in st.open_zones))}"
             + (f" · 沙尘暴锁定: {[NAME_BY_ZONE[z] for z in st.frozen_zones]}" if st.frozen_zones else "")
             + (" · 盛宴生效中(中心区多抽2张;中心没牌了就改为回 3 血)" if st.feast_active else "")
             + (" · 盛宴预告:下回合中心区多抽2张(中心没牌了就改为回 3 血)" if st.feast_next else ""))
    left = {z: len(st.decks.get(z, [])) for z in sorted(st.open_zones, key=lambda z: z.value)}
    L.append("各区剩余张数: " + ", ".join(f"{NAME_BY_ZONE[z]} {n}" + ("(空!抽不到牌)" if n == 0 else "")
                                        for z, n in left.items()))
    if phase == "move":
        if not blind:
            cnt = {}
            for q in eng.alive_players():
                cnt[NAME_BY_ZONE[q.zone]] = cnt.get(NAME_BY_ZONE[q.zone], 0) + 1
            L.append("上回合各区人数: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())))
    recent = [e for e in eng.log.events if e.type in PUBLIC_EV and e.round_no >= r - 1]
    if recent:
        L.append("【近期公开事件】")
        for e in recent[-15:]:
            L.append("  " + _event_line(e))
    msgs = [m for m in eng.visible_messages(seat) if m.round_no >= r - 1]
    if msgs:
        L.append("【近期消息】")
        for m in msgs[-10:]:
            tag = "公开" if m.to is None else ("私聊给你" if m.to == seat else f"你私聊s{m.to}")
            L.append(f"  r{m.round_no} s{m.sender}[{tag}]: {m.text}")
    L.append(f"【你上回合的备忘】{_memos(eng).get(seat, '(无)')}")
    if phase == "move":
        planned = _planned(eng).get(seat)
        bad = getattr(eng, "rejected_moves", {}).get(seat)
        if planned:
            why = "该区已关闭" if _zone(planned) not in st.open_zones else "现在去不了"
            L.append(f"⚠ 你上回合计划去 {planned},但{why},请重新选择。")
        elif bad:
            L.append(f"⚠ 你上回合写的下回合去向 {bad} 不合法(不相邻/已关闭/不存在),请重新选择。")
        L.append(f"可去: {', '.join(NAME_BY_ZONE[z] for z in _legal_zones(eng, p))}")
        L.append('决策格式: {"say":[...],"move":"区名","memo":"..."}')
    else:
        atk = build_observation(eng, seat).attackable_seats
        mates = [q for q in eng.alive_players() if q.seat != seat and q.zone == p.zone]
        L.append(f"本区同伴: {', '.join(f's{q.seat}' for q in mates) or '无'} · 可攻击: {atk or '无'}")
        if p.zone == Zone.CENTER and atk:
            L.append("你在中心区:必须攻击(自己选目标),攻击后自动抽 1 张中心牌。")
        ex = _extras(eng, p)
        L.append(f"可用附加行动: {', '.join(ex) if ex else '无'}"
                 + (" · 也可 declare:座位=身份,..." if p.identity == "Social Butterfly" else ""))
        nxt = ", ".join(NAME_BY_ZONE[z] for z in _next_legal(eng, p))
        closing = _closing_zone(eng)
        L.append(f"【同时决定下回合去哪】下回合可去: {nxt}"
                 + (f"(本回合末 {NAME_BY_ZONE[closing]} 会关闭)" if closing else "")
                 + "。别人也在同时暗选,你只能按现在的局面判断。")
        L.append('决策格式: {"action":"draw或attack:座位","extra":[...],"move":"下回合的区名","say":[...],"memo":"..."}')
    humans = getattr(eng, "humans", {})
    if humans and seat not in humans:
        L.append(f"【谁是人类?】本局有 {len(humans)} 名人类玩家混在你们中间(不是你)。在决策 JSON 里加 "
                 '"human_guess": 座位号,写下你现在最怀疑谁是人类(每次都可以改);也可以在喊话里试探。'
                 "游戏结束时会公布谁猜对了。")
    L.append(f"把决策 JSON 用 Write 写到 {DECISION_DIR}/s{seat}.json(只写这一个文件)。")
    return "\n".join(L)


def _record_thinking(eng, seat, phase, memo, round_no=None):
    import json as _json
    tf = f"{APP_LIVE}/think.json"
    try:
        t = _json.load(open(tf, encoding="utf-8"))
    except Exception:
        t = {}
    r = str(round_no or eng.state.round_no)
    cur = t.setdefault(str(seat), {}).get(r, "")
    tag = {"move": "移动", "act": "行动", "reflect": "出局感悟"}.get(phase, phase)
    t[str(seat)][r] = (cur + " | " if cur else "") + f"[{tag}] {memo}"
    os.makedirs(APP_LIVE, exist_ok=True)
    _json.dump(t, open(tf, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def _record_human_guess(eng, seat, g):
    if g is None or g == "":
        return
    try:
        target = _seat(g)
    except (ValueError, TypeError):
        return
    if not hasattr(eng, "human_guesses"):
        eng.human_guesses = {}
    eng.human_guesses.setdefault(seat, []).append((eng.state.round_no, target))


def _apply_talk(eng, seat, d, phase):
    _record_human_guess(eng, seat, d.get("human_guess"))
    for m in (d.get("say") or [])[:config.MESSAGES_PER_ROUND]:
        if isinstance(m, str):                 # bare string = public message
            m = {"to": "all", "text": m}
        elif isinstance(m, (list, tuple)):     # ["to", "text"]
            m = {"to": m[0], "text": m[1]} if len(m) >= 2 else {"to": "all", "text": str(m[0]) if m else ""}
        to = m.get("to")
        to = None if to in (None, "all", "public", "公开") else int(str(to).lstrip("sS"))
        text = m.get("text") or m.get("msg") or m.get("message") or m.get("content")
        if text:
            eng.post_message(seat, to, str(text))
    if d.get("memo"):
        _memos(eng)[seat] = str(d["memo"])[:400]
        _record_thinking(eng, seat, phase, str(d["memo"]))


def _apply_declare(eng, seat, spec):
    pairs = [x.split("=") for x in spec.split(",") if "=" in x]
    eng.declare(seat, [(int(a.strip().lstrip("s")), b.strip()) for a, b in pairs])


def _ask_reflections(eng, seats):
    """A seat that just fell gets one last prompt: look back on its game. After that it is never
    called again (dead seats are never asked to move or act)."""
    if not seats:
        return
    import shutil
    for d in (PROMPT_DIR, DECISION_DIR):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    r = eng.state.round_no
    for seat in seats:
        p = eng._p(seat)
        hits = [e for e in eng.log.events if e.type == "attack" and (e.payload or {}).get("target") == seat]
        last = hits[-1] if hits else None
        how = (f"第 {last.round_no} 回合被 s{last.actor} {eng._p(last.actor).character.name} 打倒" if last
               else "没有被人直接攻击(事件/炸弹/毒)")
        alive = ", ".join(f"s{q.seat} {q.character.name}({q.hp}血)" for q in eng.alive_players())
        L = [f"你是 s{seat} {p.character.name},秘密身份 {p.identity}。你在第 {r} 回合出局了:{how}。",
             f"胜利条件: {WIN_COND.get(p.identity, '?')}",
             f"还活着的人: {alive or '无'}",
             f"你最后的备忘: {_memos(eng).get(seat, '(无)')}",
             "",
             "游戏对你来说结束了,这是最后一次叫你。写一段出局感悟(150~250 字):你原本的计划、"
             "哪一步走错了或者被谁坑了、如果重来你会怎么打;再从玩家角度说说对游戏节奏的看法"
             "(太快/太慢、哪几个回合最无聊或最紧张、牌够不够、有没有想改的规则)。不用再做任何行动。",
             '决策格式: {"reflection":"..."}',
             f"把 JSON 用 Write 写到 {DECISION_DIR}/s{seat}.json(只写这一个文件)。"]
        with open(f"{PROMPT_DIR}/s{seat}.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(L))
    eng.pending_reflect = {seat: r for seat in seats}


def _absorb_reflections(eng):
    """Collect the fallen seats' reflections (called before the prompt dirs are reused)."""
    pending = getattr(eng, "pending_reflect", {}) or {}
    if not pending:
        return
    got = _load_decisions(argparse.Namespace(decisions=None))
    if not hasattr(eng, "reflections"):
        eng.reflections = {}
    for seat, r in pending.items():
        d = got.get(seat)
        text = d and (d.get("reflection") or d.get("memo"))
        if text:
            eng.reflections[seat] = str(text)
            _record_thinking(eng, seat, "reflect", str(text), round_no=r)
        else:
            print(f"! s{seat} 没交出局感悟,跳过")
    eng.pending_reflect = {}


def cmd_reflect(args):
    eng = _load()
    _absorb_reflections(eng)
    _absorb_human_reflections(eng)
    _save(eng)
    for seat, text in getattr(eng, "reflections", {}).items():
        print(f"s{seat} {eng._p(seat).character.name}: {text}")


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


RULES_FILE = ".claude/agents/arena-player.md"


def _rules_text():
    """The arena-player agent's system prompt (frontmatter stripped) — for agent types
    that can't load it themselves (e.g. a general-purpose fallback)."""
    txt = open(RULES_FILE, encoding="utf-8").read()
    if txt.startswith("---"):
        txt = txt.split("---", 2)[2]
    return txt.strip()


def cmd_prompt(args):
    eng = _load()
    body = _prompt(eng, args.seat, args.phase)
    if args.rules:
        body = _rules_text() + "\n\n=== 本次决策 ===\n" + body
    print(body)


def cmd_startround(args):
    """Round start: activate a telegraphed Feast, clear sandstorm, maybe fire a random event."""
    eng = _load()
    _absorb_reflections(eng)
    st = eng.state
    st.feast_active, st.feast_next = st.feast_next, False
    st.frozen_zones = set()
    _save(eng)
    cmd_event(args)


def _load_decisions(args):
    """Decisions come from the CLI JSON arg, or (default) from DECISION_DIR/s{seat}.json."""
    if args.decisions:
        return {int(k): v for k, v in json.loads(args.decisions).items()}
    out = {}
    if os.path.isdir(DECISION_DIR):
        for fn in sorted(os.listdir(DECISION_DIR)):
            if fn.startswith("s") and fn.endswith(".json"):
                try:
                    txt = open(os.path.join(DECISION_DIR, fn), encoding="utf-8").read().strip()
                    txt = txt[txt.find("{"): txt.rfind("}") + 1]      # tolerate ```json fences
                    out[int(fn[1:-5])] = json.loads(txt)
                except Exception as ex:
                    head = '"reflection":"'
                    if head in txt:                       # a reflection with stray quotes inside
                        body = txt[txt.index(head) + len(head): txt.rfind('"')]
                        out[int(fn[1:-5])] = {"reflection": body.replace("\\n", "\n")}
                    else:
                        print(f"! {fn} 无法解析 ({ex}),按默认处理")
    return out


def cmd_movephase(args):
    eng = _load()
    st = eng.state
    decisions = _load_decisions(args)
    _, ask = _plan(eng, "move")
    if missing := [s for s in ask if s not in decisions]:
        sys.exit(f"! 缺少决策 {missing}:{DECISION_DIR}/sN.json 不存在,未执行本阶段")
    auto, _ = _plan(eng, "move")
    for seat, d in decisions.items():
        _apply_talk(eng, seat, d, "move")
        if d.get("declare"):
            _apply_declare(eng, seat, d["declare"])
    for p in eng.alive_players():
        d = decisions.get(p.seat) or auto.get(p.seat) or {}
        legal = _legal_zones(eng, p)
        want = d.get("move")
        try:
            dest = _zone(want) if want and want != "stay" else p.zone
        except KeyError:
            dest = p.zone
        if dest not in legal:
            dest = p.zone if p.zone in legal else legal[0]
            if want:
                print(f"! s{p.seat} 非法移动 {want},改为 {NAME_BY_ZONE[dest]}")
        p.zone = dest
        from arena.events import Event as _Ev
        eng.log.record(_Ev("move", st.round_no, p.seat, "public", {"to": dest.value}))
    _planned(eng).clear()
    eng.rejected_moves = {}
    before = {p.seat: p.hp for p in st.players}
    eng._detonate_bombs()
    _save(eng)
    print("位置: " + ", ".join(f"s{p.seat}{p.character.name}={NAME_BY_ZONE[p.zone]}" for p in eng.alive_players()))
    hits = [f"s{s} {before[s]}→{eng._p(s).hp}" for s in before if eng._p(s).hp != before[s]]
    if hits:
        print("💥 炸弹: " + "; ".join(hits))


def _seat(x):
    """'3', 's3', ' S3 ' -> 3 (agents write seats both ways)."""
    return int(str(x).strip().lstrip("sS"))


def _parse_extra(eng, seat, x):
    x = str(x).strip()
    k, _, rest = x.partition(":")
    if k == "steal":
        return StealCard(_seat(rest))
    if k == "trade":
        to, _, cid = rest.partition(":")
        return TradeCard(_seat(to), cid)
    if k == "craft":
        return CraftWeapon()
    if k == "shield":                     # shields are gone (no armor in the game); craft a weapon
        return CraftWeapon()
    if k == "poison":
        return PoisonFood()
    if k == "peek":
        return PeekIdentity(_seat(rest.split("(")[0]))
    if k == "feed":
        to, _, cid = rest.partition(":")
        return FeedFood(_seat(to), cid or None)
    if k == "bomb":
        return PlantBomb(_zone(rest))
    if k == "eat":
        cid = rest.strip()
        hand = eng._p(seat).hand
        if not any(c.id == cid for c in hand):          # agents sometimes write the card's name
            cid = next((c.id for c in hand if c.name == cid and c.type == CardType.FOOD), cid)
        return EatFood(cid)
    return None


def cmd_actphase(args):
    eng = _load()
    st = eng.state
    decisions = _load_decisions(args)
    _, ask = _plan(eng, "act")
    if missing := [s for s in ask if s not in decisions]:
        sys.exit(f"! 缺少决策 {missing}:{DECISION_DIR}/sN.json 不存在,未执行本阶段")
    auto, _ = _plan(eng, "act")
    start = len(eng.log.events)
    order = sorted(eng.alive_players(), key=lambda q: (q.seat - st.first_seat) % 100)
    for p in order:
        if not p.alive:
            continue
        d = decisions.get(p.seat) or auto.get(p.seat) or {"action": "draw"}
        if p.seat in decisions:
            _apply_talk(eng, p.seat, d, "act")
        extras = [str(x) for x in (d.get("extra") or [])]
        for x in [x for x in extras if x.startswith("eat:")]:     # eating comes before the main action
            eng._apply_additional(p, _parse_extra(eng, p.seat, x))
        eng._maybe_heal(p)
        atk = build_observation(eng, p.seat).attackable_seats
        act = str(d.get("action", "draw"))
        tgt = _seat(act.split(":")[1]) if act.startswith("attack:") else None
        if p.zone == Zone.CENTER and atk:                  # forced fight + center draw
            eng._apply(p, Attack(tgt if tgt in atk else eng._lowest_hp(atk)))
            eng.center_draw(p)
        elif tgt in atk:
            eng._apply(p, Attack(tgt))
        else:
            eng._apply(p, Draw())
        for x in [x for x in extras if not x.startswith("eat:")]:
            if str(x).startswith("declare:"):
                _apply_declare(eng, p.seat, str(x)[len("declare:"):])
                continue
            try:
                a = _parse_extra(eng, p.seat, x)
            except (ValueError, KeyError):
                print(f"! s{p.seat} 附加行动写法看不懂,跳过: {x}")
                a = None
            if a is not None:
                eng._apply_additional(p, a)
    _store_planned(eng, decisions, auto)
    _save(eng)
    for e in eng.log.events[start:]:
        pl = e.payload or {}
        if e.type == "attack":
            print(f"  s{e.actor}→s{pl['target']} 掷{pl['roll']} 伤{pl['damage']}{' 倒地' if pl['downed'] else ''}")
        elif e.type in ("draw", "heal", "steal", "trade", "craft", "poison_planted", "plant_bomb", "poison", "peek", "feed", "feast_heal"):
            print(f"  s{e.actor} {e.type} {pl}")
    print("血量: " + ", ".join(f"s{p.seat}={p.hp}" for p in eng.alive_players()))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--players", type=int, default=5); pi.add_argument("--seed", type=int, default=0)
    pi.add_argument("--human-seats", dest="human_seats", default=None, help="e.g. 2,4")
    pi.add_argument("--humans", type=int, default=0, help="number of random human seats")
    sub.add_parser("snapshot")
    pm = sub.add_parser("move"); pm.add_argument("mapping")
    sub.add_parser("detonate")
    sub.add_parser("event")
    sub.add_parser("startround")
    pp = sub.add_parser("plan"); pp.add_argument("phase", choices=["move", "act"])
    ppr = sub.add_parser("prompt"); ppr.add_argument("seat", type=int); ppr.add_argument("phase", choices=["move", "act"])
    ppr.add_argument("--rules", action="store_true", help="prepend the arena-player rules (fallback agent types)")
    pmv = sub.add_parser("movephase"); pmv.add_argument("decisions", nargs="?")
    pac = sub.add_parser("actphase"); pac.add_argument("decisions", nargs="?")
    pa = sub.add_parser("act"); pa.add_argument("seat", type=int); pa.add_argument("rest", nargs="*")
    sub.add_parser("endround")
    ps = sub.add_parser("say"); ps.add_argument("seat", type=int); ps.add_argument("to"); ps.add_argument("text", nargs="+")
    pin = sub.add_parser("inbox"); pin.add_argument("seat", type=int)
    pd = sub.add_parser("declare"); pd.add_argument("seat", type=int); pd.add_argument("guesses", nargs="+")
    sub.add_parser("result")
    sub.add_parser("reflect")
    sub.add_parser("advance")
    pb = sub.add_parser("board"); pb.add_argument("phase", nargs="?", default=None)
    sub.add_parser("export")
    args = ap.parse_args()
    {"init": cmd_init, "snapshot": cmd_snapshot, "move": cmd_move,
     "detonate": cmd_detonate, "event": cmd_event, "act": cmd_act, "endround": cmd_endround,
     "startround": cmd_startround, "plan": cmd_plan, "prompt": cmd_prompt,
     "movephase": cmd_movephase, "actphase": cmd_actphase,
     "say": cmd_say, "inbox": cmd_inbox, "declare": cmd_declare, "result": cmd_result, "reflect": cmd_reflect, "advance": cmd_advance, "board": cmd_board, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
