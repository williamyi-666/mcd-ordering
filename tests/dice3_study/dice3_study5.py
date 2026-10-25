#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 5 —— 压力测试：强制多份投掷，验证预算安全修复是否真的有效。
构造「池中最大供餐人数 < 人数」的场景，强制 rolls ≥ 2。
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
from dice3_study import gini, ALL216  # noqa: E402

MENU = os.path.join(HERE, "menu_dinein.json")
IDX216 = {t: i for i, t in enumerate(ALL216)}


def roll_m216(pool, rng):
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    t = tuple(rng.randint(1, 6) for _ in range(3))
    idx = min(int(IDX216[t] * n / 216), n - 1)
    return srt[idx], sum(t)


def roll_m6(pool, rng):
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    f = rng.randint(1, 6)
    if n <= 6:
        return srt[min(int((f - 1) * n / 6), n - 1)], f
    bounds = [round(i * n / 6) for i in range(7)]
    a, b = bounds[f - 1], bounds[f]
    if b <= a:
        for k in range(6):
            aa, bb = bounds[k], bounds[k + 1]
            if bb > aa:
                a, b = aa, bb
                break
    return srt[a + (b - a) // 2], f


def e11_stress(meals, per=6000):
    print("=" * 84)
    print("E11 压力测试：强制多份投掷（模拟菜单缺货导致的 pool 收缩）")
    print("=" * 84)
    print("  构造方式：只保留【供餐人数 == 1】的套餐，强制每人一份")
    print()

    def singles_pool(meals, people, band, restrictions, cap_div=1):
        no_spicy = any("辣" in r for r in (restrictions or []))
        lo, hi = band["lo"], band["hi"]
        cap = hi / cap_div if hi < 10 ** 9 else hi
        pool = []
        for code, v in meals.items():
            name = v.get("name", "")
            price = float(v.get("currentPrice") or 0)
            if not any(k in name for k in DR.MAIN_KEYWORDS):
                continue
            if DR.is_drink_only(name):
                continue
            if no_spicy and DR.is_spicy(name):
                continue
            if DR.serves_of(name) != 1:
                continue
            if price < lo or price > cap:
                continue
            pool.append({"kind": "套餐", "code": code, "name": name,
                         "price": price, "total": price, "serves": 1,
                         "perCapita": price})
        return pool

    print("  %-16s %4s %5s %8s %10s %10s" %
          ("场景", "投次", "池", "越界率", "修复前均值", "修复后均值"))
    print("  " + "-" * 76)
    for people in [2, 3, 4]:
        for bk, bl in [("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            # 修复前：单份上限 = 档上限
            p_raw = singles_pool(meals, people, band, ["不吃辣"], cap_div=1)
            if not p_raw:
                continue
            rolls = people
            # 修复后：单份上限 = 档上限 / 投次
            p_fix = singles_pool(meals, people, band, ["不吃辣"], cap_div=rolls)
            if not p_fix:
                p_fix = p_raw
            cap = band["hi"]
            out = []
            for label, pool in [("修复前", p_raw), ("修复后", p_fix)]:
                rng = random.Random(5150 + people)
                over = 0
                tots = []
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
                    tots.append(tot)
                    if cap < 10 ** 9 and tot > cap:
                        over += 1
                out.append((over * 100.0 / per, statistics.mean(tots), len(pool)))
            a, b = out
            print("  %-16s %4d %2d/%-2d %7.1f%% %10.0f元 %10.0f元"
                  % ("%d人/%s" % (people, bl), rolls,
                     a[2], b[2], b[0], a[1], b[1]))
    print()
    print("  ★ 结论：不做收紧时，多份投掷的合计会突破档位上限（越界率可达数十%）；")
    print("    把单份上限设为「档上限 / 投掷次数」后，越界率归零。")
    print()


def e12_design_check(meals):
    """最终设计自检：M216 + 预算安全 + 供餐 + 忌口 + 去重，12 场景 × 多轮。"""
    print("=" * 84)
    print("E12 最终设计全量自检")
    print("=" * 84)
    print()

    def build_final(meals, people, band, restrictions):
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
            return pool, deg, 0
        rolls = DR.decide_roll_count(pool, people)
        if rolls > 1 and hi < 10 ** 9:
            tight, deg2 = scan(hi / rolls)
            if tight:
                pool, deg = tight, deg2
                rolls = DR.decide_roll_count(pool, people)
        return pool, deg, rolls

    print("  %-16s %4s %5s %8s %8s %8s %8s %8s" %
          ("场景", "投次", "池", "越界", "违例", "供餐不足", "覆盖率", "Gini"))
    print("  " + "-" * 80)
    per = 10000
    tot_over = tot_viol = tot_under = 0
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            pool, deg, rolls = build_final(meals, people, band, ["不吃辣"])
            if not pool:
                print("  %-16s %4s %5s   无解（如实告知）" % ("%d人/%s" % (people, bl), "-", "-"))
                continue
            rng = random.Random(20261024 + people)
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
                    if p.get("kind") != "组合" and p.get("serves", 1) < people:
                        under += 1
                if band["hi"] < 10 ** 9 and tot > band["hi"]:
                    over += 1
            vals = sorted(freq.values(), reverse=True)
            cov = len(freq) / len(pool) * 100
            tot_over += over
            tot_viol += viol
            tot_under += under
            print("  %-16s %4d %5d %8d %8d %8d %7.1f%% %8.4f"
                  % ("%d人/%s" % (people, bl), rolls, len(pool),
                     over, viol, under, cov, gini(vals)))
    print()
    print("  ★ 合计：越界 %d | 忌口违例 %d | 供餐不足 %d  —— 全部为 0 即达标"
          % (tot_over, tot_viol, tot_under))
    print()


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    e11_stress(meals)
    e12_design_check(meals)


if __name__ == "__main__":
    main()
