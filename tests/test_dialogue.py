import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState, Message, Move
from arena.players.base import Player
from arena.engine import Engine, build_observation


def _engine(n=3):
    players = [PlayerState(i, Character(f"P{i}", 13, 3), 13, Zone.CENTER) for i in range(n)]
    st = GameState(round_no=1, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat={p.seat: Player() for p in players}, rng=random.Random(0))


def test_public_message_is_visible_to_everyone():
    eng = _engine(3)
    eng.post_message(0, None, "let's gang up on seat 2")
    for seat in (0, 1, 2):
        vis = build_observation(eng, seat).messages
        assert any(m.text == "let's gang up on seat 2" for m in vis)


def test_private_message_only_sender_and_recipient_see_it():
    eng = _engine(3)
    eng.post_message(0, 1, "ally with me, don't tell 2")
    assert any(m.to == 1 for m in build_observation(eng, 0).messages)   # sender sees it
    assert any(m.to == 1 for m in build_observation(eng, 1).messages)   # recipient sees it
    assert build_observation(eng, 2).messages == []                     # outsider does not


def test_messages_are_logged_with_visibility():
    eng = _engine(2)
    eng.post_message(0, None, "hi all")
    eng.post_message(0, 1, "psst")
    kinds = [(e.type, e.visibility) for e in eng.log.events if e.type == "say"]
    assert ("say", "public") in kinds and ("say", "private") in kinds


def test_negotiation_phase_collects_agent_messages():
    class Talker(Player):
        async def decide_messages(self, obs):
            return [Message(round_no=obs.state.round_no, sender=obs.me.seat, to=None, text="hello")]
        async def decide_move(self, obs):
            return Move(obs.me.zone)

    eng = _engine(2)
    eng.players_by_seat = {0: Talker(), 1: Player()}
    asyncio.run(eng.negotiation_phase())
    assert any(m.text == "hello" and m.sender == 0 for m in eng.messages)
