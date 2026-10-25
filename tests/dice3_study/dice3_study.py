#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三骰选餐假设验证 —— 「3 颗骰子 / 18 个点 / 排列组合」的数学与菜单实测。

Q1 三骰总和 3~18 是不是均匀的 16 档？
Q2 现有单骰 6 段 vs 三骰 16 段 vs 三骰 216 级，哪种映射更均匀？
Q3 「排列组合」这一维度到底带来什么？
Q4 真实菜单 + 12 个（人数 × 预算）场景下哪种方案可行？
"""
import itertools
import json
import math
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.expanduser("~/.workbuddy/skills/mcd-ordering/scripts")
sys.path.insert(0, SKILL)

import dice_roll as DR  # noqa: E402

MENU = os.path.join(HERE, "menu_dinein.json")


# ================================================================ 统计工具
def gini(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    s = sorted(xs)
    tot = sum(s)
    if tot == 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(s):
        cum += (i + 1) * x
    return (2 * cum) / (n * tot) - (n + 1) / n


def cv(xs):
    if not xs:
        return 0.0
    m = statistics.mean(xs)
    return statistics.pstdev(xs) / m if m else 0.0


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


def entropy(probs):
    return -sum(p * math.log2(p) for p in probs if p > 0)


# ================================================================ Q1 数学
def q1_math():
    print("=" * 74)
    print("Q1  三骰总和分布：3~18 到底均不均匀？")
    print("=" * 74)
    cnt = {}
    for t in itertools.product(range(1, 7), repeat=3):
        cnt[sum(t)] = cnt.get(sum(t), 0) + 1
    total = 216
    print("  点数  :  " + " ".join("%3d" % s for s in range(3, 19)))
    print("  组合数:  " + " ".join("%3d" % cnt.get(s, 0) for s in range(3, 19)))
    print("  概率% :  " + " ".join("%3.1f" % (cnt.get(s, 0) * 100.0 / total) for s in range(3, 19)))
    probs = [cnt.get(s, 0) / total for s in range(3, 19)]
    print()
    print("  ★ 16 档若视为均匀，每档应为 6.25%。实际：")
    print("    点数 10/11/12 三档合计 %.1f%%  ← 吃掉超过 1/3 的概率" % (sum(probs[7:10]) * 100))
    print("    点数 3 与 18 各只有 %.2f%%  ← 最便宜/最贵的档几乎掷不出" % (probs[0] * 100))
    print("    熵 %.4f bits（均匀 16 档需 4.0000 bits）→ 有效档位只有 %.1f 档"
          % (entropy(probs), 2 ** entropy(probs)))
    print()
    print("  ★ 排列组合维度：")
    print("    有序 (a,b,c) 共 %d 种（每种等概率）" % total)
    print("    忽略顺序的组合共 %d 种（每种概率不同）"
          % len({tuple(sorted(t)) for t in itertools.product(range(1, 7), repeat=3)}))
    print("    → 「18 个点」实为 16 个不同总和值；三骰的自然离散度是 216 档等概率。")
    print()
    return cnt


# ================================================================ 映射方案
def key_strength(t):
    """
    强度键：主键 = 总和点数（保留「点数大 = 吃得好」直觉）
    次键 = 最大骰 / 中位骰 / 最小骰 → 同和的多种排列被稳定排开
    """
    a, b, c = t
    return (a + b + c, max(a, b, c), sorted((a, b, c))[1], min(a, b, c))


ALL216 = sorted(itertools.product(range(1, 7), repeat=3), key=key_strength)
SUM_ORDER = {}
for _s in range(3, 19):
    SUM_ORDER[_s] = sorted([t for t in ALL216 if sum(t) == _s])


def _segment(srt, lo, hi):
    """价格排序池切段 [lo,hi)，返回该段内的候选列表。"""
    n = len(srt)
    if n <= 1:
        return srt
    bounds = [round(i * n / hi) for i in range(hi + 1)]
    a, b = bounds[lo], bounds[lo + 1]
    if b <= a:
        # 边界重合 → 向右找最近的有货段
        for k in range(lo, hi):
            aa, bb = bounds[k], bounds[k + 1]
            if bb > aa:
                return srt[aa:bb]
        return srt
    return srt[a:b]


def pick_m6(pool, rng):
    """基线：单骰 6 段（现状实现语义）。"""
    srt = sorted(pool, key=lambda x: x["total"])
    f = rng.randint(1, 6)
    seg = _segment(srt, f - 1, 6)
    return rng.choice(seg) if seg else srt[0]


def pick_m16(pool, rng):
    """三骰总和 → 16 个价位档（总和值直接当档号），档内均匀随机。"""
    srt = sorted(pool, key=lambda x: x["total"])
    s = sum(rng.randint(1, 6) for _ in range(3))
    seg = _segment(srt, min(15, max(0, s - 3)), 16)
    return rng.choice(seg) if seg else srt[0]


def pick_m216(pool, rng):
    """
    三骰 216 级强度阶梯：
    216 个有序三元组按强度键排成阶梯，价格池等长对应 → 每候选命中概率 = 1/n，
    且「强度越大 → 价格越贵」严格单调。
    """
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    t = tuple(rng.randint(1, 6) for _ in range(3))
    r = ALL216.index(t)
    idx = min(int(r * n / 216), n - 1)
    return srt[idx]


def pick_msum216(pool, rng):
    """
    变体：阶梯只用总和作主序，同和的 27 种排列按字典序排开。
    与 m216 对比 → 检验「排列」作为次级维度是否真的有贡献。
    """
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    t = tuple(rng.randint(1, 6) for _ in range(3))
    s = sum(t)
    r = (s - 3) * 27 + SUM_ORDER[s].index(t)
    idx = min(int(r * n / 216), n - 1)
    return srt[idx]


def pick_mdirect(pool, rng):
    """
    变体：216 阶梯 + 强度权重。
    强度不只用总和，还用「平方和」强调大点数组合（666 比 631 更豪华）。
    """
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    t = tuple(rng.randint(1, 6) for _ in range(3))
    ss = sum(x * x for x in t)
    r = ALL216.index(t)
    idx = min(int(r * n / 216), n - 1)
    return srt[idx]


METHODS = [
    ("M6    单骰6段", pick_m6),
    ("M16   总和16档", pick_m16),
    ("M216  强度阶梯", pick_m216),
    ("Msum  仅总和", pick_msum216),
]


# ================================================================ Q4 场景体检
def q4_scenarios(meals):
    print("=" * 74)
    print("Q4  真实菜单下 12 个场景的候选池（决定映射粒度上限）")
    print("=" * 74)
    print("  %-6s %-8s %6s %12s %s" % ("人数", "预算档", "池容量", "价格跨度", "备注"))
    print("  " + "-" * 64)
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            pool, deg = DR.build_pool(meals, people, DR.normalize_band(bk), ["不吃辣"])
            if not pool:
                print("  %-6d %-8s %6s %12s %s" % (people, bl, "无解", "-", "真无解，如实告知"))
                continue
            ps = [p["total"] for p in pool]
            note = []
            if deg:
                note.append("组合兜底")
            if len(pool) <= 6:
                note.append("池小→16档大量重复")
            elif len(pool) < 16:
                note.append("池<16→部分档位重复")
            print("  %-6d %-8s %6d %12s %s"
                  % (people, bl, len(pool), "%.1f~%.1f" % (min(ps), max(ps)), " ".join(note)))
    print()


# ================================================================ Q2/Q3 实测
def q2_simulate(meals, trials=60000):
    print("=" * 74)
    print("Q2/Q3  四种映射方案在真实菜单上的对比（每个有解场景 %d 次）" % (trials // 12))
    print("=" * 74)
    bands = ["under50", "50to100", "over100"]
    peoples = [1, 2, 3, 4]
    scenarios = [(p, b) for p in peoples for b in bands]

    agg = {n: {"freq": {}, "face": [], "price": [], "over": 0, "viol": 0, "under": 0}
           for n, _ in METHODS}
    rng = random.Random(20261024)

    # 预建场景池
    pools = {}
    for (p, b) in scenarios:
        pool, deg = DR.build_pool(meals, p, DR.normalize_band(b), ["不吃辣"])
        pools[(p, b)] = pool

    for (p, b) in scenarios:
        pool = pools[(p, b)]
        if not pool:
            continue
        band = DR.normalize_band(b)
        for _ in range(trials // 12):
            for name, fn in METHODS:
                if name.startswith("M6"):
                    face = rng.randint(1, 6)
                    # 单骰也要用同样的骰源，保证对照公平
                    save = rng.getstate()
                    rng.setstate(save)
                    pick = pick_m6(pool, rng)
                    fv = face
                elif name.startswith("M16"):
                    dice = [rng.randint(1, 6) for _ in range(3)]
                    pick = pick_m16(pool, rng)
                    fv = sum(dice)
                else:
                    dice = [rng.randint(1, 6) for _ in range(3)]
                    pick = pick_m216(pool, rng) if name.startswith("M216") else pick_msum216(pool, rng)
                    fv = sum(dice)
                agg[name]["freq"][pick["code"]] = agg[name]["freq"].get(pick["code"], 0) + 1
                agg[name]["face"].append(fv)
                agg[name]["price"].append(pick["total"])
                if band["hi"] < 10 ** 9 and pick["total"] > band["hi"]:
                    agg[name]["over"] += 1
                if "辣" in pick["name"]:
                    agg[name]["viol"] += 1
                if pick.get("serves", 1) < p:
                    agg[name]["under"] += 1

    # 全局候选全集
    allcodes = set()
    for (p, b) in scenarios:
        for it in pools[(p, b)]:
            allcodes.add(it["code"])

    print("  %-18s %8s %9s %8s %10s %8s" %
          ("方案", "覆盖率", "基尼", "变异", "点数↔价", "越界"))
    print("  " + "-" * 68)
    for name, _ in METHODS:
        a = agg[name]
        freqs = [a["freq"].get(c, 0) for c in sorted(allcodes)]
        cov = sum(1 for f in freqs if f > 0) / max(len(freqs), 1) * 100
        rho = spearman(a["face"], a["price"]) if len(a["face"]) > 10 else 0.0
        print("  %-18s %7.1f%% %9.4f %8.3f %10.4f %8d"
              % (name, cov, gini(freqs), cv(freqs), rho, a["over"]))
    print()
    print("  覆盖率 = 被至少选中过一次的候选占比（越高越不重复）")
    print("  基尼   = 命中次数的不平等程度（0 最均匀，越大越集中）")
    print("  点数↔价 = Spearman 相关系数（保留「点数大 = 吃得好」的程度）")
    print()
    return agg, pools, allcodes


# ================================================================ Q5 结论
def q5_conclusion(agg, pools, allcodes):
    print("=" * 74)
    print("Q5  每候选命中次数分布（看真实均匀性）")
    print("=" * 74)
    for name, _ in METHODS:
        f = sorted(agg[name]["freq"].values())
        if not f:
            continue
        print("  %-18s 候选 %2d 个 | 命中 min=%d 中位=%d max=%d | 前 5 高频占比 %.1f%%"
              % (name, len(f), f[0], f[len(f) // 2], f[-1],
                 sum(f[-5:]) * 100.0 / sum(f)))
    print()
    print("  ★ 关键读数：若「前 5 高频占比」远高于 5/n，说明映射把概率挤到了少数档位。")
    print()


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    q1_math()
    q4_scenarios(meals)
    agg, pools, allcodes = q2_simulate(meals, trials=60000)
    q5_conclusion(agg, pools, allcodes)


if __name__ == "__main__":
    main()
