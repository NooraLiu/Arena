import asyncio
import random
from collections import Counter
from typing import List, Dict
from .setup import new_game
from .players.bots import HeuristicBot


def run_many(num_games: int, num_players: int, seed: int) -> List[Dict]:
    results = []
    for g in range(num_games):
        rng = random.Random(seed + g)
        eng = new_game(num_players, rng, lambda: HeuristicBot(rng))
        results.append(asyncio.run(eng.play_game()))
    return results


def summarize(results: List[Dict]) -> Dict:
    rounds = [r["rounds"] for r in results]
    wins = Counter(r["winner"] for r in results if r["outcome"] == "win")
    outcomes = Counter(r["outcome"] for r in results)
    first_elims, last_elims = [], []
    for r in results:
        er = list(r["elim_round_by_seat"].values())
        if er:
            first_elims.append(min(er))
            last_elims.append(max(er))
    n = len(results)
    return {
        "avg_rounds": sum(rounds) / n,
        "min_rounds": min(rounds), "max_rounds": max(rounds),
        "round_histogram": dict(sorted(Counter(rounds).items())),
        "win_rate_by_seat": {s: c / n for s, c in sorted(wins.items())},
        "outcome_counts": dict(outcomes),
        "avg_first_elim_round": (sum(first_elims) / len(first_elims)) if first_elims else 0,
        "avg_last_elim_round": (sum(last_elims) / len(last_elims)) if last_elims else 0,
    }
