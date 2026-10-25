#!/usr/bin/env python3
"""
麦当劳点餐搭配引擎。

职责：
1. 解析 query-meals 返回的菜单 + 套餐 round 结构
2. 按人数定位合适档位的套餐
3. 按忌口过滤商品，标记无法满足的项
4. 优惠券择优（一次仅一券，按净省最大选）
5. 人均预算校验

配合 SKILL.md 使用：模型负责从自然语言抽取槽位，本脚本负责确定性计算。

用法:
  python menu_helper.py candidates --menu menu.json --people 3 --budget 150
  python menu_helper.py coupons --menu menu.json --plan plan.json --coupons coupons.json
  python menu_helper.py nutrition --names "巨无霸,中薯条"

所有 JSON 文件均为 mcd_call.py 的原始输出。
"""

import argparse
import json
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- 商品编码别名
# 券绑定的 productCode 与菜单 productCode 不一致（实测：券绑 1440，菜单是 901440）。
# 同一商品两套编码，必须维护映射，否则会误判"券绑商品不在方案里"。

CODE_ALIASES = {
    "1440": "901440",    # 麦辣鸡腿汉堡
}

# 兜底别名：按名称反查编码
NAME_ALIASES = {
    "薯条": "501205",
    "中薯条": "501205",
    "大薯条": "501206",
    "小薯条": "501205",
}


def canon(code: str) -> str:
    """把券绑编码归一到菜单编码。"""
    return CODE_ALIASES.get(str(code), str(code))


# ---------------------------------------------------------------- 忌口规则库

# 辣度判定：以酱料/名称为依据（实测特调无法"去辣"）
SPICY_HINTS = ["辣椒黄油", "韩式甜辣", "麦辣", "辣味", "香辣", "变态辣"]
# 生菜类（可特调去掉）
HERB_HINTS = ["生菜", "香菜"]

# 纯素/可替代兜底（实测存在）
VEG_FALLBACK = {
    "521917": "泷愿成真麦旋风——大米风味",
    "904437": "甜香玉米杯",
    "904438": "甜香玉米杯(大)",
    "906102": "苹果片",
    "501205": "薯条",
    "501206": "大薯条",
    "904106": "香芋派",
    "904105": "菠萝派",
    "903755": "纯牛奶(盒装)",
    "510488": "燕麦奶",
    "902372": "奥利奥麦旋风",
    "902373": "草莓麦旋风",
    "902374": "朱古力新地",
    "902375": "草莓新地",
}

# 已知不辣款（实测）
NON_SPICY = {
    "901100": "巨无霸",
    "901106": "培根蔬萃双层牛堡",
    "901120": "双层吉士汉堡",
    "901010": "吉士汉堡包",
    "901600": "麦香鱼",
    "9900003589": "双层深海鳕鱼堡",
    "901450": "麦香鸡",
    "902060": "培根安格斯厚牛堡",
    "902061": "芝士安格斯厚牛堡",
}

# 素食兜底里唯一可当"正餐级"解释的（其余是甜品/小食，必须诚实标注）
VEG_MAIN_OK = "521917"

# 套餐人数档位（按名称识别，仅作辅助）
# ⚠️ 实测：名称里的"双人/四人"可能指"含几种汉堡"而非供餐人数。
#    例：「快乐吃鸡双人餐」饮料数=2（真2人份）、「大吉大利吃鸡双人餐」饮料数=2（真2人份）。
#    因此真实人数必须以 round 结构里的饮料数量为准，名称只作交叉验证。
MEAL_SIZE_HINTS = [
    (1, ["单人餐", "单人"]),
    (2, ["双人餐", "两人"]),
    (3, ["三人餐", "三人"]),
    (4, ["四人餐", "四人"]),
]

# 名称里带这些词但人数不固定的（如"双人餐"其实是2种汉堡）
SHARE_HINTS = ["分享餐", "全家桶", "欢享", "盛宴", "四人餐"]


def is_spicy(name: str) -> bool:
    return any(h in name for h in SPICY_HINTS)


