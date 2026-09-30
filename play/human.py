"""What one human seat may see, and checking what it submits.

Pure functions over an engine: nothing here writes files. The rules for what is legal come from
play/session.py (the same helpers that build the agents' prompts), so a human and an agent in
the same seat are offered exactly the same choices.
"""
import json
import os

from arena.engine import build_observation
from arena.models import Zone, CardType
from arena import identities
from play import session as S
from play.briefing import fill_for

MAX_SAY = 2
MAX_TEXT = 200
MAX_MEMO = 400


_DESC = None


def _descriptions():
    """Character flavor text from the 人物 sheet (loaded once)."""
    global _DESC
    if _DESC is None:
        _DESC = {}
        try:
            from arena.deck_loader import _open, _iter_rows
            for row in _iter_rows(_open(S.DECK)["人物"], "角色名"):
                _DESC[str(row["角色名"]).strip()] = str(row.get("描述") or "").strip()
        except Exception:
            pass
    return _DESC


def _names(zones):
    return [S.NAME_BY_ZONE[z] for z in sorted(zones, key=lambda z: z.value)]


def _card(c):
    return {"id": c.id, "name": c.name, "type": c.type.value, "value": c.value, "label": S._card_str(c)}


def _asked(eng, seat, phase):
    return phase in ("move", "act") and seat in S._plan(eng, phase)[1]


def _has_decision(seat):
    return os.path.exists(f"{S.DECISION_DIR}/s{seat}.json")


def _read_decision(seat):
    try:
        return json.load(open(f"{S.DECISION_DIR}/s{seat}.json", encoding="utf-8"))
    except Exception:
        return None


def _reflection_text(eng, seat):
    text = getattr(eng, "reflections", {}).get(seat)
    if text:
        return text
    fp = f"{S.HUMAN_DIR}/reflections/s{seat}.json"
    if os.path.exists(fp):
        try:
            return json.load(open(fp, encoding="utf-8")).get("reflection")
        except Exception:
            return None
    return None


def _card_name(eng, cid):
    names = getattr(eng, "card_names", {})
    if cid in names:
        return names[cid]
    for q in eng.state.players:
        for c in q.hand + ([q.equipped_weapon] if q.equipped_weapon else []):
            if c.id == cid:
                return c.name
    for cards in eng.state.decks.values():
        for c in cards:
            if c.id == cid:
                return c.name
    return cid


def _my_actions(eng, seat):
    """What happened to this seat's own cards and HP, oldest first (only its own events)."""
    p = eng._p(seat)
    eq = p.equipped_weapon.id if p.equipped_weapon else None
    held = {c.id for c in p.hand}
    out = []
    for e in eng.log.events:
        pl, r = e.payload or {}, f"r{e.round_no}"
        if e.actor == seat:
            if e.type == "draw":
                cid = pl.get("got")
                if cid is None:
                    out.append(f"{r} 抽牌落空,没抽到牌(那个区的牌堆已经空了)")
                else:
                    where = " · 已自动装备" if cid == eq else (" · 在手牌里" if cid in held else "")
                    out.append(f"{r} 抽到 {_card_name(eng, cid)}{where}")
            elif e.type == "heal":
                out.append(f"{r} 吃了 {_card_name(eng, pl.get('food'))} → {pl.get('hp')} 血")
            elif e.type == "feast_heal":
                out.append(f"{r} 盛宴回血 → {pl.get('hp')} 血")
            elif e.type == "poison":
                out.append(f"{r} 抽到毒食物! → {pl.get('hp')} 血")
            elif e.type == "steal":
                out.append(f"{r} 从 s{pl.get('from')} 偷到 {_card_name(eng, pl.get('card'))}")
            elif e.type == "trade":
                out.append(f"{r} 把 {_card_name(eng, pl.get('card'))} 给了 s{pl.get('to')}")
            elif e.type == "craft":
                out.append(f"{r} 合成了一把武器")
            elif e.type == "plant_bomb":
                out.append(f"{r} 埋下炸弹 → {S.NAME_BY_ZONE.get(S.ZONE_BY_NAME.get(str(pl.get('zone'))), pl.get('zone'))}")
            elif e.type == "peek":
                out.append(f"{r} 偷看到 s{pl.get('target')} 是 {pl.get('identity')}")
            elif e.type == "feed":
                out.append(f"{r} 喂 s{pl.get('to')} 吃了 {_card_name(eng, pl.get('food'))}")
            elif e.type == "discard":
                why = {"hand_limit": "手牌超过上限,自动丢掉最早的", "dogs": "饿狗事件:交出食物",
                       "flood": "洪水事件:手里的武器被冲回这个区的牌堆",
                       "monkeys": "猴群事件:已装备的武器被抢走,扔回这个区的牌堆",
                       "replaced": "换上更好的武器,旧武器丢掉",
                       "unlogged": "之前没记录到:换装备时丢掉的旧武器,或手牌超上限被丢"}.get(pl.get("why"), "丢弃")
                cards = "、".join(_card_name(eng, c) for c in pl.get("cards", []))
                out.append(f"{r} {why} → {cards}")
        elif e.type == "trade" and pl.get("to") == seat:
            out.append(f"{r} s{e.actor} 给了你 {_card_name(eng, pl.get('card'))}")
        elif e.type == "steal" and pl.get("from") == seat:
            out.append(f"{r} s{e.actor} 偷走了你的 {_card_name(eng, pl.get('card'))}")
        elif e.type == "feed" and pl.get("to") == seat:
            out.append(f"{r} s{e.actor} 喂你吃了东西 → {pl.get('hp')} 血")
    return out[-20:]


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
        elif kind == "eat":
            o["cards"] = [_card(c) for c in p.hand if c.type == CardType.FOOD]
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
            "identities": sorted({q.identity for q in eng.state.players if q.identity})
                          + ([identities.TARGET_LABEL] if p.identity == "Bodyguard" else [])}


