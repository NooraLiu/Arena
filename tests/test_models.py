from arena.models import Zone, CardType, Card, Character, PlayerState, Move, Draw, Attack


def test_player_state_defaults():
    ch = Character(name="Ranger", hp_max=5, base_attack=3)
    p = PlayerState(seat=1, character=ch, hp=5, zone=Zone.CENTER,
                    hand=[], equipped_weapon=None, alive=True)
    assert p.seat == 1 and p.hp == 5 and p.alive is True


def test_actions_carry_payload():
    assert Move(Zone.N).zone == Zone.N
    assert Attack(target_seat=2).target_seat == 2
    assert isinstance(Draw(), Draw)
