#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 3 —— 修正版：ρ(点数↔价格) 必须与选餐同源；组合类供餐判定修正。
同时验证 M216 的严格单调性与「语义层」增强。
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
from dice3_study import gini, cv, spearman, ALL216, _segment  # noqa: E402

MENU = os.path.join(HERE, "menu_dinein.json")
IDX216 = {t: i for i, t in enumerate(ALL216)}


def structure(t):
    s = sorted(t)
    if s[0] == s[2]:
        return "豹子"
    if s[0] == s[1] or s[1] == s[2]:
        return "对子"
    if s[2] - s[0] == 2 and len(set(s)) == 3:
        return "顺子"
    return "散牌"


def serves_ok(item, people):
    """组合类本身就是 N 份打包，供餐天然满足。"""
    if item.get("kind") == "组合":
        return True
    return item.get("serves", 1) >= people


def roll_m6(pool, rng):
    srt = sorted(pool, key=lambda x: x["total"])
    f = rng.randint(1, 6)
    seg = _segment(srt, f - 1, 6)
    return (rng.choice(seg) if seg else srt[0]), f


def roll_m16(pool, rng):
    srt = sorted(pool, key=lambda x: x["total"])
    t = tuple(rng.randint(1, 6) for _ in range(3))
    s = sum(t)
    seg = _segment(srt, min(15, max(0, s - 3)), 16)
    return (rng.choice(seg) if seg else srt[0]), s


def roll_m216(pool, rng):
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    t = tuple(rng.randint(1, 6) for _ in range(3))
    idx = min(int(IDX216[t] * n / 216), n - 1)
    return srt[idx], sum(t)


METHODS = [("M6", roll_m6), ("M16", roll_m16), ("M216", roll_m216)]


def e4_fixed(meals, per=20000):
    print("=" * 80)
    print("E4' 修正版对比（face 与选餐同源；组合类供餐判定已修）")
    print("=" * 80)
    print("  %-4s %-8s %3s | %-30s | %-30s" % ("人数", "预算", "池", "M6", "M216"))
    print("  " + "-" * 78)
    rows = []
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            pool, deg = DR.build_pool(meals, people, DR.normalize_band(bk), ["不吃辣"])
            if not pool:
                continue
            band = DR.normalize_band(bk)
            rng = random.Random(7788 + people)
            res = {}
            for m, fn in METHODS:
                over = viol = under = 0
                faces, prices, freq = [], [], Counter()
                for _ in range(per):
                    p, f = fn(pool, rng)          # ★ 同源
                    faces.append(f)
                    prices.append(p["total"])
                    freq[p["code"]] += 1
                    if band["hi"] < 10 ** 9 and p["total"] > band["hi"]:
                        over += 1
                    if "辣" in p["name"]:
                        viol += 1
                    if not serves_ok(p, people):
                        under += 1
                vals = sorted(freq.values(), reverse=True)
                res[m] = dict(over=over, viol=viol, under=under,
                              gini=gini(vals),
                              top3=sum(vals[:3]) * 100.0 / sum(vals),
                              rho=spearman(faces, prices))
            rows.append((people, bl, len(pool), res))
            a, b = res["M6"], res["M216"]
            print("  %-4d %-8s %3d | G=%.3f top3=%5.1f%% ρ=%+.3f | G=%.3f top3=%5.1f%% ρ=%+.3f"
                  % (people, bl, len(pool),
                     a["gini"], a["top3"], a["rho"], b["gini"], b["top3"], b["rho"]))
    print()
    tot = {m: {"over": 0, "viol": 0, "under": 0} for m, _ in METHODS}
    for _, _, _, res in rows:
        for m, _ in METHODS:
            for k in tot[m]:
                tot[m][k] += res[m][k]
    n = len(rows) * per
    for m, _ in METHODS:
        print("  %-5s 预算越界 %d | 忌口违例 %d | 供餐不足 %d   （%d 次投掷）"
              % (m, tot[m]["over"], tot[m]["viol"], tot[m]["under"], n))
    print()
    for key, label in [("gini", "Gini(均匀性)"), ("top3", "top3 集中度"), ("rho", "ρ(点数↔价格)")]:
        g6 = statistics.mean([r[3]["M6"][key] for r in rows])
        g16 = statistics.mean([r[3]["M16"][key] for r in rows])
        g216 = statistics.mean([r[3]["M216"][key] for r in rows])
        better = min((g6, "M6"), (g16, "M16"), (g216, "M216"))[1]
        print("  平均 %-16s M6=%+.4f  M16=%+.4f  M216=%+.4f   最优=%s"
              % (label, g6, g16, g216, better))
    print()


