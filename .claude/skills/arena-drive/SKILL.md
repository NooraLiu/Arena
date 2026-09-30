---
name: arena-drive
description: Drive the live Arena game's AI seats (推进 Arena 对局). Use when the user says 推进/继续 Arena 对局, or has just started a human+AI game from the 对战台 page.
---

# 推进 Arena 对局

The live game was started from the 对战台 (「开始新一局(人类+AI)」) or with
`python3 -m play.session init --players N --humans H`. Human seats answer on `/play.html`;
you answer for the AI seats. Run everything from the repo root.

Loop until the game is over:

1. `python3 -m play.session advance` → prints `{"phase", "waiting", "ai", "humans"}`.
2. `phase == "over"`: run `python3 -m play.session result`, tell the user the game ended, stop.
3. For every seat in `ai`: start one `arena-player` agent per seat, all in parallel, each with the
   prompt `你是座位 N。读 play/live/prompts/sN.txt,按里面的格式把决策写到 play/live/decisions/sN.json。`
   (fallback when that agent type is missing: a general-purpose agent with
   `python3 -m play.session prompt N <move|act> --rules` as its prompt). Wait for all of them.
4. If `humans` is not empty: wait until `play/live/decisions/sN.json` exists for each of those seats
   (use Monitor with an until-loop on the files; never foreground `sleep`). Humans may take minutes.
5. Go back to 1.

Rules for you as the orchestrator:
- Never read other seats' prompt/decision files into the chat, and never tell the humans anything
  from them: report only public events (moves, attacks, eliminations) and "waiting for sN".
- Don't write decisions for human seats and don't edit the save (`/tmp/arena_game.pkl`) by hand.
- If an agent's decision fails to parse, `advance` treats it as a default; just carry on.