def human_view(eng, seat):
    st, p = eng.state, eng._p(seat)
    ph = getattr(eng, "phase", "start")
    status = _status(eng, seat)
    blind = st.round_no == 1 and ph in ("start", "move")   # nobody has picked a zone yet
    players = []
    for q in st.players:
        eq = q.equipped_weapon
        players.append({"seat": q.seat, "name": q.character.name, "hp": q.hp, "hp_max": q.character.hp_max,
                        "alive": q.alive,
                        "zone": None if blind else S.NAME_BY_ZONE[q.zone],
                        "weapon": eq.name if eq else None, "weapon_value": eq.value if eq else 0})
    lover = None
    if p.identity == "Lovers":
        lover = next((q.seat for q in st.players if q.identity == "Lovers" and q.seat != seat), None)
    known = getattr(eng, "known_identities", {}).get(seat) or {}
    me = {"name": p.character.name, "desc": _descriptions().get(p.character.name, ""),
          "hp": p.hp, "hp_max": p.character.hp_max,
          "base_attack": p.character.base_attack, "attack": S._atk(p),
          "attack_rolls": eng._skill(p).attack_rolls(p),
          "skill": S.SKILL_TXT.get(p.character.name, ""), "zone": None if blind else S.NAME_BY_ZONE[p.zone],
          "hand": [_card(c) for c in p.hand],
          "equipped": _card(p.equipped_weapon) if p.equipped_weapon else None,
          "identity": p.identity, "win_condition": fill_for(eng, seat, S.WIN_COND.get(p.identity, "")),
          "progress": S._progress(eng, seat), "lover": lover,
          "known": {str(k): v for k, v in known.items()},
          "declared": [[s, i] for s, i in eng.declarations.get(seat, [])],
          "memo": S._memos(eng).get(seat, "")}
    messages = [{"round": m.round_no, "from": m.sender, "to": m.to, "text": m.text}
                for m in eng.visible_messages(seat)][-40:]
    events = [line for line in (S._event_line(e) for e in eng.log.events) if line][-30:]
    random_events = [{"round": e.round_no, "id": e.payload.get("id"), "name": e.payload.get("name"),
                      "zones": [S.NAME_BY_ZONE[S.ZONE_BY_NAME[z]] for z in (e.payload.get("zones") or [e.payload.get("zone")])],
                      "hits": e.payload.get("hits", [])}
                     for e in eng.log.events if e.type == "random_event"][-3:]
    view = {"seat": seat, "round": st.round_no, "phase": ph, "status": status,
            "mode": getattr(eng, "mode", "simultaneous"),
            "turn_order": [s for s in getattr(eng, "act_order", [])] if ph == "act" and S._board(eng) else [],
            "acted": sorted(getattr(eng, "act_done", set())) if ph == "act" and S._board(eng) else [],
            "open_zones": _names(st.open_zones),
            "deck_left": {S.NAME_BY_ZONE[z]: len(st.decks.get(z, [])) for z in st.open_zones},
            "feast_active": st.feast_active, "feast_next": st.feast_next,
            "frozen": _names(st.frozen_zones),
            "players": players, "me": me, "messages": messages, "events": events,
            "random_events": random_events,
            "options": _options(eng, seat, ph) if status in ("your_turn", "submitted") else None,
            "brief": getattr(eng, "briefs", {}).get(seat, ""),
            "submitted": _read_decision(seat) if status == "submitted" else None,
            "my_actions": _my_actions(eng, seat),
            "reflection": None, "result": None}
    if status == "dead":
        text = _reflection_text(eng, seat)
        view["reflection"] = {"open": not text, "text": text}
    if status == "over":
        wins = eng.identity_winners()
        view["result"] = {"identities": {str(q.seat): q.identity for q in st.players},
                          "winners": {str(s): t for s, t in wins.items() if t},
                          "humans": sorted(getattr(eng, "humans", {})),
                          "human_guesses": {str(s): g[-1][1] for s, g in getattr(eng, "human_guesses", {}).items() if g}}
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
        if kind == "eat":
            if rest.strip() not in {c["id"] for c in o["cards"]}:
                errs.append(f"只能吃你手里的食物: {rest}")
        elif kind in ("trade", "feed"):
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
            roll = d.get("roll")
            if roll is not None:                     # dice rolled on the page; missing = the engine rolls
                p = eng._p(seat)
                n, faces = eng._skill(p).attack_rolls(p), S._atk(p)
                if not (isinstance(roll, list) and len(roll) == n
                        and all(isinstance(v, int) and 1 <= v <= faces for v in roll)):
                    errs.append(f"骰子要掷 {n} 颗 d{faces},每颗 1~{faces}")
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