def has_herb(name: str) -> bool:
    return any(h in name for h in HERB_HINTS)


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def meals_of(menu_doc) -> dict:
    """从 mcd_call.py 输出里取 meals 字典。"""
    return (menu_doc.get("data") or {}).get("meals") or {}


def categories_of(menu_doc) -> list:
    return (menu_doc.get("data") or {}).get("categories") or []


def price_of(meals: dict, code: str, default: float = 0.0) -> float:
    item = meals.get(str(code)) or {}
    raw = item.get("currentPrice")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def parse_diff_price(diff: str) -> float:
    """'+ ¥5' -> 5.0 ; '- ¥1' -> -1.0 ; '+ ¥0' -> 0.0"""
    if not diff:
        return 0.0
    m = re.search(r"[-+]\s*¥\s*([\d.]+)", str(diff))
    if not m:
        return 0.0
    val = float(m.group(1))
    return -val if "-" in str(diff).split("¥")[0] else val


def capacity_from_detail(detail_doc) -> int:
    """
    从 query-meal-detail 的 round 结构推断真实供餐人数。
    判据：饮料 round 中默认选项的 quantity（饮料几杯 = 几人份）。
    """
    dd = detail_doc.get("data") or {}
    drinks = 0
    for r in dd.get("rounds", []):
        if "饮料" in r.get("name", ""):
            for ch in r.get("choices", []):
                if ch.get("isDefault") == 1:
                    drinks = max(drinks, int(ch.get("quantity") or 0))
    return drinks


# ---------------------------------------------------------------- 人数定位

def detect_people_capacity(name: str) -> int:
    """从套餐名推测供几人份（仅作辅助，优先用 round 结构）。"""
    for size, hints in MEAL_SIZE_HINTS:
        for h in hints:
            if h in name:
                return size
    return 0


def pick_meal_for_people(meals: dict, people: int, details: dict = None) -> list:
    """
    按人数挑选候选套餐。
    details: {productCode: query-meal-detail 原始输出}，用于精确判定人数。
    返回按适配度排序的 (code, name, price, capacity) 列表。
    """
    cands = []
    for code, info in meals.items():
        name = info.get("name", "")
        if "餐" not in name:
            continue
        price = price_of(meals, code)
        if price <= 0:
            continue

        cap = 0
        if details and code in details:
            cap = capacity_from_detail(details[code])
        if not cap:
            cap = detect_people_capacity(name)

        cands.append((code, name, price, cap))

    def score(item):
        code, name, price, cap = item
        if cap <= 0:
            return (999, price)
        diff = abs(cap - people)
        # 同人数档优先；人数不够的套餐人均更划算，给轻微加权
        penalty = diff * 10
        if cap < people:
            penalty -= 2
        return (penalty, price)

    cands.sort(key=score)
    return cands


def compose_for_people(meals: dict, people: int, details: dict = None) -> list:
    """
    生成覆盖 N 人的套餐组合方案。
    优先用单个恰好 N 人的套餐；没有时拆成"大套餐 + 小套餐"组合。
    例：3 人无三人餐时 -> 双人餐 + 单人餐。
    """
    cands = pick_meal_for_people(meals, people, details)
    if not cands:
        return []

    exact = [c for c in cands if c[3] == people]
    if exact:
        best = min(exact, key=lambda x: x[2])
        return [{"type": "single", "items": [best], "total": best[2],
                 "serves": people, "perPerson": round(best[2] / people, 2)}]

    # 贪心：尽量用接近 people 的套餐覆盖，剩余用单人餐补
    combos = []
    for big in cands:
        if big[3] <= 0 or big[3] >= people:
            continue
        rest = people - big[3]
        singles = [c for c in cands if c[3] == 1]
        if not singles:
            continue
        # 剩余人数用单人餐补齐
        n_single = rest
        total = big[2] + singles[0][2] * n_single
        combos.append({
            "type": "combo",
            "items": [big] + [singles[0]] * n_single,
            "total": round(total, 2),
            "serves": big[3] + n_single,
            "perPerson": round(total / people, 2),
        })

    combos.sort(key=lambda c: c["total"])
    return combos[:5]


# ---------------------------------------------------------------- 忌口检查

