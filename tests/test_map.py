from arena.models import Zone
from arena.map import adjacent, legal_moves


def test_center_borders_all_outer():
    assert adjacent(Zone.CENTER) == {Zone.N, Zone.E, Zone.S, Zone.W}


def test_outer_ring_neighbors():
    assert adjacent(Zone.N) == {Zone.CENTER, Zone.E, Zone.W}
    assert adjacent(Zone.E) == {Zone.CENTER, Zone.N, Zone.S}


def test_legal_moves_includes_stay_and_excludes_closed():
    moves = legal_moves(Zone.N, open_zones={Zone.CENTER, Zone.N, Zone.E})
    assert Zone.N in moves          # stay
    assert Zone.CENTER in moves and Zone.E in moves
    assert Zone.W not in moves      # closed
