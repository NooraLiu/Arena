import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState, Card, CardType
from arena.players.base import Player
from arena.engine import Engine


def _engine(players):
    st = GameState(round_no=2, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat={p.seat: Player() for p in players},
                  rng=random.Random(0))


def _c(name, t, v):
    return Card(name, getattr(CardType, t), v, name=name)


def test_center_fighters_attack_and_also_draw_a_card():
    """Entering the center forces an attack AND grants a draw from the rich central stash."""
    a = PlayerState(0, Character("A", 10, 3), 10, Zone.CENTER)
    b = PlayerState(1, Character("B", 10, 2), 10, Zone.CENTER)
    eng = _engine([a, b])
    eng.state.decks[Zone.CENTER] = [_c("神器", "WEAPON", 5), _c("神刀", "WEAPON", 4)]
    asyncio.run(eng.action_phase())
    # both were forced to fight (took damage) AND each drew a center weapon (deck drained)
    assert len(eng.state.decks[Zone.CENTER]) == 0
    assert a.equipped_weapon is not None and b.equipped_weapon is not None
    assert a.hp < 10 and b.hp < 10


def test_center_draw_upgrades_attack_over_rounds():
    a = PlayerState(0, Character("A", 10, 3), 10, Zone.CENTER, equipped_weapon=_c("木棍", "WEAPON", 2))
    b = PlayerState(1, Character("B", 10, 4), 10, Zone.CENTER, equipped_weapon=_c("铁管", "WEAPON", 2))
    eng = _engine([a, b])
    eng.state.decks[Zone.CENTER] = [_c("advanced", "WEAPON", 6), _c("advanced2", "WEAPON", 6)]
    asyncio.run(eng.action_phase())
    # picking up an advanced center weapon raises the equipped value (total attack climbs)
    assert a.equipped_weapon.value == 6 and b.equipped_weapon.value == 6
