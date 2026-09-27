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

# recommended identity sets by player count (see 推荐身份配置)
IDENTITY_CONFIG = {
    5: ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly"],
    6: ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Negotiator"],
    7: ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers"],
}

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
    eng = new_game(args.players, rng, lambda: None, data_path=DECK)
    ids = list(IDENTITY_CONFIG[args.players])
    rng.shuffle(ids)
    for p, ident in zip(eng.state.players, ids):
        p.identity = ident
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
            print(f"! seat {p.seat} illegal move to {zname}; staying at {NAME_BY_ZONE[p.zone]}")
            continue
        p.zone = target
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


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--players", type=int, default=5); pi.add_argument("--seed", type=int, default=0)
    sub.add_parser("snapshot")
    pm = sub.add_parser("move"); pm.add_argument("mapping")
    sub.add_parser("detonate")
    pa = sub.add_parser("act"); pa.add_argument("seat", type=int); pa.add_argument("rest", nargs="*")
    sub.add_parser("endround")
    args = ap.parse_args()
    {"init": cmd_init, "snapshot": cmd_snapshot, "move": cmd_move,
     "detonate": cmd_detonate, "act": cmd_act, "endround": cmd_endround}[args.cmd](args)


if __name__ == "__main__":
    main()
