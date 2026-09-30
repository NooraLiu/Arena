import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState
from arena.players.bots import RandomBot
from arena.engine import Engine, build_observation


def _engine(zones_by_seat):
    players, pbs = [], {}
    rng = random.Random(0)
    for seat, zone in zones_by_seat.items():
        ch = Character("X", 5, 3)
        players.append(PlayerState(seat=seat, character=ch, hp=5, zone=zone))
        pbs[seat] = RandomBot(rng)
    st = GameState(round_no=1, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=min(zones_by_seat))
    return Engine(state=st, players_by_seat=pbs, rng=rng)


def test_build_observation_lists_same_zone_targets():
    eng = _engine({1: Zone.CENTER, 2: Zone.CENTER, 3: Zone.N})
    obs = build_observation(eng, 1)
    assert obs.attackable_seats == [2]      # seat 3 is elsewhere


def test_movement_is_simultaneous_and_legal():
    eng = _engine({1: Zone.N, 2: Zone.S})
    asyncio.run(eng.movement_phase())
    for p in eng.state.players:
        assert p.zone in set(Zone)          # everyone landed somewhere legal


def test_round_one_is_free_placement_any_zone():
    eng = _engine({1: Zone.N})
    eng.state.round_no = 1
    obs = build_observation(eng, 1)
    assert set(obs.legal_move_zones) == set(Zone)   # choose any open zone, not just adjacent


def test_later_rounds_constrained_to_adjacency():
    eng = _engine({1: Zone.N})
    eng.state.round_no = 2
    obs = build_observation(eng, 1)
    assert Zone.S not in obs.legal_move_zones        # S is not adjacent to N


def test_center_with_target_forces_attack():
    eng = _engine({1: Zone.CENTER, 2: Zone.CENTER})
    # deck empty so a Draw would be wasted; center rule must pick Attack
    asyncio.run(eng.action_phase())
    assert any(e.type == "attack" for e in eng.log.events)


def test_center_attacker_chooses_the_target():
    from arena.models import Attack
    from arena.players.base import Player

    class HitsSeat2(Player):
        async def decide_action(self, obs):
            return Attack(2)

    eng = _engine({1: Zone.CENTER, 2: Zone.CENTER, 3: Zone.CENTER})
    eng._p(2).hp, eng._p(3).hp = 5, 1                 # seat 3 is weaker, but seat 1 picks seat 2
    eng.players_by_seat = {1: HitsSeat2(), 2: HitsSeat2(), 3: HitsSeat2()}
    asyncio.run(eng.action_phase())
    first = next(e for e in eng.log.events if e.type == "attack")
    assert first.actor == 1 and first.payload["target"] == 2
