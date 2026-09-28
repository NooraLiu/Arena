"""Step-through play harness: drive a real Arena game one phase at a time,
so an LLM (or a human) can play every seat. State is pickled between calls.

Usage:
  python3 play/session.py init --players 5 --seed 7
  python3 play/session.py snapshot            # public + (for the driver) private state as JSON
  python3 play/session.py move '{"0":"forest","1":"center",...}'   # simultaneous movement
  python3 play/session.py detonate            # blow up bombs due this round
  python3 play/session.py act 0 draw
  python3 play/session.py act 1 attack 3
  python3 play/session.py act 2 bomb city
  python3 play/session.py act 2 trade 3 <card_id>
  python3 play/session.py endround            # resolve deaths, shrink, next round
"""
import argparse
import json
import os
import pickle
import random
import sys

from arena.setup import new_game
from arena.models import Zone, Draw, Attack, PlantBomb, TradeCard
from arena.map import legal_moves
from arena.engine import build_observation

STATE = os.environ.get("ARENA_STATE", "/tmp/arena_game.pkl")
DECK = "Arena牌堆表.xlsx"

ZONE_BY_NAME = {"forest": Zone.N, "林": Zone.N, "water": Zone.E, "水": Zone.E,
                "stone": Zone.S, "石": Zone.S, "city": Zone.W, "城": Zone.W,
                "center": Zone.CENTER, "中": Zone.CENTER,
                "n": Zone.N, "e": Zone.E, "s": Zone.S, "w": Zone.W, "c": Zone.CENTER}
NAME_BY_ZONE = {Zone.N: "forest", Zone.E: "water", Zone.S: "stone", Zone.W: "city", Zone.CENTER: "center"}


def _save(eng):
    with open(STATE, "wb") as f:
        pickle.dump(eng, f)


def _load():
    with open(STATE, "rb") as f:
        return pickle.load(f)


def cmd_init(args):
    rng = random.Random(args.seed)
    eng = new_game(args.players, rng, lambda: None, data_path=DECK)   # assigns identities
    _save(eng)
    print(f"initialized {args.players}-player game (seed {args.seed}); identities dealt secretly.")


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
    dead = [eng._p(s).character.name for s in before - {p.seat for p in eng.alive_players()}]
    eng.state.round_no += 1
    eng.state.first_seat = (eng.state.first_seat + 1) % len(eng.state.players)
    _save(eng)
    w = eng.check_winner()
    msg = f"round -> {eng.state.round_no}. "
    msg += f"eliminated: {dead}. " if dead else "no eliminations. "
    msg += f"alive: {[p.character.name for p in eng.alive_players()]}."
    if w is not None:
        msg += f"  *** GAME OVER: {'draw' if w == -1 else eng._p(w).character.name + ' survives'} ***"
    print(msg)


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



