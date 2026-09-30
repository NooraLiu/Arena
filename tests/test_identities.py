import asyncio
import random
from arena.models import Zone, Character, PlayerState, GameState, Card, CardType, Move, Attack, TradeCard
from arena.players.base import Player
from arena.engine import Engine
from arena import identities


class Fixed(Player):
    def __init__(self, action, extras=None):
        self.action = action
        self.extras = list(extras or [])

    async def decide_move(self, obs):
        return Move(obs.me.zone)

    async def decide_action(self, obs):
        return self.action

    async def decide_additional_actions(self, obs):
        out, self.extras = self.extras, []
        return out


class MaxRoll:
    def randint(self, a, b):
        return b


def _p(seat, name, hp, zone, identity, **kw):
    return PlayerState(seat, Character(name, hp, 4), hp, zone, identity=identity, **kw)


def _engine(players, bots=None, rng=None):
    st = GameState(round_no=1, players=players, decks={z: [] for z in Zone},
                   open_zones=set(Zone), first_seat=0)
    bots = bots or {p.seat: Fixed(None) for p in players}
    return Engine(state=st, players_by_seat=bots, rng=rng or MaxRoll())


def test_config_has_right_counts():
    for n in range(5, 13):
        assert len(identities.IDENTITY_CONFIG[n]) == n


def test_kill_credit_and_myrtle_sole_first_death():
    killer = _p(0, "K", 13, Zone.N, "Warrior")
    myrtle = _p(1, "M", 1, Zone.N, "Myrtle")     # 1 hp, dies to one hit
    eng = _engine([killer, myrtle])
    from arena.models import Draw
    eng._apply(killer, Attack(1))                 # killer hits myrtle to <=0
    eng.resolve_deaths()
    assert eng.kills[0] == 1                       # kill credited to seat 0
    assert eng.killer_of[1] == 0
    winners = identities.check_winners(eng)
    assert "Myrtle" in winners.get(1, [])          # sole first death
    assert "Warrior" in winners.get(0, [])         # unique most kills


def test_vendetta_wins_only_by_killing_right_neighbor():
    v = _p(0, "V", 13, Zone.N, "Vendetta")         # right neighbor = seat 1
    target = _p(1, "T", 1, Zone.N, "Bodyguard")
    other = _p(2, "O", 13, Zone.N, "Warrior")
    eng = _engine([v, target, other])
    eng._apply(v, Attack(1))                        # V kills its right neighbor
    eng.resolve_deaths()
    assert "Vendetta" in identities.check_winners(eng).get(0, [])


def test_collector_wins_if_dies_with_three_advanced_weapons():
    adv = lambda i: Card(f"w{i}", CardType.WEAPON, 4, name="rifle")
    coll = _p(0, "C", 1, Zone.N, "Collector",
              hand=[adv(1), adv(2)], equipped_weapon=adv(3))
    killer = _p(1, "K", 13, Zone.N, "Warrior")
    eng = _engine([coll, killer])
    eng._apply(killer, Attack(0))
    eng.resolve_deaths()
    assert "Collector" in identities.check_winners(eng).get(0, [])


def test_pacifist_wins_if_never_attacked_and_reaches_final_three():
    pac = _p(0, "P", 13, Zone.N, "Pacifist")
    eng = _engine([pac, _p(1, "A", 13, Zone.N, "Warrior"), _p(2, "B", 13, Zone.N, "Myrtle")])
    eng.reached_final3 = {0, 1, 2}                  # simulate having reached 3 alive
    assert "Pacifist" in identities.check_winners(eng).get(0, [])
    eng.ever_attacked.add(0)                        # once he attacks, he loses it
    assert "Pacifist" not in identities.check_winners(eng).get(0, [])


def test_play_game_reports_identity_winners():
    import random as _r
    from arena.setup import new_game
    from arena.players.bots import SmartBot
    from tests.xlsx_helpers import make_workbook, DEFAULT_CHARS, DEFAULT_ZONES
    p = make_workbook("/tmp/idwin.xlsx", characters=DEFAULT_CHARS * 3, zones=DEFAULT_ZONES)
    rng = _r.Random(0)
    eng = new_game(5, rng, lambda: SmartBot(rng), data_path=p)
    result = asyncio.run(eng.play_game())
    assert "identity_winners" in result
    assert all(pl.identity is not None for pl in eng.state.players)   # identities were dealt


