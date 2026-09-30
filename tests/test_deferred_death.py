import asyncio
import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          Move, Draw, Attack)
from arena.players.base import Player
from arena.engine import Engine


class FixedPlayer(Player):
    def __init__(self, action):
        self._action = action

    async def decide_move(self, obs):
        return Move(obs.me.zone)          # stay put

    async def decide_action(self, obs):
        return self._action


def _engine(players, actions, first_seat, seed=0):
    pbs = {p.seat: FixedPlayer(actions[p.seat]) for p in players}
    st = GameState(round_no=2, players=players,          # round>=2 so movement keeps them put
                   decks={z: [] for z in Zone}, open_zones=set(Zone), first_seat=first_seat)
    return Engine(state=st, players_by_seat=pbs, rng=random.Random(seed))


def test_downed_player_still_acts_before_dying_and_can_retaliate():
    # Attacker (d1, always 1 dmg) acts first and downs the 1-HP defender.
    atk = PlayerState(seat=1, character=Character("A", 5, 1), hp=5, zone=Zone.N)
    dfn = PlayerState(seat=2, character=Character("D", 1, 1), hp=1, zone=Zone.N)
    eng = _engine([atk, dfn], {1: Attack(2), 2: Attack(1)}, first_seat=1)
    asyncio.run(eng.action_phase())
    # defender was downed by seat 1 but still took its action and hit back
    assert atk.hp == 4                      # retaliation landed (d1 -> 1 dmg)
    assert dfn.alive is True                # not yet resolved during the phase
    eng.resolve_deaths()
    assert dfn.alive is False               # dies at end-of-round resolution (still <=0)


def test_wounded_player_heals_proactively_before_dying():
    # HP 1 of 5 (below half), holds food -> should top up on its turn, not wait to be downed.
    food = Card("f1", CardType.FOOD, 2, name="面包")
    p = PlayerState(seat=1, character=Character("D", 5, 2), hp=1, zone=Zone.N, hand=[food])
    eng = _engine([p], {1: Draw()}, first_seat=1)
    asyncio.run(eng.action_phase())
    assert p.hp == 3                         # 1 + 2 (proactive heal)
    assert food not in p.hand


def test_healthy_player_does_not_waste_food():
    food = Card("f1", CardType.FOOD, 2, name="面包")
    p = PlayerState(seat=1, character=Character("D", 5, 2), hp=5, zone=Zone.N, hand=[food])
    eng = _engine([p], {1: Draw()}, first_seat=1)
    asyncio.run(eng.action_phase())
    assert food in p.hand                     # full HP -> keep the food
    assert p.hp == 5


def test_downed_player_eats_food_to_survive():
    atk = PlayerState(seat=1, character=Character("A", 5, 1), hp=5, zone=Zone.N)
    food = Card("f1", CardType.FOOD, 2, name="面包")
    dfn = PlayerState(seat=2, character=Character("D", 1, 1), hp=1, zone=Zone.N, hand=[food])
    eng = _engine([atk, dfn], {1: Attack(2), 2: Draw()}, first_seat=1)
    asyncio.run(eng.action_phase())
    eng.resolve_deaths()
    assert dfn.alive is True                # healed above 0 on its turn
    assert dfn.hp == 1                       # 1 - 1(dmg) + 2(food), capped at max HP 1
    assert food not in dfn.hand              # food consumed