SKILL_TXT = {
 "Riley":"小偷(附加行动):d4 出4则偷同区一名玩家一张手牌(不偷已装备武器)",
 "Elliot":"拾荒:同区无人时一次抽2张,手牌上限6",
 "Agatha":"合成(附加行动):两张初级武器→攻击相加的武器,或减伤2的护盾",
 "Fae":"在林区,攻击的回合也能额外抽一张牌",
 "Natalie":"下毒(附加行动):2张食物→1张毒食物洗入本区牌堆,抽到者 -4",
 "Cato":"最强(15血/攻4),但不能用碎片造炸弹",
 "Garcia":"只需2枚碎片就能造一个炸弹",
 "Tobias":"三叉戟在手且在水区时,每回合多抽一张牌",
 "Bram":"蛮力:攻击时无视对方护甲",
 "Iris":"在城区每局一次,可秘密查看同区一名玩家的身份",
 "Mira":"附加行动:把食物给同区盟友吃,回血效果+2",
 "Michael":"拿到弓时,可攻击相邻区域的玩家",
}
WIN_COND = {
 "Warrior":"杀敌数唯一最多者胜(并列不算)。",
 "Vendetta":"只有亲手杀死你右边的玩家才胜;被别人抢杀就输。",
 "Bodyguard":"保护 Vendetta 的复仇对象存活(结束时指认),或亲手杀死 Vendetta。",
 "Myrtle":"第一个被淘汰(且唯一)即胜。",
 "Social Butterfly":"正确认出任意 3 名玩家的身份即胜(死前指认也算)。",
 "Lovers":"你和另一名 Lovers 互为恋人;任一方活到最后,两人同赢。",
 "Sour Lemon":"认出并杀死一名 Lovers 即胜。",
 "Pacifist":"进入最后 3 人时从未主动攻击即胜。",
 "Negotiator":"与至少(人数-2)名不同玩家各完成一次交换即胜。",
 "Collector":"死时持有 3 件高级武器(中心武器)即胜。",
 "Judas":"亲手杀死一名与你交换过 3 次手牌的玩家即胜。",
}
LIVE = "play/live"

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
    import os as _os, json as _json
    eng=_load(); st=eng.state; n=len(st.players)
    LIVEDIR=_os.path.join(os.path.dirname(os.path.dirname(__file__)),"app","live") if False else "app/live"
    _os.makedirs("app/live", exist_ok=True)
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
            elif e.type=="bomb" and "hit" in pl: hp[pl["hit"]]=pl.get("hp",hp.get(pl["hit"],0))
            elif e.type=="eliminated": alive[e.actor]=False
            elif e.type=="zone_closed": open_zones.discard(pl.get("zone"))
        snaps.append({"round":r,"open_zones":sorted(open_zones),
                      "players":[{"seat":s2,"zone":pos[s2],"hp":hp[s2],"alive":alive[s2],
                                  "equipped":final_eq[s2],"eq_atk":final_eqa[s2],"hand":final_hand[s2]} for s2 in range(n)]})
    events=[{"type":e.type,"round":e.round_no,"actor":e.actor,"visibility":e.visibility,
             "payload":e.payload} for e in eng.log.events]
    thinking={}
    tf="app/live/think.json"
    if _os.path.exists(tf):
        try: thinking={int(k):{int(rr):tt for rr,tt in v.items()} for k,v in _json.load(open(tf,encoding="utf-8")).items()}
        except Exception: thinking={}
    w=eng.check_winner()
    over = w is not None                       # winners are only judged at game end
    out={"roster":roster,"snapshots":snaps,"events":events,
         "winners":({str(k):v for k,v in eng.identity_winners().items()} if over else {}),
         "thinking":{str(k):{str(rr):tt for rr,tt in v.items()} for k,v in thinking.items()},
         "outcome":("进行中" if not over else ("draw" if w==-1 else "win")),
         "rounds":st.round_no-1,"survivor":(None if not over or w==-1 else w)}
    _json.dump(out, open("app/live/game.json","w",encoding="utf-8"), ensure_ascii=False)
    print("wrote app/live/game.json (%d snapshots, %d events)"%(len(snaps),len(events)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--players", type=int, default=5); pi.add_argument("--seed", type=int, default=0)
    sub.add_parser("snapshot")
    pm = sub.add_parser("move"); pm.add_argument("mapping")
    sub.add_parser("detonate")
    pa = sub.add_parser("act"); pa.add_argument("seat", type=int); pa.add_argument("rest", nargs="*")
    sub.add_parser("endround")
    ps = sub.add_parser("say"); ps.add_argument("seat", type=int); ps.add_argument("to"); ps.add_argument("text", nargs="+")
    pin = sub.add_parser("inbox"); pin.add_argument("seat", type=int)
    pd = sub.add_parser("declare"); pd.add_argument("seat", type=int); pd.add_argument("guesses", nargs="+")
    sub.add_parser("result")
    pb = sub.add_parser("board"); pb.add_argument("phase", nargs="?", default=None)
    sub.add_parser("export")
    args = ap.parse_args()
    {"init": cmd_init, "snapshot": cmd_snapshot, "move": cmd_move,
     "detonate": cmd_detonate, "act": cmd_act, "endround": cmd_endround,
     "say": cmd_say, "inbox": cmd_inbox, "declare": cmd_declare, "result": cmd_result, "board": cmd_board, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
