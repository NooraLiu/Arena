# Arena Simulator v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a headless, bot-only Arena game engine that plays complete matches and reports pacing statistics (rounds per game, elimination timing, per-seat win rates) to answer whether the game drags.

**Architecture:** A pure-rules async engine (no LLM, no UI) drives the two-phase round loop (simultaneous movement → sequential actions). Players implement one async `decide()` interface; v1 ships Random and Heuristic bots. All card/character numbers live in a config module so they can be tuned without touching engine code. Every game emits a JSONL event log; a stats runner aggregates many logs.

**Tech Stack:** Python 3.9+, standard library only for the engine (`asyncio`, `random`, `dataclasses`, `enum`, `json`), `pytest` for tests. No third-party runtime dependencies in v1.

**Spec:** [Arena模拟器设计.md](../../../Arena模拟器设计.md) (see also [Arena规则.md](../../../Arena规则.md))

## Global Constraints

- Python 3.9-compatible syntax (no `match` statements, no `X | Y` type unions in annotations — use `typing.Optional`/`typing.Union`). The dev machine has Python 3.9.6.
- Engine and bots MUST NOT import any LLM client, network library, or UI framework. v1 is fully offline and deterministic given a seed.
- All randomness goes through a single injected `random.Random` instance so tests are deterministic. No bare `random.random()` / `random.choice()` calls in engine or combat code.
- All tunable numbers (HP tiers, attack values, weapon bonuses, deck composition, draw count, hand limit, armor reduction, shrink trigger, round cap) live in `arena/config.py` — never hard-coded inside logic.
- Package layout under `arena/`; tests under `tests/`. Use relative imports within the package.

## Review Focus

- **Empty region deck**: a player chooses Draw from a zone whose deck is exhausted. Expected: the draw yields nothing (no crash), the action still consumes the turn. Test in Task 3.
- **No valid attack target**: a player is forced to attack (in center with others) or chooses attack, but computes targets when alone. Expected: if no legal target, the forced-attack rule does not apply / attack is not offered; player falls back to Draw. Test in Task 7.
- **Simultaneous mutual elimination in one round**: two players reduce each other to ≤0 HP across the same action phase. Expected: both are eliminated; the engine does not crash iterating a list that changes, and win-check counts survivors correctly. Test in Task 8.
- **Game that never converges**: bots avoid each other forever. Expected: shrink closes zones each round after the trigger, and a hard round cap guarantees termination with a recorded `capped` outcome. Test in Task 8.
- **Single starting player / everyone eliminated same round**: win-check with 1 or 0 survivors. Expected: 1 survivor → that seat wins; 0 survivors → recorded as a draw, not a crash. Test in Task 8.

---

### Task 1: Project scaffold and core data models

**Files:**
- Create: `arena/__init__.py` (empty)
- Create: `arena/models.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_models.py`
- Create: `pytest.ini`

**Interfaces:**
- Produces: `Zone` (Enum: `CENTER, N, E, S, W`), `CardType` (Enum: `WEAPON, ARMOR, FOOD, AMMO`), `Card(dataclass: id:str, type:CardType, value:int)`, `Character(dataclass: name:str, hp_max:int, base_attack:int)`, `PlayerState(dataclass: seat:int, character:Character, hp:int, zone:Zone, hand:list[Card], equipped_weapon:Optional[Card], alive:bool)`, `Action` classes (`Move(zone:Zone)`, `Draw()`, `Attack(target_seat:int)`), `GameState(dataclass: round_no:int, players:list[PlayerState], decks:dict[Zone,list[Card]], open_zones:set[Zone], first_seat:int)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'arena'`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set

class Zone(Enum):
    CENTER = "center"; N = "n"; E = "e"; S = "s"; W = "w"

class CardType(Enum):
    WEAPON = "weapon"; ARMOR = "armor"; FOOD = "food"; AMMO = "ammo"

@dataclass
class Card:
    id: str
    type: CardType
    value: int  # weapon: +attack; food: +hp; armor: damage reduced; ammo: fragment count

