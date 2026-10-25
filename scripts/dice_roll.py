#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
骰子选餐引擎 —— 「今天吃啥」决策降级。

## 两种骰子模式

| 模式 | 原子数 | 映射 | 特点 |
|---|---:|---|---|
| `single` 单骰（v1） | 6 | 池按价格切 6 段，段内随机 | 简单，但段边界取整导致命中概率不均 |
| `triple` 三骰（v2，默认） | 216 | 216 级强度阶梯，每个候选独占等长原子段 | 概率近均匀 + 点数↔价格严格单调 + 可复现 |

### 为什么是 216 而不是 18（2026-10-24 实测推导）

三骰「点数总和」只有 16 个不同取值（3~18），分布极不均匀：
  点数 10/11/12 合计占 36.6%，点数 3 与 18 各只有 0.46%。
  概率熵 3.5993 bits（均匀 16 档需 4.0000 bits）。

若按总和分 16 档映射到候选池，**候选数 n > 8 时均匀映射在数学上不可能**：
单个原子概率 12.5% > 1/n，必然把概率挤到少数候选上。
统一口径实测（真实菜单 + 权威人数，9 个有解场景 × 20000 次）：

  | 映射方案     | 平均 Gini（越低越均匀） | 平均 ρ（点数↔价格） |
  |--------------|------------------------:|--------------------:|
  | 单骰 6 段    | 0.0387                  | +0.546              |
  | 总和 16 档   | 0.2409（明显更差）      | +0.531              |
  | 216 级阶梯   | 0.0119 ★                | +0.582 ★            |

  均匀性 M216 比 M6 提升 3.2 倍、比 M16 提升 20.2 倍；
  只看池容量 ≥ 8 的场景（M6 0.0578 → M216 0.0246）提升 2.3 倍。

用 216 个「有序三元组」当原子即可突破该下界：
  把 216 个 (a,b,c) 按强度键（总和 → 最大骰 → 中位骰 → 最小骰）排成阶梯，
  候选池按总价升序对应等长阶梯段 → 强度越大价格越贵（严格单调，违例 0），
  且每个候选命中概率 = 1/n（n 能整除 216 时完全均匀）。
  额外收益：同组骰面必得同一结果 —— 可复现、可分享、可反查。

### 排列组合的第二重价值：叙事标签

216 种骰面按结构可分 4 类（豹子 / 对子 / 顺子 / 散牌）。
结构与点数总和【强相关】（豹子只在 3/6/9/12/15/18 出现），
因此**不能当作独立于价位的第二决策维度**，否则二者互相打架。
正确用法是【叙事标签 + 免费重投权】——不影响合规性：
  豹子 2.8%  「幸运三连」→ 免费重投一次
  顺子 11.1% 「顺水一局」→ 免费重投一次
  对子 41.7% 「双拼日」  → 仅标签
  散牌 44.4% 「日常局」  → 仅标签

## 硬约束（任何模式下必须全 0）

| 约束 | 保证方式 |
|---|---|
| 不超预算 | 建池按总价过滤；多份投掷时单份上限收紧为「档上限 / 投掷次数」 |
| 不违反忌口 | 建池阶段过滤，骰子不可能 roll 出违规项 |
| 供餐量够人数 | 建池用**权威人数**（query-meal-detail 的饮料数），非名称推断 |
| 不选纯饮品 | 全局排除 |
| 组合总价不翻倍 | 组合的 total 已是 N 份合计，累加时不再乘次数 |

### 供餐人数：名称推断不可靠（2026-10-24 实测 44 个套餐全量核对）

名称含「双人餐」不代表 2 人份：
  「麦麦周末双人餐」59.5 元 → 真实 1 人份
  「开心亲子双人餐」59.5 元 → 真实 1 人份
名称推断错误率 2/44 = 5%，且错的都是「双人餐」—— 直接影响 2 人场景池子。
→ 权威判据：query-meal-detail 的饮料 round 默认项 quantity（几杯饮料 = 几人份）。
→ 用 scripts/serves_probe.py 批量生成缓存（serves_map.json）。
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import re
import sys
from typing import Optional

# ---------------------------------------------------------------- 预算档
BANDS = [
    {"key": "under50", "label": "50以内", "lo": 0, "hi": 50},
    {"key": "50to100", "label": "50-100", "lo": 50, "hi": 100},
    {"key": "over100", "label": "100+", "lo": 100, "hi": 10 ** 9},
]
BAND_ALIASES = {
    "50以内": "under50", "50以内以内": "under50", "under50": "under50",
    "50-100": "50to100", "50到100": "50to100", "50to100": "50to100",
    "100+": "over100", "100以上": "over100", "over100": "over100",
}

# ---------------------------------------------------------------- 菜单识别
SPICY_HINTS = ["辣椒黄油", "韩式甜辣", "麦辣", "辣味", "香辣", "变态辣",
               "麻辣", "酸辣", "辣"]
MAIN_KEYWORDS = ["餐", "套", "桶", "盒", "拼盘", "全明星", "分享"]

# 纯饮品（不能算一顿饭，组合兜底时必须排除）
DRINK_ONLY = ["牛奶", "果汁", "可乐", "雪碧", "怡泉", "美汁源", "柠檬红茶",
              "冰咖", "美式", "奶铁", "黑巧", "鲜萃", "纯牛奶", "苹果汁",
              "阳光柠檬", "鲜奶"]


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def meals_of(doc) -> dict:
    return (doc.get("data") or {}).get("meals") or {}


