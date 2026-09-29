from arena.models import Zone, CardType
from arena.deck_loader import load_characters, load_decks, load_game_data, parse_zones
from tests.xlsx_helpers import make_workbook, DEFAULT_CHARS


def _zones():
    return {
        "林区牌堆": [
            ["示例↓ 林00", "食物", "示例蘑菇", "x", 2, "", "", 9, "格式示例"],   # example row, skipped
            ["林01", "武器", "弓", "A hunter's bow", 2, "Wren:可攻击相邻区域", "", 1, ""],
            ["林02", "食物", "蘑菇", "看上去有点毒的蘑菇", 2, "", "", 3, ""],
        ],
        "水区牌堆": [["水01", "武器", "三叉戟", "trident", "+3", "", "", 1, ""]],
        "中心牌堆": [
            ["中01", "护甲", "石板盾", "", -2, "", "", 1, ""],       # armor written as a reduction
            ["中02", "碎片", "弹药碎片", "", None, "", "", 2, ""],   # fragment value defaults to 1
        ],
    }


def test_load_characters_skips_example_and_reads_stats(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", characters=[
        ["示例↓ C01", "示例·游侠", "x", 13, 3, "skill", 1, ""],
        ["C01", "Riley", "", 13, 3, "小偷", None, ""],
        ["C06", "Cato", "", 15, 4, "", None, ""],
    ])
    chars = load_characters(p)
    assert [c.name for c in chars] == ["Riley", "Cato"]
    assert chars[1].hp_max == 15 and chars[1].base_attack == 4


def test_each_zone_sheet_fills_its_own_deck(tmp_path):
    decks = load_decks(make_workbook(tmp_path / "d.xlsx", zones=_zones()))
    assert [c.name for c in decks[Zone.N]].count("弓") == 1
    assert [c.name for c in decks[Zone.N]].count("蘑菇") == 3
    assert [c.name for c in decks[Zone.E]] == ["三叉戟"]
    assert decks[Zone.S] == [] and decks[Zone.W] == []


def test_card_types_and_values(tmp_path):
    decks = load_decks(make_workbook(tmp_path / "d.xlsx", zones=_zones()))
    bow = next(c for c in decks[Zone.N] if c.name == "弓")
    assert bow.type == CardType.WEAPON and bow.value == 2
    assert next(c for c in decks[Zone.N] if c.name == "蘑菇").type == CardType.FOOD
    assert decks[Zone.E][0].value == 3                       # "+3" text parses
    shield = next(c for c in decks[Zone.CENTER] if c.name == "石板盾")
    assert shield.type == CardType.ARMOR and shield.value == 2   # -2 reduction stored as 2
    frags = [c for c in decks[Zone.CENTER] if c.type == CardType.AMMO]
    assert len(frags) == 2 and frags[0].value == 1


def test_values_written_as_text_are_parsed(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", zones={"林区牌堆": [
        ["林01", "食物", "苹果", "", "+2Health", "", "", 1, ""],
        ["林02", "食物", "虾", "", "+1health", "", "", 1, ""],
        ["林03", "护甲", "石板盾", "", "+2 防御", "", "", 1, ""],
    ]})
    by_name = {c.name: c for c in load_decks(p)[Zone.N]}
    assert by_name["苹果"].value == 2
    assert by_name["虾"].value == 1
    assert by_name["石板盾"].value == 2


def test_extra_columns_are_preserved(tmp_path):
    decks = load_decks(make_workbook(tmp_path / "d.xlsx", zones=_zones()))
    bow = next(c for c in decks[Zone.N] if c.name == "弓")
    assert bow.description == "A hunter's bow"
    assert bow.synergy == "Wren:可攻击相邻区域"


def test_unknown_card_type_raises_clear_error(tmp_path):
    import pytest
    p = make_workbook(tmp_path / "d.xlsx", zones={"石区牌堆": [["石01", "法术", "火球", "", 3, "", "", 1, ""]]})
    with pytest.raises(ValueError, match="石区牌堆"):
        load_decks(p)


def test_zone_names_map_to_ring_positions():
    # ring order 林区 -> 水区 -> 石区 -> 城区 -> (back to 林区)
    assert parse_zones("林区") == [Zone.N]
    assert parse_zones("水区") == [Zone.E]
    assert parse_zones("石区") == [Zone.S]
    assert parse_zones("城区") == [Zone.W]
    assert parse_zones("Central") == [Zone.CENTER]


def test_load_game_data_returns_both(tmp_path):
    p = make_workbook(tmp_path / "d.xlsx", characters=[["C01", "Riley", "", 13, 3, "", None, ""]],
                      zones=_zones())
    chars, decks = load_game_data(p)
    assert len(chars) == 1 and len(decks[Zone.N]) == 4


def test_zero_count_card_is_left_out_but_blank_count_means_one(tmp_path):
    from arena.models import Zone
    path = make_workbook(tmp_path / "d.xlsx", DEFAULT_CHARS, {
        "林区牌堆": [["林01", "食物", "面包", "", 2, "", "", 0, "退役"],
                    ["林02", "武器", "木棍", "", 2, "", "", None, ""]],
    })
    decks = load_decks(path)
    assert [c.name for c in decks[Zone.N]] == ["木棍"]