def check_dietary(meals: dict, items: list, restrictions: list) -> dict:
    """
    检查方案是否满足忌口。
    items: [{"productCode","name","quantity"}]
    返回 {"satisfied": bool, "issues": [...], "notes": [...]}
    """
    issues = []
    notes = []
    names = [i.get("name", "") for i in items]

    for r in restrictions:
        r = r.lower()

        if any(k in r for k in ["素", "vegetarian", "vegan"]):
            has_meat = any(
                n and not is_veg_fallback(n)
                for n in names
            )
            if has_meat:
                issues.append({
                    "restriction": "吃素/素食",
                    "level": "partial",
                    "message": "麦当劳没有素食主餐，主食位无法满足素食需求",
                    "fallback": "可改用「单人餐 + 泷愿成真麦旋风(大米风味)」凑无荤正餐形态",
                })
            else:
                notes.append("素食：已全部换成纯素/无荤单品")

        if any(k in r for k in ["辣", "spicy"]):
            spicy = [n for n in names if is_spicy(n)]
            if spicy:
                issues.append({
                    "restriction": "不吃辣",
                    "level": "partial",
                    "message": f"辣味来自酱料本身，系统内无法完全去除；涉及：{'、'.join(spicy)}",
                    "fallback": "建议换成巨无霸 / 麦香鸡 / 板烧鸡腿堡等不辣款",
                })
            else:
                notes.append("不吃辣：已全部换成不辣款")

        if any(k in r for k in ["香菜", "生菜"]):
            herb = [n for n in names if has_herb(n)]
            if herb:
                notes.append(f"去香菜/生菜：涉及 {'、'.join(herb)}，可用特调去掉")

        if any(k in r for k in ["过敏", "allerg"]):
            issues.append({
                "restriction": "过敏",
                "level": "unmet",
                "message": "系统内无法标注过敏原，必须当面与门店确认",
                "fallback": "建议用户直接致电门店确认，或自行准备替代",
            })

        if any(k in r for k in ["无糖", "控糖", "diabet"]):
            notes.append("控糖：饮品优先换无糖可口可乐 / 纯牛奶")

        if any(k in r for k in ["低卡", "热量", "减肥", "减脂", "calorie"]):
            notes.append("控热量：参考 references/dietary.md 低卡表挑选")

    return {
        "satisfied": all(i["level"] != "unmet" for i in issues),
        "issues": issues,
        "notes": notes,
    }


def is_veg_fallback(name: str) -> bool:
    return any(v in name for v in VEG_FALLBACK.values())


# ---------------------------------------------------------------- 券择优

def parse_coupon_expiry(coupon: dict):
    """
    解析券的有效期，兼容两种结构：

    A) 门店券（query-store-coupons）：
       "tradeDateTime": "2026-10-19 10:30:00-2026-10-23 23:59:59"
    B) 卡包券（query-my-coupons）：
       "tradeStartDateTime": "2026-10-26 10:30:00"
       "tradeEndDateTime":   "2026-10-30 23:59:59"

    返回 (start_str, end_str)
    注意：日期本身含 '-',不能用 split('-')，需用正则匹配时间边界。
    """
    if not isinstance(coupon, dict):
        return (None, None)

    # 结构 B：卡包券
    start = coupon.get("tradeStartDateTime")
    end = coupon.get("tradeEndDateTime")
    if start and end:
        return (str(start).strip(), str(end).strip())

    # 结构 A：门店券
    trade_dt = coupon.get("tradeDateTime")
    if not trade_dt:
        return (None, None)
    s = str(trade_dt).strip()
    m = re.match(
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*-\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
        s,
    )
    if m:
        return (m.group(1), m.group(2))
    # 兜底：只有单个日期
    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    return (m2.group(1) if m2 else None, None)


def hours_until(expire_end: str, now: str = None) -> float:
    """计算券还有多少小时过期。now 格式 'YYYY-MM-DD HH:MM:SS'。"""
    if not expire_end:
        return None
    try:
        from datetime import datetime
        end = datetime.strptime(expire_end, "%Y-%m-%d %H:%M:%S")
        ref = datetime.now() if not now else datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
        return round((end - ref).total_seconds() / 3600, 2)
    except Exception:
        return None


