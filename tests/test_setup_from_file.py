import random
import pytest
from arena.models import Zone
from arena.setup import new_game
from arena.players.bots import RandomBot
from tests.xlsx_helpers import make_workbook, DEFAULT_CHARS, DEFAULT_ZONES


def test_new_game_uses_file_characters_and_decks(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", characters=DEFAULT_CHARS, zones=DEFAULT_ZONES)
    rng = random.Random(0)
    eng = new_game(num_players=2, rng=rng, players_factory=lambda: RandomBot(rng), data_path=p)
    assert {pl.character.name for pl in eng.state.players} == {"游侠", "刺客"}
    assert any(c.name == "步枪" for c in eng.state.decks[Zone.CENTER])


def test_new_game_without_path_still_uses_defaults():
    rng = random.Random(0)
    eng = new_game(num_players=3, rng=rng, players_factory=lambda: RandomBot(rng))
    assert len(eng.state.players) == 3


def test_workbook_without_characters_raises_clear_error(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", characters=[], zones=DEFAULT_ZONES)
    rng = random.Random(0)
    with pytest.raises(ValueError, match="人物"):
        new_game(num_players=2, rng=rng, players_factory=lambda: RandomBot(rng), data_path=p)


def test_workbook_without_cards_raises_clear_error(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", characters=DEFAULT_CHARS, zones={})
    rng = random.Random(0)
    with pytest.raises(ValueError, match="牌堆"):
        new_game(num_players=2, rng=rng, players_factory=lambda: RandomBot(rng), data_path=p)
