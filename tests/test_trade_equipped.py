import random
from arena.models import (Zone, Character, PlayerState, GameState, Card, CardType,
                          TradeCard)
from arena.players.base import Player
from arena.engine import Engine


def _engine(players):
    st = GameState(round_no=2, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat={p.seat: Player() for p in players},
                  rng=random.Random(0))


def _c(name, t, v):
    return Card(name, getattr(CardType, t), v, name=name)


def test_can_trade_equipped_weapon_and_receiver_auto_equips_upgrade():
    giver = PlayerState(0, Character("G", 10, 2), 10, Zone.N,
                        equipped_weapon=_c("铁管", "WEAPON", 3))
    recv = PlayerState(1, Character("R", 10, 2), 10, Zone.N)   # unarmed
    eng = _engine([giver, recv])
    eng._apply_additional(giver, TradeCard(1, "铁管"))          # trade the EQUIPPED weapon
    assert giver.equipped_weapon is None                        # giver hands it over
    assert recv.equipped_weapon is not None and recv.equipped_weapon.name == "铁管"
    assert not any(c.name == "铁管" for c in recv.hand)          # equipped, not just held


def test_traded_weapon_that_is_not_an_upgrade_goes_to_hand():
    giver = PlayerState(0, Character("G", 10, 2), 10, Zone.N,
                        hand=[_c("木棍", "WEAPON", 2)])
    recv = PlayerState(1, Character("R", 10, 2), 10, Zone.N,
                       equipped_weapon=_c("好武器", "WEAPON", 5))  # already better
    eng = _engine([giver, recv])
    eng._apply_additional(giver, TradeCard(1, "木棍"))
    assert recv.equipped_weapon.name == "好武器"                 # keeps its better weapon
    assert any(c.name == "木棍" for c in recv.hand)              # weak weapon lands in hand


def test_trading_a_hand_food_card_still_works():
    giver = PlayerState(0, Character("G", 10, 2), 10, Zone.N,
                        hand=[_c("面包", "FOOD", 2)])
    recv = PlayerState(1, Character("R", 10, 2), 10, Zone.N)
    eng = _engine([giver, recv])
    eng._apply_additional(giver, TradeCard(1, "面包"))
    assert not giver.hand and any(c.name == "面包" for c in recv.hand)