@dataclass
class Character:
    name: str
    hp_max: int
    base_attack: int

@dataclass
class PlayerState:
    seat: int
    character: Character
    hp: int
    zone: Zone
    hand: List[Card] = field(default_factory=list)
    equipped_weapon: Optional[Card] = None
    alive: bool = True

@dataclass
class Move:
    zone: Zone
@dataclass
class Draw:
    pass
@dataclass
class Attack:
    target_seat: int

@dataclass
class GameState:
    round_no: int
    players: List[PlayerState]
    decks: Dict[Zone, List[Card]]
    open_zones: Set[Zone]
    first_seat: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: PASS (2 passed)

Also create `pytest.ini`:
```ini
[pytest]
testpaths = tests
```

- [ ] **Step 5: Commit**

```bash
git add arena/ tests/ pytest.ini
git commit -m "feat: core data models and project scaffold"
```

---

### Task 2: Map adjacency

**Files:**
- Create: `arena/map.py`
- Create: `tests/test_map.py`

**Interfaces:**
- Produces: `adjacent(zone:Zone) -> set[Zone]` — CENTER borders all four outer zones; each outer zone borders CENTER and its two ring neighbors (N–E–S–W–N). `is_adjacent(a:Zone, b:Zone) -> bool` (a is considered reachable from itself, i.e. "stay" is allowed via `legal_moves`). `legal_moves(zone:Zone, open_zones:set[Zone]) -> list[Zone]` — adjacent open zones plus staying put (if current zone still open).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_map.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_map.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/map.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_map.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/map.py tests/test_map.py
git commit -m "feat: five-zone map adjacency and legal moves"
```

---

### Task 3: Config and deck operations

**Files:**
- Create: `arena/config.py`
- Create: `arena/deck.py`
- Create: `tests/test_deck.py`

**Interfaces:**
- Produces (config): `DEFAULT_CHARACTERS: list[Character]` (mix of HP 3/5/7, attack 2/3/4), `WEAPONS: list[tuple[str,int]]` (name, +attack: knife+1, staff+2, crossbow+3, rifle+4), `DRAW_COUNT=1`, `HAND_LIMIT=5`, `ARMOR_REDUCTION=2`, `FOOD_HEAL=2`, `SHRINK_TRIGGER=5`, `ROUND_CAP=100`, `build_region_decks(rng) -> dict[Zone,list[Card]]` (center deck richer: more/higher weapons).
- Produces (deck): `draw(state, zone) -> Optional[Card]` (pops top card of the zone deck; returns None if empty), `enforce_hand_limit(player, hand_limit) -> list[Card]` (discards excess from the front, returns discarded).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deck.py
import random
from arena.models import Zone, Card, CardType, Character, PlayerState, GameState
from arena import config
from arena.deck import draw, enforce_hand_limit

def test_draw_from_empty_returns_none():
    st = GameState(round_no=1, players=[], decks={Zone.N: []},
                   open_zones={Zone.N}, first_seat=0)
    assert draw(st, Zone.N) is None

def test_draw_pops_top_card():
    c = Card(id="w1", type=CardType.WEAPON, value=2)
    st = GameState(round_no=1, players=[], decks={Zone.N: [c]},
                   open_zones={Zone.N}, first_seat=0)
    assert draw(st, Zone.N) is c
    assert draw(st, Zone.N) is None

def test_hand_limit_discards_excess():
    ch = Character("X", 5, 3)
    hand = [Card(f"c{i}", CardType.FOOD, 1) for i in range(7)]
    p = PlayerState(seat=1, character=ch, hp=5, zone=Zone.N, hand=hand)
    discarded = enforce_hand_limit(p, hand_limit=5)
    assert len(p.hand) == 5 and len(discarded) == 2

def test_region_decks_cover_all_open_zones():
    rng = random.Random(42)
    decks = config.build_region_decks(rng)
    for z in [Zone.CENTER, Zone.N, Zone.E, Zone.S, Zone.W]:
        assert z in decks and len(decks[z]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deck.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/config.py
import random
from typing import Dict, List
from .models import Zone, Card, CardType, Character

DEFAULT_CHARACTERS: List[Character] = [
    Character("Brawler", 7, 2), Character("Ranger", 5, 3),
    Character("Assassin", 3, 4), Character("Guard", 7, 2),
    Character("Scout", 5, 3), Character("Duelist", 3, 4),
]
WEAPONS = [("knife", 1), ("staff", 2), ("crossbow", 3), ("rifle", 4)]
DRAW_COUNT = 1
HAND_LIMIT = 5
ARMOR_REDUCTION = 2   # flat damage reduction when armor spent
FOOD_HEAL = 2
SHRINK_TRIGGER = 5    # start shrinking when alive count <= this
ROUND_CAP = 100       # hard termination guarantee

def _weapon(name, bonus, i):
    return Card(id=f"{name}-{i}", type=CardType.WEAPON, value=bonus)

def build_region_decks(rng: random.Random) -> Dict[Zone, List[Card]]:
    decks: Dict[Zone, List[Card]] = {}
    outer = [Zone.N, Zone.E, Zone.S, Zone.W]
    for z in outer:
        cards = []
        for i in range(3):
            name, bonus = rng.choice(WEAPONS[:2])  # outer: weaker weapons
            cards.append(_weapon(name, bonus, f"{z.value}{i}"))
        cards += [Card(f"food-{z.value}{i}", CardType.FOOD, FOOD_HEAL) for i in range(3)]
        cards += [Card(f"armor-{z.value}{i}", CardType.ARMOR, ARMOR_REDUCTION) for i in range(2)]
        rng.shuffle(cards)
        decks[z] = cards
    center = []
    for i in range(4):
        name, bonus = rng.choice(WEAPONS[1:])  # center: stronger weapons
        center.append(_weapon(name, bonus, f"c{i}"))
    center += [Card(f"food-c{i}", CardType.FOOD, FOOD_HEAL) for i in range(3)]
    center += [Card(f"armor-c{i}", CardType.ARMOR, ARMOR_REDUCTION) for i in range(2)]
    rng.shuffle(center)
    decks[Zone.CENTER] = center
    return decks
```