def hours_since_start(trade_start: str, now: str = None) -> float:
    """距离券开始可用的时间（小时）。负数表示已开始可用。"""
    if not trade_start:
        return None
    try:
        from datetime import datetime
        st = datetime.strptime(trade_start, "%Y-%m-%d %H:%M:%S")
        ref = datetime.now() if not now else datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
        return round((st - ref).total_seconds() / 3600, 2)
    except Exception:
        return None


def coupon_state(trade_start: str, trade_end: str, now: str = None) -> dict:
    """
    判断券的可用状态。

    实测规则（2026-10-24 验证）：券按**周批次滚动**发放。
    例：10-22 领到的一批是 10-19~10-23（周一~周五），
    过期后服务端自动换成下一批 10-26~10-30（下一个完整工作周），
    标签写「未到使用时间」。所以周末领的券通常要等到下周一才能用。

    state: not_started | usable | expiring | expired
    """
    until_end = hours_until(trade_end, now)
    since_start = hours_since_start(trade_start, now)

    # 有效期未知 -> 无法判断，按"需确认"处理（不当作可用）
    if until_end is None and since_start is None:
        return {
            "state": "unknown",
            "label": "有效期未知",
            "detail": "接口未返回有效期，需人工确认",
            "hoursUntilStart": None,
            "hoursLeft": None,
        }

    if since_start is not None and since_start > 0:
        days = round(since_start / 24, 1)
        return {
            "state": "not_started",
            "label": "未到使用时间",
            "detail": f"需等到 {trade_start} 才能用（还有 {days} 天）",
            "hoursUntilStart": since_start,
            "hoursLeft": until_end,
        }
    if until_end is not None and until_end <= 0:
        return {
            "state": "expired",
            "label": "已过期",
            "detail": f"已于 {trade_end} 过期",
            "hoursUntilStart": since_start,
            "hoursLeft": until_end,
        }
    if until_end is not None and until_end < 24:
        return {
            "state": "expiring",
            "label": "即将过期",
            "detail": f"{trade_end} 到期，仅剩 {round(until_end, 1)} 小时",
            "hoursUntilStart": since_start,
            "hoursLeft": until_end,
        }
    return {
        "state": "usable",
        "label": "可用",
        "detail": f"有效至 {trade_end}",
        "hoursUntilStart": since_start,
        "hoursLeft": until_end,
    }


