"""Bridge between the live game (play/session.py) and a claude.ai Artifact page (app/artifact_play.html).

Human seats play on the Artifact page; the game itself runs here. The page and this bridge talk only
through the Artifact's shared database, which Claude reads and writes with its ArtifactData tool:

  steps/<step>          one doc per published step: {seq, step, game, round, phase, humans, over}
  views/<step>-<slot>     what one human seat may see at that step (play/human.human_view)
  decisions/<step>-<slot> written by the page: {step, slot, body} -- body is the agent-format decision
  decisions/refl-<slot>   written by the page: {slot, reflection}

A slot is a random per-game code for a human seat, so doc ids (which show up in Claude's tool calls,
visible to the players) never say which seat is whose.

Every doc this bridge writes is new (step ids only grow), so Claude never needs a document version.

  python3 -m play.artifact_bridge push OUT_DIR
      write steps/views JSON files for the current game state into OUT_DIR and print the ArtifactData
      batch entries ({op, collection, doc_id, file_path}) to send.
  python3 -m play.artifact_bridge pull IN_DIR
      IN_DIR holds the decisions collection as saved by an ArtifactData read with out_dir. Valid
      decisions for the current step become decision files (exactly like /api/decision); rejected ones
      are shown on the page by the next push. Prints counts only.
"""
import argparse
import glob
import json
import os
import secrets
import sys
import time

from play import session as S
from play import human as H
from app import human_api as A


def _slots(eng):
    """seat -> random slot code for every human seat of this game (made once)."""
    if not getattr(eng, "bridge_slots", None):
        eng.bridge_slots = {s: secrets.token_hex(4) for s in sorted(getattr(eng, "humans", {}))}
    return eng.bridge_slots


def _step_id(eng):
    return f"{eng.bridge_game}-{eng.bridge_seq:04d}"


def push(out_dir):
    """Publish the current state as a new step, with any errors the last pull found."""
    eng = S._load()
    errors = getattr(eng, "bridge_errors", None) or {}
    eng.bridge_errors = {}
    if not getattr(eng, "bridge_game", None):
        eng.bridge_game = "g" + secrets.token_hex(3)
        eng.bridge_seq = 0
    eng.bridge_seq += 1
    step = _step_id(eng)
    eng.bridge_step = step
    slots = _slots(eng)
    S._save(eng)
    os.makedirs(out_dir, exist_ok=True)
    humans = sorted(getattr(eng, "humans", {}))
    phase = getattr(eng, "phase", "start")
    # seq is a ms clock so the newest step wins even across games (each game's own count restarts)
    doc = {"seq": int(time.time() * 1000), "step": step, "game": eng.bridge_game, "round": eng.state.round_no,
           "phase": phase, "over": phase == "over",
           "humans": [{"slot": slots[s]} for s in humans]}   # no seat numbers or names: picking reveals nothing
    writes = [_file(out_dir, "steps", step, doc)]
    for s in humans:
        view = H.human_view(eng, s)
        view["step"] = step
        view["errors"] = errors.get(str(s)) or []
        view["slot"] = slots[s]
        writes.append(_file(out_dir, "views", f"{step}-{slots[s]}", view))
    return writes


def _file(out_dir, collection, doc_id, data):
    path = os.path.join(out_dir, f"{collection}__{doc_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return {"op": "set", "collection": collection, "doc_id": doc_id, "file_path": os.path.abspath(path)}


def _docs(in_dir):
    """Documents saved by an ArtifactData read with out_dir (any nesting), as (doc_id, body)."""
    for fp in sorted(glob.glob(os.path.join(in_dir, "**", "*.json"), recursive=True)):
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        body = d.get("data") if isinstance(d.get("data"), dict) else d
        yield os.path.splitext(os.path.basename(fp))[0], body


def pull(in_dir):
    eng = S._load()
    step = getattr(eng, "bridge_step", None)
    by_slot = {v: k for k, v in _slots(eng).items()}
    accepted, errors, reflections = [], {}, []
    for doc_id, d in _docs(in_dir):
        seat = by_slot.get(str(d.get("slot")))
        if seat is None:
            continue
        if doc_id.startswith("refl-"):
            fp = f"{S.HUMAN_DIR}/reflections/s{seat}.json"
            text = str(d.get("reflection") or "").strip()
            if text and not eng._p(seat).alive and not os.path.exists(fp) and not H._reflection_text(eng, seat):
                A._write(fp, {"reflection": text[:2000]})
                reflections.append(seat)
            continue
        if d.get("step") != step or not isinstance(d.get("body"), dict):
            continue                                    # a decision for a step that already resolved
        status = H.human_view(eng, seat)["status"]
        if status not in ("your_turn", "submitted"):
            continue
        body = d["body"]
        errs = H.validate_decision(eng, seat, eng.phase, body)
        if errs:
            errors[str(seat)] = errs
            continue
        new = A._clean(body, eng.phase)
        if H._read_decision(seat) != new:
            A._write(f"{S.DECISION_DIR}/s{seat}.json", new)
        accepted.append(seat)
    eng.bridge_errors = errors                         # the next push shows them on the page
    S._save(eng)
    # counts only: this output shows up in the chat, where both players can read it
    return {"step": step, "accepted": len(accepted), "rejected": len(errors), "reflections": len(reflections)}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("push"); pp.add_argument("out_dir")
    pl = sub.add_parser("pull"); pl.add_argument("in_dir")
    a = ap.parse_args()
    if a.cmd == "push":
        print(json.dumps(push(a.out_dir), ensure_ascii=False))
    else:
        print(json.dumps(pull(a.in_dir), ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
