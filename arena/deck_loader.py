"""Load characters and region decks from the Arena 牌堆表 .xlsx.

Reads sheets by name and columns by header (so column order can change).
Skips the grey example row and blank rows.

Convention for the 所在区域牌堆 column (see the workbook's 说明 sheet):
    中心 / center            -> the center deck
    上/下/左/右 (or N/S/W/E)  -> that specific outer deck
    外区 / 外                 -> each of the four outer decks
    任意 / 全部 / all         -> every deck (center + four outer)
`张数` is the number of copies placed in EACH target zone.
"""
import random
from typing import Dict, List, Optional, Tuple
import openpyxl
from .models import Zone, Card, CardType, Character

OUTER = [Zone.N, Zone.E, Zone.S, Zone.W]
ALL_ZONES = [Zone.CENTER] + OUTER

_TOKEN_ZONES = {
    "中心": [Zone.CENTER], "center": [Zone.CENTER], "c": [Zone.CENTER],
    "上": [Zone.N], "北": [Zone.N], "n": [Zone.N],
    "下": [Zone.S], "南": [Zone.S], "s": [Zone.S],
    "左": [Zone.W], "西": [Zone.W], "w": [Zone.W],
    "右": [Zone.E], "东": [Zone.E], "e": [Zone.E],
    "外区": list(OUTER), "外": list(OUTER),
    "任意": list(ALL_ZONES), "全部": list(ALL_ZONES), "all": list(ALL_ZONES),
}


def parse_zones(text) -> List[Zone]:
    if text is None or str(text).strip() == "":
        return list(OUTER)
    t = str(text).strip().lower()
    for sep in "/、,，;； ":
        t = t.replace(sep, " ")
    result = []
    for tok in t.split():
        for z in _TOKEN_ZONES.get(tok, []):
            if z not in result:
                result.append(z)
    if not result:
        return list(OUTER)
    return sorted(result, key=lambda z: ALL_ZONES.index(z))


def _header_map(ws) -> Dict[str, int]:
    return {str(ws.cell(row=1, column=c).value).strip(): c
            for c in range(1, ws.max_column + 1)
            if ws.cell(row=1, column=c).value is not None}


def _is_data_row(cells: dict, name_key: str) -> bool:
    name = cells.get(name_key)
    if name is None or str(name).strip() == "":
        return False
    joined = " ".join(str(v) for v in cells.values() if v is not None)
    return "示例" not in joined


def _iter_rows(ws, name_key: str):
    headers = _header_map(ws)
    for r in range(2, ws.max_row + 1):
        cells = {h: ws.cell(row=r, column=c).value for h, c in headers.items()}
        if _is_data_row(cells, name_key):
            yield cells


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _open(path):
    return openpyxl.load_workbook(path, data_only=True)


def load_characters(path: str) -> List[Character]:
    wb = _open(path)
    ws = wb["人物"]
    chars = []
    for row in _iter_rows(ws, "角色名"):
        chars.append(Character(
            name=str(row["角色名"]).strip(),
            hp_max=_int(row.get("HP档(3/5/7)"), 5),
            base_attack=_int(row.get("基础攻击(2/3/4)"), 3),
        ))
    return chars


def _add_cards(decks: Dict[Zone, List[Card]], zones: List[Zone], count: int,
               base_id: str, ctype: CardType, value: int,
               name: str, description: str, effect: str, synergy: str):
    for z in zones:
        for i in range(count):
            decks[z].append(Card(
                id=f"{base_id}-{z.value}{i}", type=ctype, value=value,
                name=name, description=description, effect=effect, synergy=synergy,
            ))


def load_decks(path: str, rng: Optional[random.Random] = None) -> Dict[Zone, List[Card]]:
    wb = _open(path)
    decks: Dict[Zone, List[Card]] = {z: [] for z in ALL_ZONES}

    ws = wb["武器"]
    for row in _iter_rows(ws, "武器名"):
        name = str(row["武器名"]).strip()
        _add_cards(
            decks, parse_zones(row.get("所在区域牌堆")), max(1, _int(row.get("张数"), 1)),
            base_id=str(row.get("ID") or name), ctype=CardType.WEAPON,
            value=_int(row.get("攻击加成(+X)"), 0), name=name,
            description=str(row.get("描述") or ""), effect=str(row.get("特殊效果") or ""),
            synergy=str(row.get("角色协同") or ""),
        )

    ws = wb["物资(食物·护甲)"]
    for row in _iter_rows(ws, "牌名"):
        name = str(row["牌名"]).strip()
        kind = str(row.get("类型(食物/护甲)") or "").strip()
        ctype = CardType.ARMOR if "护甲" in kind else CardType.FOOD
        _add_cards(
            decks, parse_zones(row.get("所在区域牌堆")), max(1, _int(row.get("张数"), 1)),
            base_id=str(row.get("ID") or name), ctype=ctype,
            value=_int(row.get("数值"), 0), name=name,
            description=str(row.get("描述") or ""), effect=str(row.get("特殊效果") or ""),
            synergy="",
        )

    if rng is not None:
        for z in decks:
            rng.shuffle(decks[z])
    return decks


def load_game_data(path: str, rng: Optional[random.Random] = None
                   ) -> Tuple[List[Character], Dict[Zone, List[Card]]]:
    return load_characters(path), load_decks(path, rng)