def choose_coupon(meals: dict, plan_items: list, coupons: list, now: str = None) -> dict:
    """
    券择优算法：
    对每张券计算净省 = 券抵扣额 - 加购成本，选净省最大者。
    一次只能用一张券（硬限制）。
    """
    if not coupons:
        return {"chosen": None, "reason": "当前门店没有可用优惠券", "candidates": []}

    in_plan = {canon(i.get("productCode")) for i in plan_items}
    results = []

    for c in coupons:
        title = c.get("title", "")
        # 从标题解析抵扣价，如 "19.9元王牌炸鸡任选2" -> 19.9
        m = re.search(r"([\d.]+)\s*元", title)
        face_value = float(m.group(1)) if m else 0.0

        bound = [p.get("productCode") for p in (c.get("products") or [])]
        bound_canon = [canon(b) for b in bound]

        add_cost = 0.0
        missing = []
        unknown_price = False
        for b, bc in zip(bound, bound_canon):
            if bc in in_plan:
                continue
            missing.append(b)
            # 绑定商品在菜单里查不到价格时，无法估算加购成本 -> 标记未知
            price = price_of(meals, bc, 0.0) or price_of(meals, b, 0.0)
            if price > 0:
                add_cost += price
            else:
                unknown_price = True

        net_save = face_value - add_cost
        start, end = parse_coupon_expiry(c)
        st = coupon_state(start, end, now)
        # 卡包券若没有绑定商品信息，无法判断是否需加购 -> 视为需人工确认
        no_binding_info = not bound and bool(face_value)
        if no_binding_info:
            unknown_price = True

        results.append({
            "title": title,
            "couponId": c.get("couponId") or c.get("id"),
            "couponCode": c.get("couponCode") or c.get("code"),
            "boundProducts": bound,
            "boundNames": [p.get("productName") for p in (c.get("products") or [])],
            "faceValue": face_value,
            "addCost": round(add_cost, 2),
            "netSave": round(net_save, 2),
            "missingProducts": missing,
            "unknownAddCost": unknown_price,
            "noBindingInfo": no_binding_info,
            # 只有真正在有效期内且未过期才能用
            "usable": (net_save > 0 and not unknown_price
                       and st["state"] in ("usable", "expiring")),
            "state": st["state"],
            "stateLabel": st["label"],
            "stateDetail": st["detail"],
            "expireStart": start,
            "expireEnd": end,
            "hoursLeft": st["hoursLeft"],
            "hoursUntilStart": st["hoursUntilStart"],
            "expiringSoon": st["state"] == "expiring",
            "notStarted": st["state"] == "not_started",
        })

    usable = [r for r in results if r["usable"]]
    usable.sort(key=lambda r: r["netSave"], reverse=True)

    if not usable:
        reasons = []
        if any(r["notStarted"] for r in results):
            reasons.append("卡包里的券尚未到使用时间（券按周批次滚动，需等到下周一）")
        if any(r["unknownAddCost"] for r in results):
            reasons.append("部分券的绑定商品加购成本无法估算，需人工确认")
        if any(r["netSave"] <= 0 for r in results if not r["notStarted"]):
            reasons.append("所有可用券的净省均不大于 0（加购成本高于抵扣额）")
        return {
            "chosen": None,
            "reason": "；".join(reasons) or "无可用券",
            "candidates": results,
        }

    best = usable[0]
    alts = [u for u in usable[1:] if best["netSave"] - u["netSave"] < 1.0]
    return {
        "chosen": best,
        "reason": f"净省最大：抵扣 {best['faceValue']} 元，加购成本 {best['addCost']} 元",
        "alternatives": alts,
        "candidates": results,
    }


# ---------------------------------------------------------------- 预算校验

def budget_check(price: float, people: int, budget: float = None) -> dict:
    per = round(price / people, 2) if people else 0
    out = {"total": round(price, 2), "perPerson": per}
    if budget:
        out["budget"] = budget
        out["withinBudget"] = price <= budget
        out["perPersonBudget"] = round(budget / people, 2) if people else None
        out["overBy"] = round(price - budget, 2) if price > budget else 0
    return out


# ---------------------------------------------------------------- 子命令

def cmd_candidates(args):
    menu = load_json(args.menu)
    meals = meals_of(menu)
    people = args.people

    # 可选：多个 detail 文件（目录或单文件），用于精确判定套餐人数
    details = {}
    if args.details:
        paths = []
        if os.path.isdir(args.details):
            for fn in sorted(os.listdir(args.details)):
                if fn.endswith(".json"):
                    paths.append(os.path.join(args.details, fn))
        else:
            paths.append(args.details)
        for p in paths:
            try:
                d = load_json(p)
                code = (d.get("data") or {}).get("code")
                if code:
                    details[str(code)] = d
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 跳过 {p}: {e}", file=sys.stderr)

    cands = pick_meal_for_people(meals, people, details)

    print(f"== {people} 人份候选套餐 ==", file=sys.stderr)
    out = []
    for code, name, price, cap in cands[:args.limit]:
        item = {"productCode": code, "name": name, "price": price, "serves": cap,
                "perPerson": round(price / cap, 2) if cap else None}
        out.append(item)
        cap_s = f"供{cap}人" if cap else "人数未知"
        per_s = f"人均{price/cap:.1f}" if cap else ""
        print(f"{code:12s} {name:26s} {price:>6} 元  {cap_s} {per_s}",
              file=sys.stderr)

    # 组合方案（覆盖 N 人的最优拆法）
    combos = compose_for_people(meals, people, details)
    print(f"\n== {people} 人份组合方案 ==", file=sys.stderr)
    for cb in combos:
        desc = " + ".join(f"{n}×{k}" for _, n, _, k in
                           [(i[0], i[1], i[2], 1) for i in cb["items"]])
        print(f"  {cb['type']:7s} {desc:40s} 合计 {cb['total']:>6} 元  人均 {cb['perPerson']}",
              file=sys.stderr)

    # 兜底单品（素食场景）
    veg = [{"productCode": c, "name": n,
            "price": price_of(meals, c, 0) or None}
           for c, n in VEG_FALLBACK.items() if c in meals]

    print(json.dumps({"candidates": out, "combos": combos, "vegFallback": veg},
                     ensure_ascii=False, indent=2))


