#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 2 —— 分场景均匀性 + 「排列组合」维度的真实价值验证。

核心论点：
  三骰总和只有 16 个「原子」，最大原子概率 12.5%。
  想让 n 个候选命中概率相等（1/n），单个原子必须 ≤ 1/n。
  → 当 n > 8 时，16 档根本不够，必须用 216 个「有序三元组」当原子。
  这正是用户「排列组合」直觉的数学价值所在。

实验内容：
  E1 分场景均匀性：M6 / M16 / M216 逐场景算 Gini 与 top-k 集中度
  E2 理论可达下界：n 候选时均匀映射需要多少原子
  E3 排列语义分类：216 种骰面按结构分几类，能绑什么维度
  E4 双维度方案：总和→价位 + 排列结构→品类，验证是否可行
"""
import itertools
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
from dice3_study import (gini, cv, spearman, ALL216, SUM_ORDER,  # noqa: E402
                         _segment, entropy)

NAMES = ["M6", "M16", "M216"]


# ================================================================ 映射
def pick(pool, rng, method):
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    if method == "M6":
        f = rng.randint(1, 6)
        seg = _segment(srt, f - 1, 6)
        return rng.choice(seg) if seg else srt[0]
    if method == "M16":
        s = sum(rng.randint(1, 6) for _ in range(3))
        seg = _segment(srt, min(15, max(0, s - 3)), 16)
        return rng.choice(seg) if seg else srt[0]
    # M216
    t = tuple(rng.randint(1, 6) for _ in range(3))
    idx = min(int(ALL216.index(t) * n / 216), n - 1)
    return srt[idx]


# ================================================================ E1 分场景
def e1(meals, per=8000):
    print("=" * 78)
    print("E1  分场景均匀性（每场景 %d 次投掷）" % per)
    print("=" * 78)
    print("  %-5s %-8s %4s | %-24s | %-24s" % ("人数", "预算档", "池", "M6 (基尼/top3占比)", "M216 (基尼/top3占比)"))
    print("  " + "-" * 74)
    summary = {m: {"g": [], "t3": [], "cov": []} for m in NAMES}
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            pool, _ = DR.build_pool(meals, people, DR.normalize_band(bk), ["不吃辣"])
            if not pool:
                print("  %-5d %-8s %4s | %s" % (people, bl, "无解", "-"))
                continue
            rng = random.Random(hash((people, bk)) & 0xFFFF)
            cells = {}
            for m in NAMES:
                freq = Counter()
                for _ in range(per):
                    p = pick(pool, rng, m)
                    freq[p["code"]] += 1
                vals = sorted(freq.values(), reverse=True)
                g = gini(vals)
                t3 = sum(vals[:3]) * 100.0 / sum(vals)
                cov = len(freq) / len(pool) * 100
                summary[m]["g"].append(g)
                summary[m]["t3"].append(t3)
                summary[m]["cov"].append(cov)
                cells[m] = (g, t3, cov)
            print("  %-5d %-8s %4d | G=%.3f top3=%4.1f%% 覆%3.0f%% | G=%.3f top3=%4.1f%% 覆%3.0f%%"
                  % (people, bl, len(pool),
                     cells["M6"][0], cells["M6"][1], cells["M6"][2],
                     cells["M216"][0], cells["M216"][1], cells["M216"][2]))
    print()
    for m in NAMES:
        s = summary[m]
        print("  %-6s 平均 Gini=%.4f  平均 top3 集中度=%.1f%%  平均覆盖率=%.1f%%"
              % (m, statistics.mean(s["g"]), statistics.mean(s["t3"]), statistics.mean(s["cov"])))
    print()
    print("  ★ Gini 越低越均匀；top3 集中度越低说明概率没被挤到少数候选。")
    print()


# ================================================================ E2 理论下界
def e2():
    print("=" * 78)
    print("E2  理论下界：n 个候选要均匀命中，需要多少个原子？")
    print("=" * 78)
    cnt = Counter(sum(t) for t in ALL216)
    print("  %-8s %10s %12s %14s %16s" % ("候选数 n", "理想 1/n", "16档原子够?", "需要的原子数", "三骰提供"))
    print("  " + "-" * 66)
    for n in [1, 2, 4, 6, 8, 12, 16, 24, 34, 42]:
        need = n
        atoms_sum = "16（总和分析）"
        atoms_216 = "216（有序排列）"
        ok16 = "够" if n <= 16 else "不够 ✗"
        # 16 档时最大原子概率 12.5%，若 n>8 则单个原子就会超过 1/n
        if n > 8:
            ok16 = "不够 ✗ (12.5%%>%.1f%%)" % (100.0 / n)
        print("  %-8d %9.1f%% %12s %14d %16s"
              % (n, 100.0 / n, ok16, atoms_216.count("x") and need or need, atoms_216))
    print()
    print("  ★ 结论：三骰「总和」只有 16 个原子，最大原子概率 12.5%（点数10/11/12）。")
    print("    当候选数 n > 8 时，均匀映射在 16 档下【数学上不可能】——")
    print("    单个原子 12.5% > 1/n，必然造成命中概率偏斜。")
    print("    要突破这个下界，必须用 216 个「有序三元组」当原子，")
    print("    这正是用户「三骰排列组合」直觉的真正数学价值。")
    print()


# ================================================================ E3 排列语义
def e3(meals):
    print("=" * 78)
    print("E3  216 种骰面的结构分类 —— 排列维度能承载什么语义")
    print("=" * 78)
    cats = Counter()
    examples = {}
    for t in ALL216:
        s = sorted(t)
        if s[0] == s[2]:
            k = "豹子(三个相同)"
        elif s[0] == s[1] or s[1] == s[2]:
            k = "对子"
        elif s[2] - s[0] == 2 and len(set(s)) == 3:
            k = "顺子(连号)"
        elif s[2] - s[0] == 1 and len(set(s)) == 2:
            k = "相邻对"
        else:
            k = "散牌"
        cats[k] += 1
        examples.setdefault(k, []).append(t)
    for k, v in cats.most_common():
        print("  %-14s %3d 种 (%5.1f%%)  例: %s"
              % (k, v, v * 100.0 / 216,
                 " ".join("%d%d%d" % t for t in examples[k][:6])))
    print()
    print("  5 类结构 → 5 个语义槽，可绑定：")
    print("    豹子 → 全场最贵/加购特调   对子 → 牛/鸡双拼   顺子 → 连锁套餐")
    print("    相邻对 → 固定款           散牌 → 随机款")
    print("  ★ 这让「排列」有了独立于「价位」的语义维度，而不是纯概率颗粒。")
    print()

    # 语义类 × 点数总和 的联合分布
    print("  结构 × 总和 联合分布（看是否互补）：")
    print("  %-14s %s" % ("", " ".join("%5d" % s for s in range(3, 19, 2))))
    byk = {}
    for t in ALL216:
        s = sorted(t)
        if s[0] == s[2]:
            k = "豹子"
        elif s[0] == s[1] or s[1] == s[2]:
            k = "对子"
        elif s[2] - s[0] == 2 and len(set(s)) == 3:
            k = "顺子"
        elif s[2] - s[0] == 1 and len(set(s)) == 2:
            k = "相邻对"
        else:
            k = "散牌"
        byk.setdefault(k, Counter())[sum(t)] += 1
    for k in ["豹子", "对子", "顺子", "相邻对", "散牌"]:
        row = byk.get(k, Counter())
        print("  %-14s %s" % (k, " ".join("%5d" % row.get(s, 0) for s in range(3, 19, 2))))
    print()
    print("  ★ 豹子只在 3/6/9/12/15/18 出现 → 结构与点数【强相关】。")
    print("    若同时用两者，会互相干扰；需要明确主次。")
    print()


# ================================================================ E4 双维度方案
def e4(meals, per=12000):
    print("=" * 78)
    print("E4  候选方案实测：M216 强度阶梯 vs 现状 M6")
    print("=" * 78)
    print("  检验：预算越界 / 忌口违例 / 供餐不足 / 命中均匀性 / 点数↔价格单调性")
    print()
    rows = []
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            pool, deg = DR.build_pool(meals, people, DR.normalize_band(bk), ["不吃辣"])
            if not pool:
                continue
            band = DR.normalize_band(bk)
            rng = random.Random(7788 + people)
            res = {}
            for m in NAMES:
                over = viol = under = 0
                faces, prices = [], []
                freq = Counter()
                for _ in range(per):
                    if m == "M6":
                        f = rng.randint(1, 6)
                        p = pick(pool, rng, m)
                        faces.append(f)
                    else:
                        t = tuple(rng.randint(1, 6) for _ in range(3))
                        p = pick(pool, rng, m)
                        faces.append(sum(t))
                    prices.append(p["total"])
                    freq[p["code"]] += 1
                    if band["hi"] < 10 ** 9 and p["total"] > band["hi"]:
                        over += 1
                    if "辣" in p["name"]:
                        viol += 1
                    if p.get("serves", 1) < people:
                        under += 1
                vals = sorted(freq.values(), reverse=True)
                res[m] = dict(over=over, viol=viol, under=under,
                              gini=gini(vals),
                              top3=sum(vals[:3]) * 100.0 / sum(vals),
                              rho=spearman(faces, prices),
                              util=statistics.mean(prices) / band["hi"] * 100
                              if band["hi"] < 10 ** 9 else 0)
            rows.append((people, bl, len(pool), res))
    print("  %-4s %-8s %3s | %-30s | %-30s" % ("人数", "预算", "池", "M6", "M216"))
    print("  " + "-" * 76)
    for people, bl, npool, res in rows:
        a, b = res["M6"], res["M216"]
        print("  %-4d %-8s %3d | G=%.3f top3=%4.1f%% ρ=%+.3f | G=%.3f top3=%4.1f%% ρ=%+.3f"
              % (people, bl, npool,
                 a["gini"], a["top3"], a["rho"], b["gini"], b["top3"], b["rho"]))
    print()
    tot_over = sum(r[3][m]["over"] for r in rows for m in NAMES)
    tot_viol = sum(r[3][m]["viol"] for r in rows for m in NAMES)
    tot_under = sum(r[3][m]["under"] for r in rows for m in NAMES)
    print("  全场景合计：预算越界 %d | 忌口违例 %d | 供餐不足 %d  （%d 次投掷）"
          % (tot_over, tot_viol, tot_under, len(rows) * per * len(NAMES)))
    g6 = statistics.mean([r[3]["M6"]["gini"] for r in rows])
    g216 = statistics.mean([r[3]["M216"]["gini"] for r in rows])
    t6 = statistics.mean([r[3]["M6"]["top3"] for r in rows])
    t216 = statistics.mean([r[3]["M216"]["top3"] for r in rows])
    print("  平均均匀性：M6 Gini=%.4f top3=%.1f%%  →  M216 Gini=%.4f top3=%.1f%%"
          % (g6, t6, g216, t216))
    print()


def main():
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = DR.meals_of(doc)
    e2()
    e1(meals)
    e3(meals)
    e4(meals)


if __name__ == "__main__":
    main()
