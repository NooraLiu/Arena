import random
from typing import Callable
from .models import Zone, PlayerState, GameState
from .players.base import Player
from .engine import Engine
from . import config


def new_game(num_players: int, rng: random.Random,
             players_factory: Callable[[], Player]) -> Engine:
    zones = list(Zone)
    players, pbs = [], {}
    for seat in range(num_players):
        ch = config.DEFAULT_CHARACTERS[seat % len(config.DEFAULT_CHARACTERS)]
        zone = zones[seat % len(zones)]
        players.append(PlayerState(seat=seat, character=ch, hp=ch.hp_max, zone=zone))
        pbs[seat] = players_factory()
    st = GameState(round_no=1, players=players, decks=config.build_region_decks(rng),
                   open_zones=set(Zone), first_seat=0)
    return Engine(state=st, players_by_seat=pbs, rng=rng)
