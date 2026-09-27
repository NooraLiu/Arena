from dataclasses import dataclass
from typing import List, Union
from ..models import PlayerState, GameState, Zone, Move, Draw, Attack


@dataclass
class Observation:
    me: PlayerState
    state: GameState
    legal_move_zones: List[Zone]
    attackable_seats: List[int]


class Player:
    async def decide_move(self, obs: "Observation") -> Move:
        raise NotImplementedError

    async def decide_action(self, obs: "Observation") -> Union[Draw, Attack]:
        raise NotImplementedError

    async def decide_additional_actions(self, obs: "Observation") -> list:
        """Extra actions beyond the main one (plant bomb, trade card, ...). Default none."""
        return []