def is_spicy(name: str) -> bool:
    return any(k in name for k in SPICY_HINTS)


def is_drink_only(name: str) -> bool:
    """
    是否纯饮品（无主食）。组合兜底时必须排除。

    ⚠️ 顺序很重要：先看是否含【主食】，再看是否命中饮品词。
    「纯牛奶」含"奶"，但"奶"在饮品表里、"牛"在主食表里，
    若先用主食表排除会把它误判成正餐（曾导致组合兜底选出"2份纯牛奶"）。
    """
    if any(k in name for k in ["餐", "套", "堡", "鸡", "鱼", "薯", "翅",
                               "块", "腿", "卷", "派", "旋风", "蛋", "猪柳",
                               "鸡薯", "全麦", "三明治", "卷饼"]):
        return False
    if re.search(r"牛(?!奶|肉堡)", name) and "堡" not in name:
        pass
    return any(k in name for k in DRINK_ONLY)


def serves_of(name: str) -> int:
    """
    从套餐名推断供餐人数 —— **仅在没有权威数据时兜底**。

    ⚠️ 名称不可全信（2026-10-24 全量核对 44 个套餐）：
        「麦麦周末双人餐」「开心亲子双人餐」名称含"双人"但真实只有 1 人份。
        有 serves_map 时请务必使用权威值。
    """
    if any(k in name for k in ["四人餐", "合家欢", "欢享", "盛宴"]):
        return 4
    if "三人餐" in name:
        return 3
    if "双人餐" in name or "分享餐" in name or "全家桶" in name:
        return 2
    return 1


def normalize_band(raw: str) -> Optional[dict]:
    if not raw:
        return None
    key = str(raw).strip()
    key = BAND_ALIASES.get(key, key)
    for b in BANDS:
        if b["key"] == key:
            return b
    # 兼容纯标签传入（"50以内" / "50-100" / "100+"）
    for b in BANDS:
        if b["label"] == key:
            return b
    return None


# ---------------------------------------------------------------- 投前确认
# 骰子模式必须先把「不可回退的决策」问清楚，再掷。
# 理由：骰子一旦掷出，用户看到的是「结果」而不是「选项」——
#       此时再说"其实我不吃辣/我要外送"，整轮就白掷了。
#       所以这些槽位必须在投掷【之前】确认，缺一不可。

CONFIRM_SLOTS = [
    {
        "key": "people", "name": "人数", "required": True,
        "ask": "几个人吃？",
        "why": "决定供餐量与投掷次数（一份四人餐只投 1 次，四份单人要投 4 次）",
    },
    {
        "key": "band", "name": "预算档", "required": True,
        "ask": "总预算档：50以内 / 50-100 / 100+？（总价，不是人均）",
        "why": "决定候选池价格区间；选错档会直接超预算或选不到",
    },
    {
        "key": "restrictions", "name": "忌口", "required": True,
        "ask": "有忌口吗？不吃辣 / 忌口项 / 无",
        "why": "建池阶段过滤，掷完再提无法补救（骰子不可能roll出违规项，但池子会变）",
    },
    {
        "key": "channel", "name": "取餐方式", "required": True,
        "ask": "到店自取 / 麦乐送 / 得来速？",
        "why": "到店与外送是两套 productCode 体系，选错编码下单报 60006 已售罄",
    },
    {
        "key": "storeCode", "name": "门店", "required": True,
        "ask": "哪家门店？（外送需先查可送门店拿 beCode）",
        "why": "菜单随门店与营业时段变化，必须绑定具体门店",
    },
    {
        "key": "useCoupon", "name": "是否用券", "required": False,
        "ask": "要用优惠券吗？（一次只能用一张）",
        "why": "影响最终净价，但不影响骰子选餐结果",
    },
]

CHANNEL_MATRIX = {
    "到店自取": {"beType": 1, "orderType": 1, "beCodeNeeded": False,
                 "takeWayCode": "eat-in"},
    "外送": {"beType": 2, "orderType": 2, "beCodeNeeded": True, "takeWayCode": None},
    "麦乐送": {"beType": 2, "orderType": 2, "beCodeNeeded": True, "takeWayCode": None},
    "得来速": {"beType": 5, "orderType": 1, "beCodeNeeded": True,
               "takeWayCode": "take-dt-quick"},
}

# ---------------------------------------------------------------- 默认值
# 用户约定（2026-10-24）：
#   有默认值 → 直接用默认值，不再重复问
#   无默认值 → 5 项全问
#   付款前   → 无论有没有默认值，都必须再确认一次
#
# 哪些项可以存默认值：
#   可默认：门店、取餐方式、忌口、是否用券  ← 相对稳定
#   不默认：人数、预算档                    ← 每次都变，且是核心决策
#
# ⚠️ 忌口虽有默认值，确认卡必须【显式展示】——
#    用户某天想吃辣却没看到默认的"不吃辣"，就会误过滤。展示即视为已知会。

DEFAULTS_KEYS = ["storeCode", "storeName", "channel", "restrictions", "useCoupon"]
NEVER_DEFAULT_KEYS = ["people", "band"]

DEFAULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "defaults.json")


def load_defaults(path: Optional[str] = None) -> dict:
    """读默认值。文件不存在返回空 dict（不是错误）。"""
    p = path or DEFAULTS_PATH
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_defaults(values: dict, path: Optional[str] = None) -> str:
    """
    写默认值。只保留 DEFAULTS_KEYS 中有效项。

    ⚠️ False 是有效值（"不用券"是明确选择），不能当空值过滤掉。
    """
    p = path or DEFAULTS_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cur = load_defaults(p)
    for k in DEFAULTS_KEYS:
        if k not in values:
            continue
        v = values[k]
        if v is None or v == "" or v == [] or v == ():
            continue
        cur[k] = v
    cur["updatedAt"] = __import__("datetime").datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    return p


def clear_defaults(path: Optional[str] = None) -> str:
    p = path or DEFAULTS_PATH
    if os.path.exists(p):
        os.remove(p)
    return p



def normalize_channel(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    key = str(raw).strip()
    for k, v in CHANNEL_MATRIX.items():
        if k in key or key in k:
            out = dict(v)
            out["label"] = k
            return out
    return None


def build_confirm_card(people=None, band=None, restrictions=None,
                       channel=None, store_code=None, use_coupon=None,
                       store_name=None, defaults: Optional[dict] = None,
                       use_defaults: bool = True) -> dict:
    """
    生成投前确认卡。

    返回 {"ready", "missing", "card", "questions", "fromDefaults", ...}

    ★ 默认值规则（用户约定 2026-10-24）：
      - 有默认值 → 直接用，不再重复问（但会在卡上显式展示）
      - 无默认值 → 列入 missing，逐条问
      - 人数 / 预算档【永不使用默认值】—— 每次都变且是核心决策
      - 显式传入的值优先于默认值（用户临时改条件即可覆盖）

    ready=False 时**不允许投掷**。
    """
    d = (defaults or {}) if use_defaults else {}
    explicit = {
        "people": people,
        "band": band,
        "restrictions": restrictions,
        "channel": channel,
        "storeCode": store_code,
        "useCoupon": use_coupon,
    }
    # 默认值映射（storeName 跟随 storeCode）
    dmap = {
        "people": None, "band": None,
        "restrictions": d.get("restrictions"),
        "channel": d.get("channel"),
        "storeCode": d.get("storeCode"),
        "useCoupon": d.get("useCoupon"),
    }
    if not store_name and d.get("storeName"):
        store_name = d.get("storeName")

    values = {}
    sources = {}

    def _has(v) -> bool:
        """是否算"已填写"。⚠️ False 是有效值（明确的"不用券"）。"""
        return v is not None and v != "" and v != [] and v != ()

    for key, val in explicit.items():
        if _has(val):
            values[key] = val
            sources[key] = "user"
            continue
        if key == "restrictions" and isinstance(val, list):
            values[key] = val
            sources[key] = "user"
            continue
        if key in NEVER_DEFAULT_KEYS:
            values[key] = None
            sources[key] = "missing"
            continue
        dv = dmap.get(key)
        if _has(dv):
            values[key] = dv
            sources[key] = "default"
        else:
            values[key] = None
            sources[key] = "missing"

    ch = normalize_channel(values.get("channel"))
    # 预算档归一化为展示标签（under50 -> 50以内）
    if values.get("band"):
        nb = normalize_band(values["band"])
        if nb:
            values["band"] = nb["label"]
    missing = []
    card = []
    for slot in CONFIRM_SLOTS:
        key = slot["key"]
        v = values.get(key)
        filled = sources.get(key) in ("user", "default")
        if slot["required"] and not filled:
            missing.append(slot)
        card.append({
            "key": key, "name": slot["name"],
            "value": v if filled else None,
            "filled": filled,
            "source": sources.get(key, "missing"),
            "required": slot["required"],
            "ask": slot["ask"],
            "why": slot["why"],
        })

    ready = not missing
    warn = []
    if ch and ch["beCodeNeeded"]:
        warn.append("%s场景必须用 delivery-query-stores 返回的 beCode（不能自己拼，"
                    "否则报 60002）" % ch["label"])
    if ready and ch and ch["beCodeNeeded"] and not values.get("storeCode"):
        warn.append("缺少门店，无法取 beCode")

    from_defaults = [c["name"] for c in card if c["source"] == "default"]
    return {
        "ready": ready,
        "missing": [m["key"] for m in missing],
        "card": card,
        "questions": ["%s：%s" % (m["name"], m["ask"]) for m in missing],
        "channel": ch,
        "warnings": warn,
        "storeName": store_name,
        "fromDefaults": from_defaults,
        "usedDefaults": bool(from_defaults),
        "askCount": len(missing),
    }


def infer_channel_from_label(label: str):
    return normalize_channel(label)



# ---------------------------------------------------------------- 三骰阶梯
def _strength_key(t) -> tuple:
    """
    强度键：三骰 (a,b,c) 的「豪华度」排序键。
    主键 = 总和点数（保留「点数大 = 吃得好」直觉）
    次键 = 最大骰 / 中位骰 / 最小骰 → 同和的多种排列被稳定排开
    """
    a, b, c = t
    return (a + b + c, max(a, b, c), sorted((a, b, c))[1], min(a, b, c))


ALL_TRIPLES = tuple(sorted(itertools.product(range(1, 7), repeat=3),
                           key=_strength_key))
TRIPLE_RANK = {t: i for i, t in enumerate(ALL_TRIPLES)}
N_ATOMS = len(ALL_TRIPLES)          # 216

STRUCTURE_LABELS = {
    "豹子": ("幸运三连", True),     # 名称, 是否给免费重投
    "顺子": ("顺水一局", True),
    "对子": ("双拼日", False),
    "散牌": ("日常局", False),
}


def structure_of(t) -> str:
    """骰面结构分类：豹子 / 对子 / 顺子 / 散牌。"""
    s = sorted(t)
    if s[0] == s[2]:
        return "豹子"
    if s[0] == s[1] or s[1] == s[2]:
        return "对子"
    if s[2] - s[0] == 2 and len(set(s)) == 3:
        return "顺子"
    return "散牌"


def triple_info(t) -> dict:
    label, reroll = STRUCTURE_LABELS[structure_of(t)]
    return {
        "dice": list(t),
        "sum": sum(t),
        "structure": structure_of(t),
        "label": label,
        "rerollToken": reroll,
    }


# ---------------------------------------------------------------- 价格口径
# ⚠️ 2026-10-24 实测踩到的严重坑：菜单 currentPrice 不一定是实付价。
#
# 例：门店 1450056「不素之霸双层牛堡四件套」
#     currentPrice = 32.0   ← 这是「随单购麦金卡优惠」价
#     originalPrice = 58.5  ← 真实原价
#     实际 calculate-price（不传 withOrder）= 5850 分 = 58.5 元
#   → 若按 currentPrice 判断预算，用户选「50以内」档会实付 58.5 元，**直接超支**。
#
# 全量核对（1450056）：48 个正餐类里 15 个（31%）是麦金卡优惠价，
# 现价与原价相差近一倍；**23 个商品跨预算档**。
#
# 结论：预算判断必须用【实付价】= originalPrice（缺省回退 currentPrice）。
#       currentPrice 只作「有会员可省」的参考展示，不参与合规判断。


def prices_of(item: dict) -> dict:
    """
    解析一个菜单项的价格口径。

    ★ 正确规则（2026-10-24 用 calculate-price 逐项核对得出）：

      | 情况 | 实付价 | 依据 |
      |---|---|---|
      | 无 discountType | **currentPrice** | 实算 == currentPrice（5/5 验证） |
      | 有 discountType（如「随单购麦金卡优惠」）| **originalPrice** | 实算 == originalPrice（58.5 验证） |

    为什么：discountType 表示「这个现价有附加条件」（需麦金卡/随单购），
    不满足条件时按原价收。若按 currentPrice 判断预算，会实付近两倍。

    ⚠️ 不能一律用 originalPrice —— 无 discountType 时 originalPrice 只是
       虚高划线价（如大堡口福三件套 现价 22.9 / 原价 47，实算 22.9），
       一律取原价会过度保守，把能选的餐都排掉。

    返回 {pay, listPrice, memberPrice, hasDiscount, discountType}
    """
    try:
        cur = float(item.get("currentPrice") or 0)
    except (TypeError, ValueError):
        cur = 0.0
    try:
        orig = float(item.get("originalPrice") or 0)
    except (TypeError, ValueError):
        orig = 0.0
    if orig <= 0:
        orig = cur
    if cur <= 0:
        cur = orig

    dt = item.get("discountType")
    if dt:
        # 有附加条件的优惠价 → 按原价判断预算（保守，绝不超支）
        pay = orig
    else:
        pay = cur
    has_disc = bool(dt) and orig > cur > 0
    return {
        "pay": pay,
        "listPrice": orig,
        "memberPrice": cur if has_disc else None,
        "hasDiscount": has_disc,
        "discountType": dt if has_disc else None,
        "conditionalDiscount": bool(dt),
    }


# ---------------------------------------------------------------- 建池
def _scan_pool(meals: dict, people: int, band: dict, restrictions: list,
               cap: float, serves_map: Optional[dict]) -> tuple:
    """
    按给定单份价格上限扫描候选。
    返回 (pool, degraded)。degraded=True 表示已降级为「N 份单人餐组合」。
    """
    no_spicy = any("辣" in r or "spicy" in r.lower() for r in (restrictions or []))
    lo = band["lo"]
    pool = []
    singles = []

    for code, v in meals.items():
        name = v.get("name", "")
        # ⚠️ 预算判断用【实付价】，不是 currentPrice（后者可能是麦金卡优惠价）
        pr = prices_of(v)
        price = pr["pay"]
        if not any(k in name for k in MAIN_KEYWORDS):
            continue
        # ⚠️ 纯饮品不是一顿饭 —— 全局排除
        if is_drink_only(name):
            continue
        if no_spicy and is_spicy(name):
            continue
        # 供餐人数：权威优先，缺失才用名称推断
        if serves_map and code in serves_map and serves_map[code] > 0:
            s = int(serves_map[code])
        else:
            s = serves_of(name)
        if s == 1:
            singles.append({"code": code, "name": name, "price": price,
                            "memberPrice": pr["memberPrice"]})
        if s < people:
            continue
        if price < lo or price > cap:
            continue
        pool.append({
            "kind": "套餐", "code": code, "name": name,
            "price": price, "total": price, "serves": s,
            "perCapita": round(price / s, 2),
            "listPrice": pr["listPrice"],
            "memberPrice": pr["memberPrice"],
            "hasDiscount": pr["hasDiscount"],
            "discountType": pr["discountType"],
        })

    if pool:
        return pool, False

    # 组合兜底：N 份单人正餐，总价仍须落在预算档内
    for s in singles:
        if is_drink_only(s["name"]):
            continue
        total = round(s["price"] * people, 2)
        if total < lo or total > cap:
            continue
        pool.append({
            "kind": "组合", "code": s["code"], "name": s["name"],
            "price": s["price"], "total": total, "serves": 1,
            "perCapita": s["price"],
            "memberPrice": s.get("memberPrice"),
            "note": "%d 份 %s" % (people, s["name"][:16]),
        })
    return pool, True


def decide_roll_count(pool: list, people: int) -> int:
    """
    决定要投几次骰子。

    关键：投掷次数由「需要几份」决定，不是「几个人」。
    一份四人套餐能喂饱四个人 → 投 1 次；
    只有双人套餐 → 投 2 次；全是单人份 → 投 N 次。
    """
    if not pool:
        return people
    if all(p.get("kind") == "组合" for p in pool):
        return 1
    max_serves = max(p.get("serves", 1) for p in pool)
    if max_serves <= 1:
        return people
    return max(1, -(-people // max_serves))


def build_pool(meals: dict, people: int, band: dict, restrictions: list,
               serves_map: Optional[dict] = None) -> tuple:
    """
    构造合规候选池（含预算安全收紧）。

    两阶段：
      1. 宽扫（单份上限 = 档上限）→ 定投掷次数
      2. 若需投多次，把单份上限收紧为「档上限 / 投掷次数」重建池，
         使任意组合的【合计】必然落在档内。收紧后投次可能变化，迭代至稳定。

    若建不出单套餐池，降级为「N 份单人餐组合」。
    返回 (pool, degraded)
    """
    hi = band["hi"]
    pool, degraded = _scan_pool(meals, people, band, restrictions, hi, serves_map)
    if not pool:
        return pool, degraded

    if hi < 10 ** 9:
        rolls = decide_roll_count(pool, people)
        for _ in range(3):
            if rolls <= 1:
                break
            tight, deg2 = _scan_pool(meals, people, band, restrictions,
                                     hi / rolls, serves_map)
            if not tight:
                break
            new_rolls = decide_roll_count(tight, people)
            pool, degraded = tight, deg2
            if new_rolls == rolls:
                break
            rolls = new_rolls
    return pool, degraded


# ---------------------------------------------------------------- 投掷
def _segment(srt: list, lo: int, hi: int) -> list:
    """价格排序池切段 [lo,hi)，段内至少一个候选（边界重合时向右找有货段）。"""
    n = len(srt)
    if n <= 1:
        return srt
    bounds = [round(i * n / hi) for i in range(hi + 1)]
    a, b = bounds[lo], bounds[lo + 1]
    if b <= a:
        for k in range(lo, hi):
            aa, bb = bounds[k], bounds[k + 1]
            if bb > aa:
                return srt[aa:bb]
        return srt
    return srt[a:b]


def roll_single(pool: list, rng: random.Random, face: Optional[int] = None) -> dict:
    """单骰 6 段映射（v1 模式，保留兼容）。"""
    if not pool:
        return None
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    f = face if face is not None else rng.randint(1, 6)
    if n <= 6:
        return srt[min(int((f - 1) * n / 6), n - 1)]
    seg = _segment(srt, f - 1, 6)
    return rng.choice(seg) if seg else srt[0]


def roll_triple(pool: list, triple: tuple) -> dict:
    """
    三骰 216 级强度阶梯映射（v2 默认模式）。

    确定性：同一组骰面 → 必然同一个候选（可复现、可分享、可反查）。
    """
    if not pool:
        return None
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    r = TRIPLE_RANK[tuple(triple)]
    idx = min(int(r * n / N_ATOMS), n - 1)
    return srt[idx]


# ---------------------------------------------------------------- 主流程
def roll_food(meals: dict, people: int, band_raw: str, restrictions: list,
              faces: Optional[list] = None, seed: Optional[int] = None,
              dice_mode: str = "triple", serves_map: Optional[dict] = None,
              triples: Optional[list] = None,
              channel: Optional[str] = None, store_code: Optional[str] = None,
              use_coupon=None, require_confirm: bool = True,
              defaults: Optional[dict] = None,
              use_defaults: bool = True) -> dict:
    """
    完整投掷流程。

    faces:    单骰模式指定点数序列（1-6）
    triples:  三骰模式指定骰面序列，每项为 [a,b,c]

    require_confirm=True（默认）时，会先做投前确认校验：
      人数 / 预算档 / 忌口 / 取餐方式 / 门店 五项缺一不可。
    **有默认值（门店/渠道/忌口/用券）时自动沿用，只需人数与预算档。**
    缺项直接返回 ok=False，error="need_confirm"，**不投掷**。
    这是刻意设计：骰子掷出后用户看到的是结果而非选项，无可回退余地。
    确需跳过（脚本自检、离线演示）可显式传 require_confirm=False。
    """
    _defaults = defaults if defaults is not None else (
        load_defaults() if use_defaults else {})
    card = build_confirm_card(people=people, band=band_raw,
                              restrictions=restrictions,
                              channel=channel, store_code=store_code,
                              use_coupon=use_coupon,
                              defaults=_defaults, use_defaults=use_defaults)
    if require_confirm and not card["ready"]:
        return {
            "ok": False,
            "error": "need_confirm",
            "message": "投掷前需要先确认：%s" % "、".join(card["missing"]),
            "missing": card["missing"],
            "confirmCard": card,
            "questions": card["questions"],
            "rolled": False,
        }

    # 用确认卡解析后的值（可能来自默认值）
    cvals = {c["key"]: c["value"] for c in card["card"]}
    if cvals.get("restrictions") is not None:
        restrictions = cvals["restrictions"]
    if cvals.get("channel"):
        channel = cvals["channel"]
    if cvals.get("storeCode"):
        store_code = cvals["storeCode"]
    if cvals.get("useCoupon") is not None:
        use_coupon = cvals["useCoupon"]

    band = normalize_band(band_raw)
    if not band:
        return {"ok": False, "error": "未知预算档 %r，可选：%s"
                % (band_raw, "/".join(b["label"] for b in BANDS))}

    pool, degraded = build_pool(meals, people, band, restrictions, serves_map)
    if not pool:
        return {
            "ok": False, "error": "no_solution",
            "message": "%d 人 + 预算「%s」+ 忌口[%s] 在当前菜单下无合规套餐"
                       % (people, band["label"], ",".join(restrictions or []) or "无"),
            "band": band, "people": people,
        }

    if seed is not None:
        random.seed(seed)
    rng = random.Random(seed) if seed is not None else random

    # ---- 投掷次数 = 需要几「份」，不是几个人 ----
    rolls_needed = decide_roll_count(pool, people)

    picks = []
    used = set()
    labels = []
    tokens = []

    if dice_mode == "triple":
        for i in range(rolls_needed):
            if triples and i < len(triples):
                t = tuple(int(x) for x in triples[i])
            else:
                t = tuple(rng.randint(1, 6) for _ in range(3))
            info = triple_info(t)
            labels.append(info)
            if info["rerollToken"]:
                tokens.append(info["label"])
            item = None
            for _try in range(8):
                cand = roll_triple(pool, t)
                if cand is None:
                    break
                if cand["code"] not in used or len(pool) == 1:
                    item = cand
                    break
            if item is None:
                item = roll_triple(pool, t)
            if item:
                used.add(item["code"])
                contribution = (item["total"] if item["kind"] == "组合"
                                else item["price"])
                serves = (people if item["kind"] == "组合"
                          else item.get("serves", 1))
                picks.append({"dice": list(t), "sum": sum(t),
                              "structure": info["structure"],
                              "label": info["label"],
                              **item,
                              "contribution": contribution,
                              "servesThis": serves})
    else:
        faces = faces or [rng.randint(1, 6) for _ in range(rolls_needed)]
        faces = list(faces[:rolls_needed])
        while len(faces) < rolls_needed:
            faces.append(rng.randint(1, 6))
        for f in faces:
            item = None
            for _try in range(8):
                cand = roll_single(pool, rng, f)
                if cand is None:
                    break
                if cand["code"] not in used or len(pool) == 1:
                    item = cand
                    break
            if item is None:
                item = roll_single(pool, rng, f)
            if item:
                used.add(item["code"])
                contribution = (item["total"] if item["kind"] == "组合"
                                else item["price"])
                serves = (people if item["kind"] == "组合"
                          else item.get("serves", 1))
                picks.append({"face": f, **item,
                              "contribution": contribution,
                              "servesThis": serves})

    total = sum(p["contribution"] for p in picks)

    # 供餐量校验（组合类本身即 N 份打包）
    serves_total = sum(p.get("servesThis", 1) for p in picks)
    if picks and all(p.get("kind") == "组合" for p in picks):
        serves_total = people

    result = {
        "ok": True,
        "mode": dice_mode,
        "band": {"key": band["key"], "label": band["label"],
                 "lo": band["lo"], "hi": band["hi"]},
        "people": people,
        "restrictions": restrictions or [],
        "degraded": degraded,
        "poolSize": len(pool),
        "rolls": len(picks),
        "picks": picks,
        "servesTotal": serves_total,
        "total": round(total, 2),
        "perCapita": round(total / people, 2) if people else 0,
        "note": ("该预算档下没有供 %d 人的单套餐，已降级为「多份单人餐组合」"
                 % people) if degraded else "",
        "confirmCard": card,
        # 直接可交下一环节的上下文（算价 / 下单）
        "orderContext": {
            "storeCode": store_code,
            "channel": (normalize_channel(channel) or {}).get("label"),
            "beType": (normalize_channel(channel) or {}).get("beType"),
            "orderType": (normalize_channel(channel) or {}).get("orderType"),
            "takeWayCode": (normalize_channel(channel) or {}).get("takeWayCode"),
            "beCodeNeeded": (normalize_channel(channel) or {}).get("beCodeNeeded"),
            "people": people,
            "band": band["label"],
            "restrictions": restrictions or [],
        },
    }
    if dice_mode == "triple":
        result["faces"] = [p.get("dice") for p in picks]
        result["sums"] = [p.get("sum") for p in picks]
        result["structures"] = [p.get("structure") for p in picks]
        result["labels"] = labels
        result["rerollTokens"] = tokens
        result["rerollAvailable"] = len(tokens) > 0
    else:
        result["faces"] = [p.get("face") for p in picks]
    return result


# ---------------------------------------------------------------- CLI
def _fmt_value(key: str, v):
    """把槽位值渲染成人能读的文字。"""
    if key == "useCoupon":
        if v is True:
            return "要用"
        if v is False:
            return "不用"
        return "-"
    if isinstance(v, list):
        return "、".join(v) if v else "无"
    if key == "restrictions":
        return v or "无"
    return v if v is not None else "-"


def print_confirm_card(card: dict) -> None:
    """打印投前确认卡（标注哪些项来自默认值）。"""
    print("📋 投前确认")
    print("  " + "-" * 56)
    for item in card["card"]:
        if item["filled"]:
            src = "  (默认)" if item["source"] == "default" else ""
            print("  ✓ %-8s %s%s"
                  % (item["name"], _fmt_value(item["key"], item["value"]), src))
        else:
            flag = "必填" if item["required"] else "选填"
            print("  ○ %-8s —— %s：%s" % (item["name"], flag, item["ask"]))
    print("  " + "-" * 56)
    if card["storeName"]:
        print("  门店：%s" % card["storeName"])
    for w in card.get("warnings", []):
        print("  ⚠️  %s" % w)
    if card["ready"]:
        if card.get("usedDefaults"):
            print("  状态：信息完整，可以投掷 ✓（沿用默认：%s）"
                  % "、".join(card["fromDefaults"]))
        else:
            print("  状态：信息完整，可以投掷 ✓")
    else:
        print("  状态：缺少 %s，**暂不投掷**" % "、".join(
            i["name"] for i in card["card"] if not i["filled"] and i["required"]))
        print()
        print("  需要先问用户（%d 项）：" % len(card["questions"]))
        for q in card["questions"]:
            print("    · %s" % q)
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="骰子选餐引擎")
    ap.add_argument("--menu", required=True, help="菜单 JSON（query-meals 输出）")
    ap.add_argument("--people", type=int, help="人数（每次都问，无默认值）")
    ap.add_argument("--band", help="预算档：50以内 / 50-100 / 100+（每次都问）")
    ap.add_argument("--restriction", nargs="*", default=None,
                    help="忌口，如 不吃辣；显式传空表示「无」")
    ap.add_argument("--channel", help="取餐方式：到店自取 / 麦乐送 / 得来速")
    ap.add_argument("--store", help="门店编码")
    ap.add_argument("--store-name", help="门店名称（仅展示）")
    ap.add_argument("--coupon", choices=["yes", "no"], help="是否用券（选填）")
    ap.add_argument("--no-defaults", action="store_true",
                    help="忽略已保存的默认值（全部重新确认）")
    ap.add_argument("--remember", action="store_true",
                    help="把本次的门店/渠道/忌口/用券存为默认值")
    ap.add_argument("--forget-defaults", action="store_true",
                    help="清除已保存的默认值")
    ap.add_argument("--show-defaults", action="store_true",
                    help="显示当前默认值并退出")
    ap.add_argument("--confirm-only", action="store_true",
                    help="只输出投前确认卡，不投掷")
    ap.add_argument("--skip-confirm", action="store_true",
                    help="跳过投前确认（仅限脚本自检/离线演示）")
    ap.add_argument("--mode", default="triple", choices=["triple", "single"],
                    help="骰子模式：triple=三骰216级（默认）/ single=单骰6段")
    ap.add_argument("--faces", nargs="*", type=int, help="指定单骰点数（1-6）")
    ap.add_argument("--triples", nargs="*", help="指定三骰骰面，如 653 441")
    ap.add_argument("--serves-map", help="权威供餐人数映射 JSON（serves_map.json）")
    ap.add_argument("--seed", type=int, help="随机种子（可复现）")
    ap.add_argument("--simulate", type=int, default=0, help="模拟次数（自检用）")
    args = ap.parse_args()

    meals = meals_of(load_json(args.menu))
    serves_map = None
    if args.serves_map and os.path.exists(args.serves_map):
        serves_map = load_json(args.serves_map)

    triples = None
    if args.triples:
        triples = []
        for t in args.triples:
            t = t.strip()
            triples.append([int(c) for c in t] if len(t) == 3 else None)
        triples = [t for t in triples if t]

    if args.simulate:
        import collections
        stats = collections.Counter()
        util = []
        viol = 0
        rng = random.Random(12345)
        for _ in range(args.simulate):
            people = rng.choice([1, 1, 2, 2, 3, 4])
            band = rng.choice(BANDS)
            restr = ["不吃辣"] if rng.random() < 0.7 else []
            r = roll_food(meals, people, band["key"], restr,
                          dice_mode=args.mode, serves_map=serves_map,
                          require_confirm=False)
            if not r["ok"]:
                stats["无解"] += 1
                continue
            stats["有解"] += 1
            cap = r["band"]["hi"] if r["band"]["hi"] < 10 ** 9 else r["total"]
            util.append(r["total"] / cap if cap else 0)
            if r["total"] > r["band"]["hi"] and r["band"]["hi"] < 10 ** 9:
                stats["超预算"] += 1
            if r.get("servesTotal", 0) < people:
                stats["供餐不足"] += 1
            for p in r["picks"]:
                if "辣" in p["name"] and any("辣" in x for x in restr):
                    viol += 1
                if is_drink_only(p["name"]):
                    stats["含饮品"] += 1
        n = stats["有解"] + stats["无解"]
        print("模拟 %d 次（模式 %s）" % (n, args.mode))
        print("  有解率   : %.1f%%" % (stats["有解"] * 100.0 / max(n, 1)))
        print("  超预算   : %d" % stats["超预算"])
        print("  忌口违例 : %d" % viol)
        print("  供餐不足 : %d" % stats["供餐不足"])
        print("  含饮品   : %d" % stats["含饮品"])
        if util:
            print("  预算利用 : %.1f%%" % (sum(util) / len(util) * 100))
        ok = (stats["无解"] == 0 and stats["超预算"] == 0 and viol == 0
              and stats["供餐不足"] == 0 and stats["含饮品"] == 0)
        return 0 if ok else 1

    if args.show_defaults:
        d = load_defaults()
        if not d:
            print("（暂无默认值，首次使用会询问全部 5 项）")
        else:
            print("当前默认值（%s）" % d.get("updatedAt", "-"))
            for k in DEFAULTS_KEYS:
                if k in d:
                    print("  %-14s %s" % (k, d[k]))
            print()
            print("人数 / 预算档 不设默认值，每次都问。")
        return 0

    if args.forget_defaults:
        p = clear_defaults()
        print("已清除默认值：%s" % p)
        return 0

    restrictions = args.restriction
    # 明确传了空 -> 表示"无忌口"，否则视为未确认
    if restrictions is not None and len(restrictions) == 0:
        restrictions = []

    use_defaults = not args.no_defaults
    card = build_confirm_card(
        people=args.people, band=args.band, restrictions=restrictions,
        channel=args.channel, store_code=args.store,
        use_coupon=(None if not args.coupon else args.coupon == "yes"),
        store_name=args.store_name,
        defaults=load_defaults() if use_defaults else {},
        use_defaults=use_defaults)

    if args.confirm_only:
        print_confirm_card(card)
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return 0 if card["ready"] else 3

    if not args.skip_confirm and not card["ready"]:
        print_confirm_card(card)
        print(json.dumps({
            "ok": False, "error": "need_confirm", "rolled": False,
            "missing": card["missing"], "questions": card["questions"],
        }, ensure_ascii=False, indent=2))
        return 3

    print_confirm_card(card)

    r = roll_food(meals, args.people, args.band, restrictions,
                  faces=args.faces, seed=args.seed, dice_mode=args.mode,
                  serves_map=serves_map, triples=triples,
                  channel=args.channel, store_code=args.store,
                  use_coupon=(None if not args.coupon else args.coupon == "yes"),
                  require_confirm=False,
                  defaults=load_defaults() if use_defaults else {},
                  use_defaults=use_defaults)
    if not r["ok"]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 1

    # 记住本次信息为默认值（只存门店/渠道/忌口/用券）
    if args.remember:
        cc = {c["key"]: c["value"] for c in card["card"]}
        saved = save_defaults({
            "storeCode": cc.get("storeCode"),
            "storeName": args.store_name or card.get("storeName"),
            "channel": cc.get("channel"),
            "restrictions": cc.get("restrictions"),
            "useCoupon": cc.get("useCoupon"),
        })
        r["defaultsSaved"] = saved

    if args.mode == "triple":
        print("🎲 三骰结果：%s" % "  ".join(
            "【%d-%d-%d】=%d点·%s" % (d[0], d[1], d[2], sum(d), l["label"])
            for d, l in zip(r["faces"], r["labels"])))
    else:
        print("🎲 骰子结果：%s" % "  ".join("【%d】" % f for f in r["faces"]))
    print("   预算档：%s   人数：%d   候选池：%d 个%s"
          % (r["band"]["label"], r["people"], r["poolSize"],
             "（已降级为组合）" if r["degraded"] else ""))
    print()
    for p in r["picks"]:
        extra = "  ← %s" % p["note"] if p.get("note") else ""
        tag = "  [%s]" % p["label"] if p.get("label") else ""
        if args.mode == "triple":
            print("   %d点·%s → %-28s %5.1f 元%s%s"
                  % (p["sum"], p["structure"], p["name"][:26],
                     p.get("contribution", p["total"]), tag, extra))
        else:
            print("   %d 点 → %-28s %5.1f 元%s"
                  % (p["face"], p["name"][:26],
                     p.get("contribution", p["total"]), extra))
    print()
    print("   合计 %.1f 元   人均 %.1f 元" % (r["total"], r["perCapita"]))
    if r.get("rerollAvailable"):
        print("   🎁 触发「%s」→ 可免费重投一次" % "、".join(r["rerollTokens"]))
    if r["note"]:
        print("   ⚠️ " + r["note"])
    print()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
