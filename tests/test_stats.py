from arena.stats import run_many, summarize


def test_run_many_and_summarize_shapes():
    results = run_many(num_games=20, num_players=6, seed=0)
    assert len(results) == 20
    s = summarize(results)
    assert s["avg_rounds"] >= 1
    assert set(s["outcome_counts"]).issubset({"win", "draw", "capped"})
    # win rates are fractions of all games and never exceed 1 in total
    assert sum(s["win_rate_by_seat"].values()) <= 1.0 + 1e-9
