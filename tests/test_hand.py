import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState, Card, CardType, Move, Draw
from arena.players.base import Player
from arena.engine import Engine


class DrawBot(Player):
    async def decide_move(self, obs):
        return Move(obs.me.zone)

    async def decide_action(self, obs):
        return Draw()


def _engine(player, deck):
    st = GameState(round_no=2, players=[player],
                   decks={z: [] for z in Zone}, open_zones=set(Zone), first_seat=player.seat)
    st.decks[player.zone] = deck
    return Engine(state=st, players_by_seat={player.seat: DrawBot()}, rng=random.Random(0))


def test_equipped_weapon_leaves_the_hand():
    p = PlayerState(seat=0, character=Character("X", 5, 3), hp=5, zone=Zone.N)
    weapon = Card("w1", CardType.WEAPON, 2, name="knife")
    eng = _engine(p, [weapon])
    asyncio.run(eng.action_phase())
    assert p.equipped_weapon is weapon
    assert weapon not in p.hand           # equipped card is not held in hand (doesn't count vs limit)
    assert p.hand == []


def test_upgrading_weapon_discards_the_old_one():
    p = PlayerState(seat=0, character=Character("X", 5, 3), hp=5, zone=Zone.N,
                    equipped_weapon=Card("old", CardType.WEAPON, 1, name="stick"))
    better = Card("w2", CardType.WEAPON, 3, name="rifle")
    eng = _engine(p, [better])
    asyncio.run(eng.action_phase())
    assert p.equipped_weapon is better and p.equipped_weapon.value == 3
    assert all(c.id != "old" for c in p.hand)   # old weapon discarded, not stuffed into hand
    assert p.hand == []
