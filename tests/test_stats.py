from arena.stats import run_many, summarize
from tests.xlsx_helpers import make_workbook, DEFAULT_CHARS, DEFAULT_ZONES


def test_run_many_with_deck_file(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", characters=DEFAULT_CHARS, zones=DEFAULT_ZONES)
    results = run_many(num_games=3, num_players=2, seed=0, data_path=p)
    assert len(results) == 3
    assert all(r["outcome"] in ("win", "draw", "capped", "lovers") for r in results)


def test_run_many_and_summarize_shapes():
    results = run_many(num_games=20, num_players=6, seed=0)
    assert len(results) == 20
    s = summarize(results)
    assert s["avg_rounds"] >= 1
    assert set(s["outcome_counts"]).issubset({"win", "draw", "capped", "lovers"})
    # win rates are fractions of all games and never exceed 1 in total
    assert sum(s["win_rate_by_seat"].values()) <= 1.0 + 1e-9
