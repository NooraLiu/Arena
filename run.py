import argparse
import json
from arena.stats import run_many, summarize


def main():
    ap = argparse.ArgumentParser(description="Run Arena bot simulations and print pacing stats.")
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--players", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    results = run_many(args.games, args.players, args.seed)
    summary = summarize(results)
    print(f"Games: {args.games}  Players: {args.players}  Seed: {args.seed}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
