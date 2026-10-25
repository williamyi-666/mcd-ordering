#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 8 —— 统一口径重测：M6 / M16 / M216 在【真实菜单 + 权威人数】下对比。

前面的实验分批做，池设定不同（有无权威人数），
文档里的 Gini 数字必须统一口径重测一次，否则不可比。
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
from dice_roll import ALL_TRIPLES, TRIPLE_RANK, N_ATOMS, _segment  # noqa: E402

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


def pick(pool, rng, method):
    """返回 (候选, 强度值)。强度值=参与 Spearman 的标量。"""
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    if method == "M6":
        f = rng.randint(1, 6)
        seg = _segment(srt, f - 1, 6)
        return (rng.choice(seg) if seg else srt[0]), f
    if method == "M16":
        t = tuple(rng.randint(1, 6) for _ in range(3))
        s = sum(t)
        seg = _segment(srt, min(15, max(0, s - 3)), 16)
        return (rng.choice(seg) if seg else srt[0]), s
    t = tuple(rng.randint(1, 6) for _ in range(3))
    idx = min(int(TRIPLE_RANK[t] * n / N_ATOMS), n - 1)
    return srt[idx], sum(t)


METHODS = ["M6", "M16", "M216"]


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    serves_map = json.load(open(SERVES, encoding="utf-8"))

    print("=" * 86)
    print("统一口径重测：M6 / M16 / M216（真实菜单 1450056 + 权威供餐人数）")
    print("=" * 86)
    print()
    PER = 20000
    agg = {m: {"g": [], "rho": [], "over": 0} for m in METHODS}
    print("  %-5s %-8s %4s | %-22s | %-22s | %-22s"
          % ("人数", "预算档", "池", "M6 单骰6段", "M16 总和16档", "M216 强度阶梯"))
    print("  " + "-" * 82)
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            pool, _ = DR.build_pool(meals, people, band, ["不吃辣"], serves_map)
            if not pool:
                print("  %-5d %-8s %4s | 无解" % (people, bl, "-"))
                continue
            cells = {}
            for m in METHODS:
                rng = random.Random(2026 + people)
                freq = Counter()
                strengths, prices = [], []
                over = 0
                for _ in range(PER):
                    p, s = pick(pool, rng, m)
                    freq[p["code"]] += 1
                    strengths.append(s)
                    prices.append(p["total"])
                    if band["hi"] < 10 ** 9 and p["total"] > band["hi"]:
                        over += 1
                vals = sorted(freq.values(), reverse=True)
                agg[m]["g"].append(gini(vals))
                agg[m]["rho"].append(spearman(strengths, prices))
                agg[m]["over"] += over
                cells[m] = (gini(vals), spearman(strengths, prices))
            print("  %-5d %-8s %4d | G=%.4f ρ=%+.3f | G=%.4f ρ=%+.3f | G=%.4f ρ=%+.3f"
                  % (people, bl, len(pool),
                     cells["M6"][0], cells["M6"][1],
                     cells["M16"][0], cells["M16"][1],
                     cells["M216"][0], cells["M216"][1]))
    print()
    print("  " + "=" * 82)
    for m in METHODS:
        a = agg[m]
        print("  %-6s 平均 Gini=%.4f   平均 ρ=%+.4f   越界 %d"
              % (m, statistics.mean(a["g"]), statistics.mean(a["rho"]), a["over"]))
    print()
    gs = {m: statistics.mean(agg[m]["g"]) for m in METHODS}
    print("  ★ 均匀性排序：%s" % " < ".join(
        "%s(%.4f)" % (m, gs[m]) for m in sorted(METHODS, key=lambda x: gs[x])))
    print("  ★ M216 相对 M6 均匀性提升 %.1f 倍；相对 M16 提升 %.1f 倍"
          % (gs["M6"] / gs["M216"], gs["M16"] / gs["M216"]))
    print()

    # 只看池容量 >= 8 的场景（三骰有意义的区间）
    print("  仅统计池容量 ≥ 8 的场景（单骰不占优的区间）:")
    big = [(p, b) for p in [1, 2, 3, 4]
           for b in ["under50", "50to100", "over100"]
           if DR.build_pool(meals, p, DR.normalize_band(b), ["不吃辣"], serves_map)[0]
           and len(DR.build_pool(meals, p, DR.normalize_band(b), ["不吃辣"], serves_map)[0]) >= 8]
    print("  场景：%s" % ["%d人/%s" % (p, b) for p, b in big])
    sub = {m: [] for m in METHODS}
    for people, bk in big:
        band = DR.normalize_band(bk)
        pool, _ = DR.build_pool(meals, people, band, ["不吃辣"], serves_map)
        for m in METHODS:
            rng = random.Random(31 + people)
            freq = Counter()
            for _ in range(PER):
                p, s = pick(pool, rng, m)
                freq[p["code"]] += 1
            sub[m].append(gini(sorted(freq.values(), reverse=True)))
    for m in METHODS:
        print("    %-6s 平均 Gini=%.4f" % (m, statistics.mean(sub[m])))
    print("  ★ 大池场景 M216 相对 M6 提升 %.1f 倍"
          % (statistics.mean(sub["M6"]) / statistics.mean(sub["M216"])))


if __name__ == "__main__":
    main()
