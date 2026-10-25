#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 7 —— v1 单骰 vs v2 三骰，同菜单同权威人数的最终对比表。

这是写进文档的权威数字来源。
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

MENU = os.path.join(HERE, "menu_dinein.json")
SERVES = os.path.join(HERE, "serves_map.json")


def gini(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    s = sorted(xs)
    tot = sum(s)
    if tot == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(s))
    return (2 * cum) / (n * tot) - (n + 1) / n


def rank(a):
    order = sorted(range(len(a)), key=lambda i: a[i])
    r = [0.0] * len(a)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and a[order[j + 1]] == a[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = (sum((v - mx) ** 2 for v in rx) * sum((v - my) ** 2 for v in ry)) ** 0.5
    return num / den if den else 0.0


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    serves_map = json.load(open(SERVES, encoding="utf-8"))

    print("=" * 84)
    print("v1 单骰 vs v2 三骰 —— 同菜单(1450056) 同权威人数 最终对比")
    print("=" * 84)
    print()
    hdr = "  %-5s %-8s %4s | %-28s | %-28s" % (
        "人数", "预算档", "池", "v1 单骰 6段", "v2 三骰 216级")
    print(hdr)
    print("  " + "-" * 80)
    agg = {"single": {"g": [], "rho": [], "cov": [], "over": 0, "viol": 0, "under": 0},
           "triple": {"g": [], "rho": [], "cov": [], "over": 0, "viol": 0, "under": 0}}
    PER = 20000
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            pool, deg = DR.build_pool(meals, people, band, ["不吃辣"], serves_map)
            if not pool:
                print("  %-5d %-8s %4s | 无解（如实告知）" % (people, bl, "-"))
                continue
            res = {}
            for mode in ("single", "triple"):
                rng = random.Random(555 + people)
                freq = Counter()
                faces, prices = [], []
                over = viol = under = 0
                for _ in range(PER):
                    r = DR.roll_food(meals, people, bk, ["不吃辣"],
                                     dice_mode=mode, serves_map=serves_map)
                    if not r["ok"]:
                        continue
                    faces.append(r["faces"][0] if mode == "single" else sum(r["faces"][0]))
                    prices.append(r["total"])
                    freq[r["picks"][0]["code"]] += 1
                    if band["hi"] < 10 ** 9 and r["total"] > band["hi"]:
                        over += 1
                    for p in r["picks"]:
                        if "辣" in p["name"]:
                            viol += 1
                    if r.get("servesTotal", 0) < people:
                        under += 1
                vals = sorted(freq.values(), reverse=True)
                res[mode] = dict(gini=gini(vals),
                                 rho=spearman(faces, prices),
                                 cov=len(freq) / len(pool) * 100,
                                 over=over, viol=viol, under=under)
                a = agg[mode]
                a["g"].append(res[mode]["gini"])
                a["rho"].append(res[mode]["rho"])
                a["cov"].append(res[mode]["cov"])
                a["over"] += over
                a["viol"] += viol
                a["under"] += under
            a, b = res["single"], res["triple"]
            print("  %-5d %-8s %4d | G=%.4f ρ=%+.3f 覆%3.0f%% | G=%.4f ρ=%+.3f 覆%3.0f%%"
                  % (people, bl, len(pool),
                     a["gini"], a["rho"], a["cov"], b["gini"], b["rho"], b["cov"]))
    print()
    print("  " + "=" * 76)
    for mode in ("single", "triple"):
        a = agg[mode]
        n = len(a["g"])
        print("  %-6s 平均 Gini=%.4f  平均 ρ=%+.4f  平均覆盖率=%.1f%%  |  越界%d 违例%d 供餐不足%d"
              % (mode, statistics.mean(a["g"]), statistics.mean(a["rho"]),
                 statistics.mean(a["cov"]), a["over"], a["viol"], a["under"]))
    print()
    gs, gt = statistics.mean(agg["single"]["g"]), statistics.mean(agg["triple"]["g"])
    print("  ★ 均匀性提升 %.1f 倍（%.4f → %.4f）"
          % (gs / gt if gt else 0, gs, gt))
    print()

    # 免费重投触发率
    from collections import Counter as C
    c = C(DR.structure_of(t) for t in DR.ALL_TRIPLES)
    tok = c["豹子"] + c["顺子"]
    print("  免费重投触发率：豹子 %.1f%% + 顺子 %.1f%% = %.1f%%"
          % (c["豹子"] * 100.0 / 216, c["顺子"] * 100.0 / 216, tok * 100.0 / 216))
    print()

    # 预算利用率
    print("  预算利用率（三骰，各场景）:")
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            pool, _ = DR.build_pool(meals, people, band, ["不吃辣"], serves_map)
            if not pool:
                continue
            rng = random.Random(99)
            tot = []
            for _ in range(5000):
                r = DR.roll_food(meals, people, bk, ["不吃辣"],
                                 dice_mode="triple", serves_map=serves_map)
                if r["ok"]:
                    tot.append(r["total"])
            cap = band["hi"] if band["hi"] < 10 ** 9 else statistics.mean(tot)
            print("    %d人/%-8s 均价 %5.1f 元   利用率 %5.1f%%"
                  % (people, bl, statistics.mean(tot), statistics.mean(tot) / cap * 100))


if __name__ == "__main__":
    main()