def extract_plan_items(plan):
    """从方案文件里提取商品列表。兼容 dict / list 两种格式。"""
    if isinstance(plan, list):
        return plan
    if isinstance(plan, dict):
        for key in ("items", "productList"):
            val = plan.get(key)
            if isinstance(val, list) and val:
                return val
        # 只有单个商品对象
        if plan.get("productCode"):
            return [plan]
    return []


def extract_coupon_list(coupons):
    """从各种结构里提取券列表。兼容：
    - [ {...}, {...} ]                      纯数组
    - {"data": [ ... ]}                    门店券
    - {"data": {"coupons": [ ... ]}}       卡包券
    - {"coupons": [ ... ]}                 卡包券变体
    """
    if isinstance(coupons, list):
        return coupons
    if isinstance(coupons, dict):
        data = coupons.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            inner = data.get("coupons")
            if isinstance(inner, list):
                return inner
        for key in ("coupons", "list", "items"):
            val = coupons.get(key)
            if isinstance(val, list):
                return val
        # 单张券对象
        if coupons.get("title"):
            return [coupons]
    return []


def cmd_coupons(args):
    menu = load_json(args.menu)
    meals = meals_of(menu)
    plan = load_json(args.plan)
    coupons = extract_coupon_list(load_json(args.coupons))

    plan_items = extract_plan_items(plan)
    result = choose_coupon(meals, plan_items, coupons)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_check(args):
    menu = load_json(args.menu)
    meals = meals_of(menu)
    plan = load_json(args.plan)
    items = extract_plan_items(plan)
    result = check_dietary(meals, items, args.restriction or [])
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_nutrition(args):
    doc = load_json(args.nutrition) if args.nutrition else None
    if doc is None:
        print("需要 --nutrition 指向 list-nutrition-foods 的输出文件", file=sys.stderr)
        sys.exit(1)
    raw = doc.get("data") or ""
    rows = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("["):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        name = parts[0]
        try:
            kcal = float(parts[3])
        except (ValueError, IndexError):
            continue
        rows.append({"name": name, "kcal": kcal,
                     "protein": parts[4], "fat": parts[5],
                     "carbohydrate": parts[6] if len(parts) > 6 else None,
                     "sodium": parts[7] if len(parts) > 7 else None})

    if args.names:
        keys = [n.strip() for n in args.names.split(",")]
        rows = [r for r in rows if any(k in r["name"] for k in keys)]
    if args.max_kcal:
        rows = [r for r in rows if r["kcal"] <= args.max_kcal]
    rows.sort(key=lambda r: r["kcal"])
    print(json.dumps(rows[:args.limit], ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="麦当劳点餐搭配引擎")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("candidates", help="按人数挑候选套餐")
    p.add_argument("--menu", required=True)
    p.add_argument("--people", type=int, required=True)
    p.add_argument("--details", help="query-meal-detail 输出的目录或单文件，用于精确判定人数")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(func=cmd_candidates)

    p = sub.add_parser("coupons", help="优惠券择优")
    p.add_argument("--menu", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--coupons", required=True)
    p.set_defaults(func=cmd_coupons)

    p = sub.add_parser("check", help="忌口检查")
    p.add_argument("--menu", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--restriction", nargs="*", default=[])
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("nutrition", help="营养/热量查询")
    p.add_argument("--nutrition", required=True)
    p.add_argument("--names", help="按名称过滤，逗号分隔")
    p.add_argument("--max-kcal", type=float)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_nutrition)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