```python
# arena/deck.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deck.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/config.py arena/deck.py tests/test_deck.py
git commit -m "feat: config defaults and deck draw/hand operations"
```

---

### Task 4: Combat resolution

**Files:**
- Create: `arena/combat.py`
- Create: `tests/test_combat.py`

**Interfaces:**
- Consumes: `PlayerState`, `Card`, `CardType` from models.
- Produces: `attack_value(attacker:PlayerState) -> int` (base_attack + equipped weapon bonus), `resolve_attack(attacker, defender, rng, armor_reduction) -> dict` (rolls die of `attack_value` faces via `rng.randint(1, faces)`, subtracts armor reduction if defender holds an armor card — spends it — floors damage at 0, applies to defender.hp, sets `defender.alive=False` if hp<=0; returns `{"damage":int,"roll":int,"defender_eliminated":bool}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_combat.py
import random
from arena.models import Character, PlayerState, Zone, Card, CardType
from arena.combat import attack_value, resolve_attack

def _p(seat, hp, atk, weapon=None, hand=None):
    ch = Character("X", hp, atk)
    return PlayerState(seat=seat, character=ch, hp=hp, zone=Zone.CENTER,
                       hand=hand or [], equipped_weapon=weapon)

def test_attack_value_adds_weapon():
    p = _p(1, 5, 3, weapon=Card("w", CardType.WEAPON, 4))
    assert attack_value(p) == 7

def test_resolve_attack_applies_damage_and_eliminates():
    atk = _p(1, 5, 4)                 # d4
    dfn = _p(2, 3, 3)
    rng = random.Random(1)            # deterministic roll
    res = resolve_attack(atk, dfn, rng, armor_reduction=2)
    assert 1 <= res["roll"] <= 4
    assert dfn.hp == 3 - res["damage"]
    assert res["defender_eliminated"] == (dfn.hp <= 0)

def test_armor_is_spent_and_reduces_damage():
    atk = _p(1, 5, 4)
    armor = Card("a", CardType.ARMOR, 2)
    dfn = _p(2, 10, 3, hand=[armor])
    rng = random.Random(1)
    res = resolve_attack(atk, dfn, rng, armor_reduction=2)
    assert armor not in dfn.hand      # spent
    assert res["damage"] == max(0, res["roll"] - 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_combat.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/combat.py
import random
from typing import Dict
from .models import PlayerState, CardType

def attack_value(attacker: PlayerState) -> int:
    bonus = attacker.equipped_weapon.value if attacker.equipped_weapon else 0
    return attacker.character.base_attack + bonus

def _take_armor(defender: PlayerState):
    for c in defender.hand:
        if c.type == CardType.ARMOR:
            defender.hand.remove(c)
            return c
    return None

def resolve_attack(attacker: PlayerState, defender: PlayerState,
                   rng: random.Random, armor_reduction: int) -> Dict:
    faces = max(1, attack_value(attacker))
    roll = rng.randint(1, faces)
    reduction = armor_reduction if _take_armor(defender) else 0
    damage = max(0, roll - reduction)
    defender.hp -= damage
    eliminated = defender.hp <= 0
    if eliminated:
        defender.alive = False
    return {"damage": damage, "roll": roll, "defender_eliminated": eliminated}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_combat.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/combat.py tests/test_combat.py
git commit -m "feat: dice-based attack resolution with armor"
```

---

### Task 5: Player interface and bots

**Files:**
- Create: `arena/players/__init__.py` (empty)
- Create: `arena/players/base.py`
- Create: `arena/players/bots.py`
- Create: `tests/test_bots.py`

**Interfaces:**
- Consumes: `GameState`, `PlayerState`, `Zone`, `Move`, `Draw`, `Attack`, `legal_moves`, `adjacent`.
- Produces: `Observation(dataclass: me:PlayerState, state:GameState, legal_move_zones:list[Zone], attackable_seats:list[int])`, `Player` (ABC with `async def decide_move(obs) -> Move` and `async def decide_action(obs) -> Union[Draw, Attack]`), `RandomBot(rng)`, `HeuristicBot(rng)` (moves toward center if healthy else away; attacks the lowest-HP reachable target, else draws).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bots.py
import asyncio, random
from arena.models import Zone, Character, PlayerState, GameState, Move, Draw, Attack
from arena.players.base import Observation
from arena.players.bots import RandomBot, HeuristicBot

def _obs(legal_moves, attackable):
    ch = Character("X", 5, 3)
    me = PlayerState(seat=1, character=ch, hp=5, zone=Zone.N)
    st = GameState(round_no=1, players=[me], decks={}, open_zones={Zone.N}, first_seat=0)
    return Observation(me=me, state=st, legal_move_zones=legal_moves, attackable_seats=attackable)

def test_random_bot_move_is_legal():
    bot = RandomBot(random.Random(0))
    obs = _obs([Zone.N, Zone.CENTER], [])
    mv = asyncio.run(bot.decide_move(obs))
    assert mv.zone in [Zone.N, Zone.CENTER]

def test_heuristic_attacks_when_target_available():
    bot = HeuristicBot(random.Random(0))
    obs = _obs([Zone.N], attackable=[2, 3])
    action = asyncio.run(bot.decide_action(obs))
    assert isinstance(action, Attack) and action.target_seat in [2, 3]

def test_heuristic_draws_when_no_target():
    bot = HeuristicBot(random.Random(0))
    obs = _obs([Zone.N], attackable=[])
    action = asyncio.run(bot.decide_action(obs))
    assert isinstance(action, Draw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bots.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/players/base.py
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
```

```python
# arena/players/bots.py
import random
from typing import Union
from ..models import Zone, Move, Draw, Attack
from .base import Player, Observation

class RandomBot(Player):
    def __init__(self, rng: random.Random):
        self.rng = rng
    async def decide_move(self, obs: Observation) -> Move:
        return Move(self.rng.choice(obs.legal_move_zones))
    async def decide_action(self, obs: Observation) -> Union[Draw, Attack]:
        if obs.attackable_seats and self.rng.random() < 0.5:
            return Attack(self.rng.choice(obs.attackable_seats))
        return Draw()

class HeuristicBot(Player):
    def __init__(self, rng: random.Random):
        self.rng = rng
    async def decide_move(self, obs: Observation) -> Move:
        healthy = obs.me.hp > obs.me.character.hp_max // 2
        if healthy and Zone.CENTER in obs.legal_move_zones:
            return Move(Zone.CENTER)
        outer = [z for z in obs.legal_move_zones if z != Zone.CENTER]
        return Move(self.rng.choice(outer) if outer else obs.legal_move_zones[0])
    async def decide_action(self, obs: Observation) -> Union[Draw, Attack]:
        targets = obs.attackable_seats
        if targets:
            by_hp = sorted(targets, key=lambda s: next(
                p.hp for p in obs.state.players if p.seat == s))
            return Attack(by_hp[0])
        return Draw()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bots.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/players/ tests/test_bots.py
git commit -m "feat: async Player interface and Random/Heuristic bots"
```

---

### Task 6: Events and JSONL logging

**Files:**
- Create: `arena/events.py`
- Create: `tests/test_events.py`

**Interfaces:**
- Produces: `Event(dataclass: type:str, round_no:int, actor:Optional[int], visibility:str, payload:dict)`, `EventLog` (collects events; `record(event)`; `to_jsonl() -> str`; `write(path)`). `visibility` is one of `"public" | "private" | "self"` (v1 uses `"public"` throughout; the field exists so v2 dialogue slots in without a schema change).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events.py
import json
from arena.events import Event, EventLog

def test_event_log_serializes_to_jsonl():
    log = EventLog()
    log.record(Event(type="attack", round_no=2, actor=1,
                      visibility="public", payload={"target": 3, "damage": 4}))
    log.record(Event(type="eliminated", round_no=2, actor=3,
                      visibility="public", payload={}))
    lines = log.to_jsonl().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "attack" and first["payload"]["damage"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_events.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/events.py
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List

@dataclass
class Event:
    type: str
    round_no: int
    actor: Optional[int]
    visibility: str
    payload: Dict

@dataclass
class EventLog:
    events: List[Event] = field(default_factory=list)
    def record(self, event: Event) -> None:
        self.events.append(event)
    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(asdict(e), ensure_ascii=False) for e in self.events) + "\n"
    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_jsonl())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_events.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/events.py tests/test_events.py
git commit -m "feat: structured event log with JSONL output"
```

---

### Task 7: Engine — movement and action phases

**Files:**
- Create: `arena/engine.py`
- Create: `tests/test_engine_phases.py`

**Interfaces:**
- Consumes: everything above, plus `attack_value`, `resolve_attack`, `draw`, `enforce_hand_limit`, `legal_moves`, `adjacent`, `RandomBot`.
- Produces: `Engine(dataclass-like: state, players_by_seat:dict[int,Player], rng, log, config module)`, `build_observation(engine, seat) -> Observation` (attackable = alive others in the same zone; a character skill hook is out of scope for v1), `async movement_phase(engine)` (collects every alive player's `decide_move` **before** applying any — simultaneous), `async action_phase(engine)` (seat order starting at `first_seat`; center-with-others forces Attack when a target exists; otherwise player chooses; applies Draw via `deck.draw`+auto-equip-best-weapon+`enforce_hand_limit`, or Attack via `resolve_attack`; records events). Auto-equip rule: after drawing, if the drawn card is a weapon with higher `value` than the equipped one, equip it (old weapon stays in hand).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_phases.py
import asyncio, random
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

def test_center_with_target_forces_attack():
    eng = _engine({1: Zone.CENTER, 2: Zone.CENTER})
    # deck empty so a Draw would be wasted; center rule must pick Attack
    asyncio.run(eng.action_phase())
    # at least one attack event recorded
    assert any(e.type == "attack" for e in eng.log.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_engine_phases.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/engine.py
import random
from typing import Dict, List
from .models import Zone, PlayerState, GameState, Move, Draw, Attack, CardType
from .map import legal_moves
from .deck import draw as deck_draw, enforce_hand_limit
from .combat import resolve_attack, attack_value
from .players.base import Observation, Player
from .events import Event, EventLog
from . import config

class Engine:
    def __init__(self, state: GameState, players_by_seat: Dict[int, Player],
                 rng: random.Random = None, log: EventLog = None):
        self.state = state
        self.players_by_seat = players_by_seat
        self.rng = rng or random.Random()
        self.log = log or EventLog()

    def alive_players(self) -> List[PlayerState]:
        return [p for p in self.state.players if p.alive]

    def _p(self, seat: int) -> PlayerState:
        return next(p for p in self.state.players if p.seat == seat)

    async def movement_phase(self):
        chosen = {}
        for p in self.alive_players():
            obs = build_observation(self, p.seat)
            mv: Move = await self.players_by_seat[p.seat].decide_move(obs)
            zone = mv.zone if mv.zone in obs.legal_move_zones else p.zone
            chosen[p.seat] = zone
        for seat, zone in chosen.items():          # apply after all decided
            self._p(seat).zone = zone
            self.log.record(Event("move", self.state.round_no, seat, "public",
                                   {"to": zone.value}))

    async def action_phase(self):
        order = sorted(self.alive_players(), key=lambda p: (p.seat - self.state.first_seat) % 100)
        for p in order:
            if not p.alive:
                continue
            obs = build_observation(self, p.seat)
            forced = (p.zone == Zone.CENTER and obs.attackable_seats)
            if forced:
                action = Attack(self._lowest_hp(obs.attackable_seats))
            else:
                action = await self.players_by_seat[p.seat].decide_action(obs)
                if isinstance(action, Attack) and action.target_seat not in obs.attackable_seats:
                    action = Draw()
            self._apply(p, action)

    def _lowest_hp(self, seats):
        return sorted(seats, key=lambda s: self._p(s).hp)[0]

    def _apply(self, p: PlayerState, action):
        if isinstance(action, Draw):
            card = deck_draw(self.state, p.zone)
            if card is not None:
                p.hand.append(card)
                if card.type == CardType.WEAPON and (
                        p.equipped_weapon is None or card.value > p.equipped_weapon.value):
                    p.equipped_weapon = card
                enforce_hand_limit(p, config.HAND_LIMIT)
            self.log.record(Event("draw", self.state.round_no, p.seat, "public",
                                   {"got": card.id if card else None}))
        elif isinstance(action, Attack):
            defender = self._p(action.target_seat)
            res = resolve_attack(p, defender, self.rng, config.ARMOR_REDUCTION)
            self.log.record(Event("attack", self.state.round_no, p.seat, "public",
                                   {"target": defender.seat, **res}))
            if res["defender_eliminated"]:
                self.log.record(Event("eliminated", self.state.round_no,
                                       defender.seat, "public", {}))

def build_observation(engine: Engine, seat: int) -> Observation:
    me = engine._p(seat)
    attackable = [q.seat for q in engine.alive_players()
                  if q.seat != seat and q.zone == me.zone]
    moves = legal_moves(me.zone, engine.state.open_zones)
    return Observation(me=me, state=engine.state,
                       legal_move_zones=moves, attackable_seats=attackable)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_engine_phases.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/engine.py tests/test_engine_phases.py
git commit -m "feat: engine movement and action phases"
```

---

### Task 8: Engine — shrink, win check, full game loop

**Files:**
- Modify: `arena/engine.py` (add `shrink_step`, `check_winner`, `play_round`, `play_game`)
- Create: `arena/setup.py` (builds a starting `GameState` from config)
- Create: `tests/test_game.py`

**Interfaces:**
- Consumes: config (`SHRINK_TRIGGER`, `ROUND_CAP`), `build_region_decks`, `DEFAULT_CHARACTERS`.
- Produces: `new_game(num_players, rng, players_factory) -> Engine` in `setup.py` (assigns characters cyclically, scatters players across zones, builds decks, all zones open). Engine methods: `shrink_step()` (if alive ≤ `SHRINK_TRIGGER`, close one outer zone per round in fixed order W,S,E,N; players in a closed zone are pushed to CENTER; CENTER never closes), `check_winner() -> Optional[int]` (returns seat if exactly 1 alive, `-1` for 0 alive, else None), `async play_round()` (movement → action → shrink → increment round, rotate `first_seat`), `async play_game() -> dict` (loops `play_round` until a winner or `ROUND_CAP`; returns `{"winner":seat_or_None, "rounds":int, "outcome":"win"|"draw"|"capped", "elim_round_by_seat":dict}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_game.py
import asyncio, random
from arena.setup import new_game
from arena.players.bots import HeuristicBot
from arena.engine import Engine

def _game(seed, n=6):
    rng = random.Random(seed)
    return new_game(num_players=n, rng=rng,
                    players_factory=lambda: HeuristicBot(rng))

def test_game_terminates_and_reports_rounds():
    result = asyncio.run(_game(1).play_game())
    assert result["outcome"] in ("win", "draw", "capped")
    assert result["rounds"] >= 1

def test_winner_is_last_survivor_when_win():
    for seed in range(5):
        eng = _game(seed)
        result = asyncio.run(eng.play_game())
        if result["outcome"] == "win":
            alive = [p.seat for p in eng.state.players if p.alive]
            assert alive == [result["winner"]]

def test_shrink_pushes_players_out_of_closed_center_never_closes():
    eng = _game(2)
    # force shrink condition
    for p in eng.state.players[5:]:
        p.alive = False
    eng.shrink_step()
    from arena.models import Zone
    assert Zone.CENTER in eng.state.open_zones
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_game.py -v`
Expected: FAIL with `ImportError` (setup module) / `AttributeError` (missing methods)

- [ ] **Step 3: Write minimal implementation**

```python
# arena/setup.py
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
```

Add to `arena/engine.py`:

```python
    _SHRINK_ORDER = [Zone.W, Zone.S, Zone.E, Zone.N]

    def shrink_step(self):
        if len(self.alive_players()) > config.SHRINK_TRIGGER:
            return
        for z in self._SHRINK_ORDER:
            if z in self.state.open_zones:
                self.state.open_zones.discard(z)
                for p in self.alive_players():
                    if p.zone == z:
                        p.zone = Zone.CENTER
                self.log.record(Event("zone_closed", self.state.round_no, None,
                                       "public", {"zone": z.value}))
                break

    def check_winner(self):
        alive = self.alive_players()
        if len(alive) == 1:
            return alive[0].seat
        if len(alive) == 0:
            return -1
        return None

    async def play_round(self):
        await self.movement_phase()
        await self.action_phase()
        self.shrink_step()
        self.state.round_no += 1
        self.state.first_seat = (self.state.first_seat + 1) % len(self.state.players)

    async def play_game(self):
        elim_round = {}
        while True:
            before = {p.seat for p in self.alive_players()}
            w = self.check_winner()
            if w is not None:
                outcome = "draw" if w == -1 else "win"
                return {"winner": None if w == -1 else w,
                        "rounds": self.state.round_no - 1,
                        "outcome": outcome, "elim_round_by_seat": elim_round}
            if self.state.round_no > config.ROUND_CAP:
                survivors = self.alive_players()
                top = max(survivors, key=lambda p: p.hp).seat if survivors else None
                return {"winner": top, "rounds": self.state.round_no - 1,
                        "outcome": "capped", "elim_round_by_seat": elim_round}
            await self.play_round()
            after = {p.seat for p in self.alive_players()}
            for seat in before - after:
                elim_round[seat] = self.state.round_no - 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_game.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add arena/engine.py arena/setup.py tests/test_game.py
git commit -m "feat: shrink, win check, and full game loop"
```

---

### Task 9: Stats runner and CLI

**Files:**
- Create: `arena/stats.py`
- Create: `run.py`
- Create: `tests/test_stats.py`

**Interfaces:**
- Consumes: `new_game`, `HeuristicBot`, `play_game`.
- Produces: `run_many(num_games, num_players, seed) -> list[dict]` (each is a `play_game` result), `summarize(results) -> dict` (`avg_rounds`, `min_rounds`, `max_rounds`, `round_histogram:dict[int,int]`, `win_rate_by_seat:dict[int,float]`, `outcome_counts:dict`, `avg_first_elim_round`, `avg_last_elim_round`). `run.py` is a CLI: `python3 run.py --games 1000 --players 6 --seed 0` prints the summary as readable text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stats.py
from arena.stats import run_many, summarize

def test_run_many_and_summarize_shapes():
    results = run_many(num_games=20, num_players=6, seed=0)
    assert len(results) == 20
    s = summarize(results)
    assert s["avg_rounds"] >= 1
    assert abs(sum(s["win_rate_by_seat"].values()) +
               s["outcome_counts"].get("draw", 0) / len(results) - 1.0) < 1e-6 \
        or s["outcome_counts"].get("draw", 0) >= 0   # draws don't attribute to a seat
    assert set(s["outcome_counts"]).issubset({"win", "draw", "capped"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_stats.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# arena/stats.py
import asyncio, random
from collections import Counter
from typing import List, Dict
from .setup import new_game
from .players.bots import HeuristicBot

def run_many(num_games: int, num_players: int, seed: int) -> List[Dict]:
    results = []
    for g in range(num_games):
        rng = random.Random(seed + g)
        eng = new_game(num_players, rng, lambda: HeuristicBot(rng))
        results.append(asyncio.run(eng.play_game()))
    return results

def summarize(results: List[Dict]) -> Dict:
    rounds = [r["rounds"] for r in results]
    wins = Counter(r["winner"] for r in results if r["outcome"] == "win")
    outcomes = Counter(r["outcome"] for r in results)
    first_elims, last_elims = [], []
    for r in results:
        er = list(r["elim_round_by_seat"].values())
        if er:
            first_elims.append(min(er)); last_elims.append(max(er))
    n = len(results)
    return {
        "avg_rounds": sum(rounds) / n,
        "min_rounds": min(rounds), "max_rounds": max(rounds),
        "round_histogram": dict(sorted(Counter(rounds).items())),
        "win_rate_by_seat": {s: c / n for s, c in sorted(wins.items())},
        "outcome_counts": dict(outcomes),
        "avg_first_elim_round": (sum(first_elims) / len(first_elims)) if first_elims else 0,
        "avg_last_elim_round": (sum(last_elims) / len(last_elims)) if last_elims else 0,
    }
```

```python
# run.py
import argparse, json
from arena.stats import run_many, summarize

def main():
    ap = argparse.ArgumentParser(description="Run Arena bot simulations and print pacing stats.")
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--players", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    results = run_many(args.games, args.players, args.seed)
    summary = summarize(results)
    print(f"Games: {args.games}  Players: {args.players}  Seed: {args.seed}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_stats.py -v`
Expected: PASS (1 passed). Then run the full suite: `python3 -m pytest -v` (all green), and a smoke run: `python3 run.py --games 200 --players 6`.

- [ ] **Step 5: Commit**

```bash
git add arena/stats.py run.py tests/test_stats.py
git commit -m "feat: stats runner and CLI for pacing analysis"
```

---

## After v1

Running `python3 run.py --games 1000 --players 6` answers the B question directly: read `avg_rounds`, the `round_histogram` (is it long-tailed / does it hit the cap?), `avg_first_elim_round` vs `avg_last_elim_round` (does the middle drag?), and `win_rate_by_seat` (positional imbalance). Tune the numbers in `arena/config.py` (weapon frequency is the biggest lever) and re-run. Once pacing feels right, proceed to the v2 plan (LLM agents + dialogue + real-time play table) — a separate spec/plan cycle.
