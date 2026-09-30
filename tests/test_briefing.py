import random
import re

from arena.setup import new_game
from arena.identities import IDENTITY_CONFIG
from play.briefing import load_table, brief, zone_guide

DECK = "Arena牌堆表.xlsx"


def _game(n=6, seed=3):
    return new_game(n, random.Random(seed), lambda: None, data_path=DECK)


def test_table_covers_every_identity_and_dealt_character():
    t = load_table()
    assert "正文" in t["共享规则"]["规则"]
    idents = {i for s in IDENTITY_CONFIG.values() for i in s}
    assert idents <= set(t["身份"]), idents - set(t["身份"])
    for n in range(4, 13):
        if n in IDENTITY_CONFIG:
            for p in _game(n).state.players:
                assert p.character.name in t["角色"], p.character.name
    assert len(t["打法倾向"]) >= 6


def test_briefs_have_no_unfilled_placeholders():
    eng = _game(6)
    guide = zone_guide(eng.state.decks)
    for p in eng.state.players:
        b = brief(eng, p.seat, guide, style="谨慎")
        assert not re.search(r"\{[^}]*\}", b), b
        assert p.character.name in b and p.identity in b
        assert "本局在场身份:" in b and "【胜负】" in b      # rule lines with colons stay in 正文


def test_lovers_know_their_partner():
    eng = _game(7)
    guide = zone_guide(eng.state.decks)
    a, b = [p for p in eng.state.players if p.identity == "Lovers"]
    assert f"s{b.seat} {b.character.name}" in brief(eng, a.seat, guide)
    assert f"s{a.seat} {a.character.name}" in brief(eng, b.seat, guide)


def test_vendetta_is_told_its_target():
    eng = _game(6)
    guide = zone_guide(eng.state.decks)
    v = next(p for p in eng.state.players if p.identity == "Vendetta")
    tgt = eng.state.players[(v.seat + 1) % 6]
    assert f"s{tgt.seat} {tgt.character.name}" in brief(eng, v.seat, guide)


def test_zone_guide_counts_real_decks():
    eng = _game(6)
    g = zone_guide(eng.state.decks)
    for name in ("center", "forest", "water", "stone", "city"):
        assert name in g
    assert f"center {len(eng.state.decks[next(z for z in eng.state.decks if z.value == 'center')])} 张" in g
