from typing import Optional, List
from .models import Zone, Card, GameState, PlayerState


def draw(state: GameState, zone: Zone) -> Optional[Card]:
    deck = state.decks.get(zone, [])
    if not deck:
        return None
    return deck.pop(0)


def enforce_hand_limit(player: PlayerState, hand_limit: int) -> List[Card]:
    if len(player.hand) <= hand_limit:
        return []
    excess = len(player.hand) - hand_limit
    discarded = player.hand[:excess]
    player.hand = player.hand[excess:]
    return discarded