def test_lovers_win_only_if_both_survive():
    a = _p(0, "A", 10, Zone.N, "Lovers")
    b = _p(1, "B", 10, Zone.N, "Lovers")
    c = _p(2, "C", 10, Zone.N, "Warrior")
    eng = _engine([a, b, c])
    c.alive = False
    w = identities.check_winners(eng)
    assert "Lovers" in w.get(0, []) and "Lovers" in w.get(1, [])
    b.alive = False                                    # partner died: no Lovers win for either
    w = identities.check_winners(eng)
    assert "Lovers" not in w.get(0, []) and "Lovers" not in w.get(1, [])


def test_social_butterfly_guesses_loose_names_and_lovers_count_once():
    sb = _p(0, "S", 10, Zone.N, "Social Butterfly")
    l1 = _p(1, "L1", 10, Zone.N, "Lovers")
    l2 = _p(2, "L2", 10, Zone.N, "Lovers")
    wa = _p(3, "W", 10, Zone.N, "Warrior")
    ve = _p(4, "V", 10, Zone.N, "Vendetta")
    eng = _engine([sb, l1, l2, wa, ve])
    both_lovers = {0: [(1, "Lover"), (2, "lovers"), (3, "Warrior")]}      # pair = 1, + Warrior = 2
    assert "Social Butterfly" not in identities.check_winners(eng, both_lovers).get(0, [])
    three = {0: [(1, "Lover"), (3, " warrior "), (4, "Vendetta")]}
    assert "Social Butterfly" in identities.check_winners(eng, three).get(0, [])


