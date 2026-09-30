"""Hand AI seats' prompts to agents under random names, so the chat (tool calls, file paths, agent
replies) never shows which seats are AI -- and so which seats are the human players.

  python3 -m play.agent_alias hide    -> copies play/live/prompts/sN.txt to play/live/agents/<code>.txt
                                         (decision path rewritten to agents/<code>.json); prints the codes
  python3 -m play.agent_alias collect -> moves each agents/<code>.json to decisions/sN.json; prints counts
"""
import json
import os
import secrets
import shutil
import sys

from play import session as S

AGENTS = os.path.join(S.PLAY_LIVE, "agents")
MAP = os.path.join(AGENTS, "map.json")


def hide():
    shutil.rmtree(AGENTS, ignore_errors=True)
    os.makedirs(AGENTS)
    codes = {}
    for fn in sorted(os.listdir(S.PROMPT_DIR)):
        if not (fn.startswith("s") and fn.endswith(".txt")):
            continue
        seat = int(fn[1:-4])
        if os.path.exists(f"{S.DECISION_DIR}/s{seat}.json"):
            continue                                   # already answered (a human, or an earlier agent)
        code = secrets.token_hex(3)
        text = open(os.path.join(S.PROMPT_DIR, fn), encoding="utf-8").read()
        text = text.replace(f"{S.DECISION_DIR}/s{seat}.json", os.path.abspath(f"{AGENTS}/{code}.json"))
        with open(f"{AGENTS}/{code}.txt", "w", encoding="utf-8") as f:
            f.write(text)
        codes[code] = seat
    json.dump({k: v for k, v in codes.items()}, open(MAP, "w"))
    return sorted(codes)


def collect():
    codes = json.load(open(MAP)) if os.path.exists(MAP) else {}
    done, missing = 0, 0
    for code, seat in codes.items():
        src = f"{AGENTS}/{code}.json"
        if os.path.exists(src):
            os.makedirs(S.DECISION_DIR, exist_ok=True)
            shutil.move(src, f"{S.DECISION_DIR}/s{seat}.json")
            done += 1
        elif not os.path.exists(f"{S.DECISION_DIR}/s{seat}.json"):
            missing += 1
    return {"collected": done, "missing": missing}


if __name__ == "__main__":
    out = hide() if sys.argv[1:] == ["hide"] else collect()
    print(json.dumps(out))
