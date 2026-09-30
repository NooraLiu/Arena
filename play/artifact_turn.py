"""One orchestration step for an Artifact-hosted game: take the page's decisions, resolve as far as
the game can go, publish the next step, and hand the AI seats their prompts under code names.

  python3 -m play.artifact_turn PULL_DIR OUT_DIR
Prints only what both players may see: counts, the round/phase, public events, the writes to send
and the agent codes.
"""
import contextlib
import io
import json
import sys

from play import session as S, artifact_bridge as B, agent_alias as G


def main(pull_dir, out_dir):
    before = len(S._load().log.events)
    pulled = B.pull(pull_dir) if pull_dir != "-" else None
    with contextlib.redirect_stdout(io.StringIO()):
        adv = S.advance()
    eng = S._load()
    public = [line for line in (S._event_line(e) for e in eng.log.events[before:]) if line]
    writes = B.push(out_dir)
    codes = G.hide() if adv["ai"] else []
    print(json.dumps({"pulled": pulled, "round": eng.state.round_no, "phase": adv["phase"],
                      "humans_to_ask": len(adv["humans"]), "public_events": public,
                      "writes": writes, "agents": codes}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