def test_six_player_set_follows_the_spreadsheet():
    # 推荐身份配置: 6 人 = 基础 5 张 + Negotiator
    assert sorted(identities.IDENTITY_CONFIG[6]) == sorted(
        ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Negotiator"])


def test_pacifist_forced_center_attack_doesnt_count_but_a_bomb_does():
    from arena.models import PlantBomb
    pac = _p(0, "P", 13, Zone.CENTER, "Pacifist",
             hand=[Card(f"a{i}", CardType.AMMO, 1) for i in range(3)])
    eng = _engine([pac, _p(1, "A", 13, Zone.CENTER, "Warrior")])
    eng._apply(pac, Attack(1), forced=True)          # the center made him swing
    assert 0 not in eng.ever_attacked
    eng._apply_additional(pac, PlantBomb(Zone.N))     # a bomb is violence
    assert 0 in eng.ever_attacked


def test_pacifist_may_fight_freely_after_reaching_the_final_three():
    pac = _p(0, "P", 13, Zone.N, "Pacifist")
    eng = _engine([pac, _p(1, "A", 13, Zone.N, "Warrior"), _p(2, "B", 13, Zone.N, "Myrtle")])
    eng.resolve_deaths()                              # 3 alive: final three reached, never attacked
    eng._apply(pac, Attack(1))
    assert "Pacifist" in identities.check_winners(eng).get(0, [])


def _give(eng, giver, to):
    card = Card(f"g{giver}-{to}-{len(eng.log.events)}", CardType.FOOD, 1)
    eng._p(giver).hand.append(card)
    eng._apply_additional(eng._p(giver), TradeCard(to, card.id))


def test_negotiator_needs_two_way_exchanges_not_gifts():
    players = [_p(0, "N", 10, Zone.N, "Negotiator")] + \
              [_p(s, f"X{s}", 10, Zone.N, "Warrior") for s in range(1, 5)]   # 5 players: needs 3
    eng = _engine(players)
    for s in (1, 2, 3):
        _give(eng, 0, s)                              # one-way gifts only
    assert "Negotiator" not in identities.check_winners(eng).get(0, [])
    for s in (1, 2):
        _give(eng, s, 0)                              # two of them give back
    assert eng.swap_partners(0) == {1, 2}
    assert "Negotiator" not in identities.check_winners(eng).get(0, [])
    _give(eng, 3, 0)
    assert "Negotiator" in identities.check_winners(eng).get(0, [])


def test_judas_counts_only_completed_swaps_with_the_victim():
    judas = _p(0, "J", 13, Zone.N, "Judas")
    friend = _p(1, "F", 1, Zone.N, "Warrior")
    eng = _engine([judas, friend])
    for _ in range(3):
        _give(eng, 0, 1)
    _give(eng, 1, 0); _give(eng, 1, 0)                # 3 gives one way, 2 back = 2 swaps
    assert eng.swap_count(0, 1) == 2
    eng._apply(judas, Attack(1))
    eng.resolve_deaths()
    assert "Judas" not in identities.check_winners(eng).get(0, [])
    eng.gives[(1, 0)] += 1                            # a third swap would have done it
    assert "Judas" in identities.check_winners(eng).get(0, [])


def test_bodyguard_protection_needs_pointing_out_the_target():
    v = _p(0, "V", 13, Zone.N, "Vendetta")            # target = seat 1
    t = _p(1, "T", 13, Zone.N, "Warrior")
    bg = _p(2, "B", 13, Zone.N, "Bodyguard")
    eng = _engine([v, t, bg])
    assert "Bodyguard" not in identities.check_winners(eng).get(2, [])
    wrong = {2: [(0, identities.TARGET_LABEL)]}
    assert "Bodyguard" not in identities.check_winners(eng, wrong).get(2, [])
    right = {2: [(1, identities.TARGET_LABEL)]}
    assert "Bodyguard" in identities.check_winners(eng, right).get(2, [])


def test_bodyguard_killing_the_vendetta_needs_no_declaration():
    v = _p(0, "V", 1, Zone.N, "Vendetta")
    bg = _p(2, "B", 13, Zone.N, "Bodyguard")
    eng = _engine([v, _p(1, "T", 13, Zone.N, "Warrior"), bg])
    eng._apply(bg, Attack(0))
    eng.resolve_deaths()
    assert "Bodyguard" in identities.check_winners(eng).get(2, [])


def test_sour_lemon_must_identify_the_lover_it_kills():
    sl = _p(0, "S", 13, Zone.N, "Sour Lemon")
    l1 = _p(1, "L1", 1, Zone.N, "Lovers")
    eng = _engine([sl, l1, _p(2, "L2", 10, Zone.N, "Lovers")])
    eng._apply(sl, Attack(1))
    eng.resolve_deaths()
    assert "Sour Lemon" not in identities.check_winners(eng).get(0, [])
    assert "Sour Lemon" in identities.check_winners(eng, {0: [(1, "Lovers")]}).get(0, [])
    assert "Sour Lemon" not in identities.check_winners(eng, {0: [(2, "Lovers")]}).get(0, [])


def test_scimitar_hurts_the_killer_and_can_take_them_down_too():
    scim = Card("s", CardType.WEAPON, 3, name="弯刀")
    holder = _p(0, "H", 1, Zone.N, "Warrior", equipped_weapon=scim)
    killer = _p(1, "K", 3, Zone.N, "Myrtle")
    bystander = _p(2, "B", 10, Zone.N, "Vendetta")
    eng = _engine([holder, killer, bystander])
    eng._apply(killer, Attack(0))
    eng.resolve_deaths()
    assert not holder.alive and not killer.alive      # 3 hp - 3 = 0: the killer falls the same round
    assert eng.killer_of[1] == 0 and eng.kills[0] == 1
    assert bystander.alive and bystander.hp == 10


def test_scimitar_in_hand_counts_and_a_healthy_killer_survives():
    holder = _p(0, "H", 1, Zone.N, "Warrior", hand=[Card("s", CardType.WEAPON, 3, name="弯刀")])
    killer = _p(1, "K", 13, Zone.N, "Myrtle")
    eng = _engine([holder, killer, _p(2, "B", 10, Zone.N, "Vendetta")])
    eng._apply(killer, Attack(0))
    eng.resolve_deaths()
    assert killer.alive and killer.hp == 10