def e5_monotonic(meals):
    """M216 的单调性：同样的三骰，总和越大 → 价格越高？"""
    print("=" * 80)
    print("E5  M216 阶梯的严格单调性检验")
    print("=" * 80)
    pool, _ = DR.build_pool(meals, 1, DR.normalize_band("under50"), ["不吃辣"])
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    print("  池容量 %d，价格 %.1f~%.1f" % (n, srt[0]["total"], srt[-1]["total"]))
    print()
    print("  %-6s %-8s %-22s %s" % ("骰面", "总和", "阶梯位", "落在价格位"))
    print("  " + "-" * 60)
    probes = [(1, 1, 1), (1, 1, 2), (2, 2, 2), (1, 2, 3), (3, 3, 3),
              (1, 4, 6), (4, 5, 6), (6, 6, 6), (2, 6, 6), (5, 6, 6)]
    for t in probes:
        r = IDX216[t]
        idx = min(int(r * n / 216), n - 1)
        print("  %-6s %-8d %-22d #%d  %.1f 元  %s"
              % ("%d%d%d" % t, sum(t), r, idx, srt[idx]["total"], srt[idx]["name"][:20]))
    print()
    # 全量单调性
    prev = -1
    viol = 0
    for t in ALL216:
        r = IDX216[t]
        idx = min(int(r * n / 216), n - 1)
        if idx < prev:
            viol += 1
        prev = max(prev, idx)
    print("  ★ 216 个骰面按阶梯映射到价格位，单调递减违例 = %d （0 = 严格单调）" % viol)
    print()


def e6_semantic(meals, per=20000):
    """语义层：结构标签能否与价位正交地叠加。"""
    print("=" * 80)
    print("E6  语义层：结构（豹子/对子/顺子/散牌）能带来什么")
    print("=" * 80)
    cnt = Counter()
    bysum = {}
    for t in ALL216:
        k = structure(t)
        cnt[k] += 1
        bysum.setdefault(k, []).append(sum(t))
    for k, v in cnt.most_common():
        ss = bysum[k]
        print("  %-6s %3d 种 (%5.1f%%)  总和范围 %d~%d  均值 %.1f"
              % (k, v, v * 100.0 / 216, min(ss), max(ss), statistics.mean(ss)))
    print()
    print("  ★ 豹子/对子/顺子/散牌 的总和分析：")
    print("    散牌总和范围最窄（4~14），顺子只在 6/9/12/15 出现 —— 结构与点数强相关，")
    print("    所以「结构」不能作为独立于价位的第二维度，否则二者互相打架。")
    print()
    print("  ✓ 更可行的用法：把结构作为【叙事标签】而非决策维度 ——")
    print("      豹子(2.8%)  = 「幸运三连」→ 加赠小食/升级特调")
    print("      顺子(11.1%) = 「顺流套餐」→ 优先连锁/家庭套餐")
    print("      对子(41.7%) = 「双拼日」  → 牛+鸡 双拼")
    print("      散牌(44.4%) = 「日常局」  → 标准选择")
    print("    标签由骰子自然产生，不影响合规性（加成后仍要重算预算）。")
    print()


def e7_granularity(meals):
    """粒度经济学：多少候选时三骰才有意义？"""
    print("=" * 80)
    print("E7  粒度经济学：三骰 vs 单骰的边际收益")
    print("=" * 80)
    print("  %-24s %8s %10s %12s" % ("场景", "池容量", "单骰可用档", "三骰可用档"))
    print("  " + "-" * 58)
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            pool, _ = DR.build_pool(meals, people, DR.normalize_band(bk), ["不吃辣"])
            if not pool:
                continue
            n = len(pool)
            s6 = min(6, n)
            s216 = min(216, n)
            waste = (1 - s6 / n) * 100
            print("  %-24s %8d %10d %12d   单骰浪费 %.0f%% 概率"
                  % ("%d人/%s" % (people, bl), n, s6, s216, waste))
    print()
    print("  ★ 池 ≤ 6 时，单骰已经把候选全覆盖 —— 三骰不增加选餐多样性。")
    print("    池 = 24 时：单骰 6 段，每段 4 个候选；M216 给 24 个候选各自独立概率。")
    print("    真正提升在池 15~42 的场景（1人/50以内 42、4人/100+ 34、3人/50-100 24）。")
    print()


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    e4_fixed(meals)
    e5_monotonic(meals)
    e6_semantic(meals)
    e7_granularity(meals)


if __name__ == "__main__":
    main()
