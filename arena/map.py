from typing import Set, List
from .models import Zone

_RING = [Zone.N, Zone.E, Zone.S, Zone.W]


def adjacent(zone: Zone) -> Set[Zone]:
    if zone == Zone.CENTER:
        return set(_RING)
    i = _RING.index(zone)
    left = _RING[(i - 1) % 4]
    right = _RING[(i + 1) % 4]
    return {Zone.CENTER, left, right}


def legal_moves(zone: Zone, open_zones: Set[Zone]) -> List[Zone]:
    options = {z for z in adjacent(zone) if z in open_zones}
    if zone in open_zones:
        options.add(zone)  # stay put
    return sorted(options, key=lambda z: z.value)
