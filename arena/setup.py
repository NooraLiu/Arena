import random
from typing import Callable, Optional
from .models import Zone, PlayerState, GameState
from .players.base import Player
from .engine import Engine
from . import config
from . import identities


def new_game(num_players: int, rng: random.Random,
             players_factory: Callable[[], Player],
             data_path: Optional[str] = None) -> Engine:
    """Build a fresh game.

    If ``data_path`` points to the Arena 牌堆表 .xlsx, characters and region
    decks are loaded from it; otherwise the placeholder defaults in ``config``
    are used. The xlsx loader (and its openpyxl dependency) is imported lazily
    so the core engine stays stdlib-only.
    """
    events = []
    if data_path is not None:
        from .deck_loader import load_game_data, load_events
        characters, decks = load_game_data(data_path, rng)
        events = load_events(data_path, rng)
        if not characters:
            raise ValueError(
                f"没有从 {data_path} 的『人物』表读到任何角色——请先填好人物行(HP/攻击),再运行。")
        if not any(decks.values()):
            raise ValueError(
                f"没有从 {data_path} 的五个区的牌堆表读到任何牌——请先填好牌堆,再运行。")
    else:
        characters, decks = config.DEFAULT_CHARACTERS, config.build_region_decks(rng)

    zones = list(Zone)
    players, pbs = [], {}
    for seat in range(num_players):
        ch = characters[seat % len(characters)]
        zone = zones[seat % len(zones)]
        players.append(PlayerState(seat=seat, character=ch, hp=ch.hp_max, zone=zone))
        pbs[seat] = players_factory()
    st = GameState(round_no=1, players=players, decks=decks,
                   open_zones=set(Zone), first_seat=0, events=events)
    ids = identities.assign(num_players, rng)
    for pl, ident in zip(players, ids):
        pl.identity = ident
    return Engine(state=st, players_by_seat=pbs, rng=rng)
