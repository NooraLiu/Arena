"""Compose each seat's opening brief from play/prompt_table.md.

brief = shared rules + that character's section + that identity's section + a play style,
with placeholders ({恋人}, {复仇对象}, {各区牌堆}, ...) filled from the live game.
"""
import os
import re
from collections import Counter

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_table.md")

ZONE_ORDER = ["center", "forest", "water", "stone", "city"]
ZONE_OF = {"center": "center", "n": "forest", "e": "water", "s": "stone", "w": "city"}
KEYS = ("正文", "技能", "适合区", "推荐打法", "胜利条件", "说明")   # the only recognised 键
TYPE_ZH = {"weapon": "武器", "food": "食物", "armor": "护甲", "ammo": "碎片"}


def load_table(path=TABLE):
    """-> {大节: {条目: {键: 值}}}. Only '## ' sections after the header are parsed."""
    out, sec, item, key = {}, None, None, None
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.startswith("## "):
            sec, item, key = line[3:].strip(), None, None
            out[sec] = {}
        elif line.startswith("### ") and sec is not None:
            item, key = line[4:].strip(), None
            out[sec][item] = {}
        elif item is not None:
            m = re.match(r"^([^\s:：]+)[:：]\s?(.*)$", line)
            if m and m.group(1) in KEYS:
                key = m.group(1)
                out[sec][item][key] = m.group(2)
            elif key is not None:
                out[sec][item][key] += "\n" + line
    for sec in out.values():
        for item in sec.values():
            for k in item:
                item[k] = item[k].strip()
    return out


def zone_guide(decks):
    """One line per zone, counted from the actual decks (call at game start)."""
    lines = []
    by_name = {ZONE_OF[z.value]: cards for z, cards in decks.items()}
    for name in ZONE_ORDER:
        cards = by_name.get(name, [])
        cnt = Counter(c.type.value for c in cards)
        parts = []
        for t, n in cnt.most_common():
            vals = sorted({c.value for c in cards if c.type.value == t})
            rng = f"{vals[0]}" if len(vals) == 1 else f"{vals[0]}~{vals[-1]}"
            sign = "+" if t == "weapon" else ""
            parts.append(f"{TYPE_ZH.get(t, t)}{n}({sign}{rng})")
        extra = ""
        if name == "center":
            wn = "、".join(sorted({c.name for c in cards if c.type.value == "weapon"}))
            extra = f" —— 武器全是高级/特殊武器({wn}),只有这里有;在此必须攻击,攻击后额外抽 1 张"
        lines.append(f"- {name} {len(cards)} 张: {'、'.join(parts)}{extra}")
    return "\n".join(lines)


def _tag(p):
    return f"s{p.seat} {p.character.name}"


def _fill(text, ctx):
    return re.sub(r"\{([^{}]+)\}", lambda m: str(ctx.get(m.group(1), m.group(0))), text)


def brief(eng, seat, guide, style=None, table=None):
    t = table or load_table()
    st = eng.state
    n = len(st.players)
    p = st.players[seat]
    left, right = st.players[(seat - 1) % n], st.players[(seat + 1) % n]
    partner = next((q for q in st.players if q.identity == p.identity == "Lovers" and q.seat != seat), None)
    ctx = {
        "我": _tag(p), "血量": p.character.hp_max, "攻击": p.character.base_attack,
        "左邻": _tag(left), "右邻": _tag(right), "人数": n,
        "身份池": " / ".join(sorted({q.identity for q in st.players if q.identity})),
        "各区牌堆": guide, "恋人": _tag(partner) if partner else "(无)",
        "复仇对象": _tag(right), "交换目标数": max(1, n - 2),
    }
    ch = t["角色"].get(p.character.name, {})
    ident = t["身份"].get(p.identity, {})
    L = ["=== 规则(所有人相同) ===", t["共享规则"]["规则"]["正文"], "",
         f"=== 你的角色:{_tag(p)} ===",
         f"{ctx['血量']} 血 · 基础攻击 {ctx['攻击']} · 左邻 {ctx['左邻']} · 右邻 {ctx['右邻']}",
         f"技能: {ch.get('技能', '无')}",
         f"适合区: {ch.get('适合区', '任意')}",
         f"推荐打法: {ch.get('推荐打法', '随机应变')}", "",
         f"=== 你的秘密身份:{p.identity} ===",
         f"胜利条件: {ident.get('胜利条件', '?')}",
         f"推荐打法: {ident.get('推荐打法', '随机应变')}"]
    if style:
        L += ["", f"=== 你的打法倾向:{style} ===", t["打法倾向"].get(style, {}).get("说明", "")]
    return _fill("\n".join(L), ctx)
