"""Hidden identities: the recommended per-count sets, seat neighbours, and
end-of-game win-checking.

Win conditions split into two kinds:
  - mechanical: derivable from what the engine tracks (kills, death order,
    trades, weapons held at death, attacks, final-three).  Checked automatically.
  - declared: need a player's stated guess (Social Butterfly, Sour Lemon's
    "identify", Bodyguard's "point out the target").  Passed in via `declarations`
    and, for now, taken at face value against the true identities.

Multiple winners are allowed: a player can win several tracks at once.
"""
from typing import Dict, List, Optional

IDENTITY_CONFIG = {
    5:  ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly"],
    6:  ["Warrior", "Vendetta", "Bodyguard", "Social Butterfly", "Lovers", "Lovers"],
    7:  ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers"],
    8:  ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers", "Sour Lemon"],
    9:  ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers", "Sour Lemon", "Pacifist"],
    10: ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers", "Sour Lemon", "Pacifist", "Negotiator"],
    11: ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers", "Sour Lemon", "Pacifist", "Negotiator", "Collector"],
    12: ["Warrior", "Vendetta", "Bodyguard", "Myrtle", "Social Butterfly", "Lovers", "Lovers", "Sour Lemon", "Pacifist", "Negotiator", "Collector", "Judas"],
}


def assign(num_players, rng):
    """Return a shuffled identity list for this player count (empty if unsupported)."""
    ids = list(IDENTITY_CONFIG.get(num_players, []))
    rng.shuffle(ids)
    return ids


def right_neighbor(seat: int, n: int) -> int:
    return (seat + 1) % n


def left_neighbor(seat: int, n: int) -> int:
    return (seat - 1) % n


def _seats_with(engine, identity: str) -> List[int]:
    return [p.seat for p in engine.state.players if p.identity == identity]


def _same_identity(actual, guess):
    """Declared guesses are free text: 'Lover' / 'lovers' / ' Lovers ' all mean Lovers."""
    norm = lambda x: str(x or "").strip().lower().rstrip("s")
    return actual is not None and norm(actual) == norm(guess)


def check_winners(engine, declarations: Optional[Dict[int, List[str]]] = None) -> Dict[int, List[str]]:
    """Return {seat: [tracks won]} for every player. Tracks include identity
    names and 'Survivor' for the last-alive arena winner."""
    declarations = declarations or {}
    st = engine.state
    n = len(st.players)
    ident = {p.seat: p.identity for p in st.players}
    alive = {p.seat for p in st.players if p.alive}
    wins: Dict[int, List[str]] = {p.seat: [] for p in st.players}

    # arena survival track
    if len(alive) == 1:
        wins[next(iter(alive))].append("Survivor")

    # unique most kills (>0)
    top = max(engine.kills.values(), default=0)
    warriors_by_kills = [s for s, k in engine.kills.items() if k == top and top > 0]

    # sole first death
    first_dead = None
    if engine.deaths_by_round:
        _, seats = engine.deaths_by_round[0]
        if len(seats) == 1:
            first_dead = seats[0]

    for p in st.players:
        s, ii = p.seat, ident[p.seat]
        if ii == "Myrtle" and first_dead == s:
            wins[s].append("Myrtle")
        elif ii == "Warrior" and warriors_by_kills == [s]:
            wins[s].append("Warrior")
        elif ii == "Vendetta" and engine.killer_of.get(right_neighbor(s, n)) == s:
            wins[s].append("Vendetta")
        elif ii == "Collector" and engine.died_with_advanced.get(s, 0) >= 3:
            wins[s].append("Collector")
        elif ii == "Pacifist" and s in engine.reached_final3 and s not in engine.ever_attacked:
            wins[s].append("Pacifist")
        elif ii == "Negotiator" and len(engine.trade_partners.get(s, ())) >= n - 2:
            wins[s].append("Negotiator")
        elif ii == "Judas":
            for q in st.players:
                if q.seat != s and engine.pair_trades.get(frozenset({s, q.seat}), 0) >= 3 \
                        and engine.killer_of.get(q.seat) == s:
                    wins[s].append("Judas")
                    break
        elif ii == "Bodyguard":
            vend = _seats_with(engine, "Vendetta")
            if vend:
                target = right_neighbor(vend[0], n)
                if target in alive or engine.killer_of.get(vend[0]) == s:
                    wins[s].append("Bodyguard")
        elif ii == "Lovers":
            partner = next((q.seat for q in st.players if q.identity == "Lovers" and q.seat != s), None)
            if partner is not None and (s in alive or partner in alive):   # either survives -> both win
                wins[s].append("Lovers")
        elif ii == "Sour Lemon":
            if any(ident.get(v) == "Lovers" and engine.killer_of.get(v) == s for v in engine.killer_of):
                wins[s].append("Sour Lemon")
        elif ii == "Social Butterfly":
            guesses = declarations.get(s, [])
            hits = [ident.get(gs) for (gs, gid) in guesses if _same_identity(ident.get(gs), gid)]
            # the Lovers pair counts as one identity, however many of them were named
            correct = len([h for h in hits if h != "Lovers"]) + (1 if "Lovers" in hits else 0)
            if correct >= 3:
                wins[s].append("Social Butterfly")

    return wins
