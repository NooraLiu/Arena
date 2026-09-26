import asyncio
import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          Move, Draw, Attack)
from arena.players.base import Observation
from arena.players.bots import SmartBot


def _state(players, decks=None):
    decks = decks or {z: [] for z in Zone}
    return GameState(round_no=1, players=players, decks=decks,
                     open_zones=set(Zone), first_seat=0)


def _card(i):
    return Card(id=f"w{i}", type=CardType.WEAPON, value=2, name="knife")


def test_unarmed_bot_draws_instead_of_a_weak_attack():
    # I am unarmed, attack 2 (max roll 2); target has 7 HP -> cannot kill -> arm up first.
    ch = Character("X", 5, 2)
    me = PlayerState(seat=1, character=ch, hp=5, zone=Zone.N)
    tgt = PlayerState(seat=2, character=Character("T", 7, 2), hp=7, zone=Zone.N)
    st = _state([me, tgt], decks={Zone.N: [_card(1)]})   # deck has a card to draw
    obs = Observation(me=me, state=st, legal_move_zones=[Zone.N], attackable_seats=[2])
    action = asyncio.run(SmartBot(random.Random(0)).decide_action(obs))
    assert isinstance(action, Draw)


def test_bot_secures_a_reachable_kill():
    # target HP 2 is within my attack range (4) -> take the kill rather than draw.
    ch = Character("X", 5, 4)
    me = PlayerState(seat=1, character=ch, hp=5, zone=Zone.N)
    tgt = PlayerState(seat=2, character=Character("T", 3, 2), hp=2, zone=Zone.N)
    st = _state([me, tgt], decks={Zone.N: [_card(1)]})
    obs = Observation(me=me, state=st, legal_move_zones=[Zone.N], attackable_seats=[2])
    action = asyncio.run(SmartBot(random.Random(0)).decide_action(obs))
    assert isinstance(action, Attack) and action.target_seat == 2


def test_weak_unarmed_bot_avoids_center_when_moving():
    ch = Character("X", 5, 2)
    me = PlayerState(seat=1, character=ch, hp=1, zone=Zone.N)   # weak, unarmed
    st = _state([me], decks={z: [_card(1)] for z in Zone})       # every zone has cards
    obs = Observation(me=me, state=st,
                      legal_move_zones=[Zone.CENTER, Zone.N], attackable_seats=[])
    mv = asyncio.run(SmartBot(random.Random(0)).decide_move(obs))
    assert isinstance(mv, Move) and mv.zone != Zone.CENTER
