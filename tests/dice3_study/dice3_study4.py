#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 4 —— 专项检验：多份投掷的【合计金额】是否突破预算上限。

背景：
  build_pool 按【单个候选总价 ∈ 预算档】过滤，
  但 4人/50-100 档需要投 2 次（池里最大 4 人份？需核对），
  两次选中的套餐【合计】可能远超档位上限。

  这是与骰子方案无关的**既存风险**，三骰方案同样会踩到，
  甚至因为 M216 偏向贵档而更容易踩。
"""
import json
import os
import random
import statistics
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/.workbuddy/skills/mcd-ordering/scripts"))
import dice_roll as DR  # noqa: E402
from dice3_study import ALL216, _segment  # noqa: E402
from dice3_study3 import roll_m6, roll_m16, roll_m216, METHODS, serves_ok  # noqa: E402

MENU = os.path.join(HERE, "menu_dinein.json")
IDX216 = {t: i for i, t in enumerate(ALL216)}


def e8_multi(meals, per=4000):
    print("=" * 82)
    print("E8  多份投掷的合计金额合规性（关键风险点）")
    print("=" * 82)
    print()
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            pool, deg = DR.build_pool(meals, people, DR.normalize_band(bk), ["不吃辣"])
            if not pool:
                continue
            band = DR.normalize_band(bk)
            rolls = DR.decide_roll_count(pool, people)
            cap = band["hi"]
            hi = band["hi"] < 10 ** 9
            if rolls <= 1:
                continue
            line = "  %d人/%-8s 池=%2d 需投%d次 上限=%s" % (
                people, bl, len(pool), rolls,
                ("%.0f元" % cap) if hi else "∞")
            for m, fn in METHODS:
                rng = random.Random(4242 + people)
                over = 0
                totals = []
                for _ in range(per):
                    tot = 0.0
                    used = set()
                    for _k in range(rolls):
                        p, f = fn(pool, rng)
                        if p["code"] in used and len(pool) > 1:
                            p2, f = fn(pool, rng)
                            p = p2
                        used.add(p["code"])
                        tot += p["total"]
                    totals.append(tot)
                    if hi and tot > cap:
                        over += 1
                line += "  | %s 越界 %5.1f%% 均值%.0f元" % (
                    m, over * 100.0 / per, statistics.mean(totals))
            print(line)
    print()


def e9_budget_safe(meals, per=6000):
    """
    修复方案验证：把「预算上限」约束下沉到【投掷次数 × 单份上限】。
    即：单份候选上限 = 档位上限 / 投掷次数，
    这样任意组合的合计必然在档内。
    """
    print("=" * 82)
    print("E9  预算安全修复：单份上限 = 档位上限 / 投掷次数")
    print("=" * 82)
    print()

    def build_safe(meals, people, band, restrictions):
        """预算感知的建池：先估投掷次数，再收紧单份上限。"""
        no_spicy = any("辣" in r for r in (restrictions or []))
        lo, hi = band["lo"], band["hi"]
        pool = []
        singles = []
        for code, v in meals.items():
            name = v.get("name", "")
            price = float(v.get("currentPrice") or 0)
            if not any(k in name for k in DR.MAIN_KEYWORDS):
                continue
            if DR.is_drink_only(name):
                continue
            if no_spicy and DR.is_spicy(name):
                continue
            s = DR.serves_of(name)
            if s == 1:
                singles.append({"code": code, "name": name, "price": price, "serves": 1})
            if s < people:
                continue
            if price < lo or price > hi:
                continue
            pool.append({"kind": "套餐", "code": code, "name": name,
                         "price": price, "total": price, "serves": s,
                         "perCapita": round(price / s, 2)})
        if pool:
            return pool, False
        for s in singles:
            total = round(s["price"] * people, 2)
            if total < lo or total > hi:
                continue
            pool.append({"kind": "组合", "code": s["code"], "name": s["name"],
                         "price": s["price"], "total": total, "serves": 1,
                         "perCapita": s["price"],
                         "note": "%d 份 %s" % (people, s["name"][:16])})
        return pool, True

    print("  %-16s %4s %6s %-34s %-34s" % ("场景", "投次", "池", "修复前", "修复后"))
    print("  " + "-" * 96)
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            cap = band["hi"]
            hi = cap < 10 ** 9
            pool, _ = build_safe(meals, people, band, ["不吃辣"])
            if not pool:
                continue
            rolls = DR.decide_roll_count(pool, people)
            if rolls <= 1:
                continue
            res = {}
            for label, builder in [("修复前", lambda: build_safe(meals, people, band, ["不吃辣"])[0]),
                                   ("修复后", None)]:
                if label == "修复前":
                    p2 = pool
                    r2 = rolls
                else:
                    # 收紧单份上限：单份 <= 档上限 / 投次
                    sub_cap = cap / rolls
                    p2 = [x for x in pool
                          if x["total"] <= sub_cap or x.get("kind") == "组合"]
                    r2 = rolls
                    if not p2:
                        p2 = pool
                    else:
                        r2 = DR.decide_roll_count(p2, people)
                rng = random.Random(99 + people)
                over = 0
                tot_l = []
                for _ in range(per):
                    tot = 0.0
                    used = set()
                    for _k in range(r2):
                        p, f = roll_m216(p2, rng)
                        if p["code"] in used and len(p2) > 1:
                            p, f = roll_m216(p2, rng)
                        used.add(p["code"])
                        tot += p["total"]
                    tot_l.append(tot)
                    if hi and tot > cap:
                        over += 1
                res[label] = (over * 100.0 / per, statistics.mean(tot_l), len(p2))
            a, b = res["修复前"], res["修复后"]
            print("  %-16s %4d %6s | 越界%5.1f%% 均值%5.0f元 池%2d | 越界%5.1f%% 均值%5.0f元 池%2d"
                  % ("%d人/%s" % (people, bl), rolls, "-",
                     a[0], a[1], a[2], b[0], b[1], b[2]))
    print()


def e10_fixed_engine(meals, per=8000):
    """
    完整修复版引擎实测：M216 + 预算安全建池 + 供餐校验 + 忌口 + 去重。
    目标：越界 0 / 违例 0 / 供餐不足 0 / 覆盖率 100%。
    """
    print("=" * 82)
    print("E10 完整修复版引擎：M216 + 预算安全建池")
    print("=" * 82)
    print()
    from dice3_study3 import structure

    def build_final(meals, people, band, restrictions):
        """两阶段：先粗池定投次，再用投次收紧单份上限重建池。"""
        no_spicy = any("辣" in r for r in (restrictions or []))
        lo, hi = band["lo"], band["hi"]

        def scan(cap):
            pool = []
            singles = []
            for code, v in meals.items():
                name = v.get("name", "")
                price = float(v.get("currentPrice") or 0)
                if not any(k in name for k in DR.MAIN_KEYWORDS):
                    continue
                if DR.is_drink_only(name):
                    continue
                if no_spicy and DR.is_spicy(name):
                    continue
                s = DR.serves_of(name)
                if s == 1:
                    singles.append({"code": code, "name": name,
                                    "price": price, "serves": 1})
                if s < people:
                    continue
                if price < lo or price > cap:
                    continue
                pool.append({"kind": "套餐", "code": code, "name": name,
                             "price": price, "total": price, "serves": s,
                             "perCapita": round(price / s, 2)})
            if pool:
                return pool, False
            for s in singles:
                total = round(s["price"] * people, 2)
                if total < lo or total > cap:
                    continue
                pool.append({"kind": "组合", "code": s["code"], "name": s["name"],
                             "price": s["price"], "total": total, "serves": 1,
                             "perCapita": s["price"],
                             "note": "%d 份 %s" % (people, s["name"][:16])})
            return pool, True

        pool, deg = scan(hi)
        if not pool:
            return pool, deg
        rolls = DR.decide_roll_count(pool, people)
        if rolls > 1 and hi < 10 ** 9:
            sub = hi / rolls
            tight, deg2 = scan(sub)
            if tight:
                pool, deg = tight, deg2
        return pool, deg

    print("  %-16s %4s %5s %8s %8s %8s %8s %8s" %
          ("场景", "投次", "池", "越界", "违例", "供餐不足", "覆盖率", "Gini"))
    print("  " + "-" * 78)
    all_over = all_viol = all_under = 0
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            pool, deg = build_final(meals, people, band, ["不吃辣"])
            if not pool:
                print("  %-16s %4s %5s   无解（如实告知）" % ("%d人/%s" % (people, bl), "-", "-"))
                continue
            rolls = DR.decide_roll_count(pool, people)
            rng = random.Random(31337 + people)
            over = viol = under = 0
            freq = Counter()
            for _ in range(per):
                tot = 0.0
                used = set()
                for _k in range(rolls):
                    p, f = roll_m216(pool, rng)
                    if p["code"] in used and len(pool) > 1:
                        for _try in range(8):
                            p, f = roll_m216(pool, rng)
                            if p["code"] not in used:
                                break
                    used.add(p["code"])
                    tot += p["total"]
                    freq[p["code"]] += 1
                    if "辣" in p["name"]:
                        viol += 1
                    if not serves_ok(p, people):
                        under += 1
                if band["hi"] < 10 ** 9 and tot > band["hi"]:
                    over += 1
            vals = sorted(freq.values(), reverse=True)
            from dice3_study import gini
            cov = len(freq) / len(pool) * 100
            all_over += over
            all_viol += viol
            all_under += under
            print("  %-16s %4d %5d %8d %8d %8d %7.1f%% %8.4f"
                  % ("%d人/%s" % (people, bl), rolls, len(pool),
                     over, viol, under, cov, gini(vals)))
    print()
    print("  合计：越界 %d | 违例 %d | 供餐不足 %d" % (all_over, all_viol, all_under))
    print()


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    e8_multi(meals)
    e9_budget_safe(meals)
    e10_fixed_engine(meals)


if __name__ == "__main__":
    main()
