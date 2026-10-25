#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验 6 —— 供餐人数权威化。

发现：serves_of() 靠名称关键词推断人数，实测有错：
    「麦麦周末双人餐」   名称含"双人餐" → 推断 2 人，真实 1 人
    「开心亲子双人餐」   名称含"双人餐" → 推断 2 人，真实 1 人
    「巨无霸四件套」     "四件套"不是四人份 → 真实 1 人（碰巧对）
    「全明星双人分享餐八件套」 → 推断 2，真实 2 ✓
    「BFF四宫格小食盘双人餐」   → 推断 2，真实 2 ✓

后果：2 人场景会把 1 人份套餐当成 2 人份放进池 → 骰子选出供餐不足的套餐。

本实验批量拉取全部正餐类的 query-meal-detail，用【饮料 round 的默认 quantity】
作为权威供餐人数，重建池子并对比修正前后。
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
MENU = os.path.join(HERE, "menu_dinein.json")
DETAILS = os.path.join(HERE, "details")
PY = sys.executable
CALLER = os.path.expanduser("~/.workbuddy/skills/mcd-ordering/scripts/mcd_call.py")
STORE = "1450056"


def fetch(code):
    out = os.path.join(DETAILS, code + ".json")
    if os.path.exists(out) and os.path.getsize(out) > 50:
        return code
    try:
        r = subprocess.run(
            [PY, CALLER, "query-meal-detail",
             json.dumps({"code": code, "storeCode": STORE,
                         "beType": 1, "orderType": 1})],
            capture_output=True, text=True, timeout=60)
        with open(out, "w", encoding="utf-8") as f:
            f.write(r.stdout)
    except Exception as e:  # noqa: BLE001
        print("  [warn] %s: %s" % (code, e))
    return code


def main():
    os.makedirs(DETAILS, exist_ok=True)
    doc = json.load(open(MENU, encoding="utf-8"))
    meals = doc["data"]["meals"]

    sys.path.insert(0, os.path.expanduser("~/.workbuddy/skills/mcd-ordering/scripts"))
    import dice_roll as DR

    targets = []
    for code, v in meals.items():
        name = v.get("name", "")
        if not any(k in name for k in DR.MAIN_KEYWORDS):
            continue
        if DR.is_drink_only(name):
            continue
        targets.append(code)
    print("待核实正餐类套餐：%d 个" % len(targets))

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(fetch, targets))
    print("拉取完成")
    print()

    # 解析权威人数
    rows = []
    for code in targets:
        p = os.path.join(DETAILS, code + ".json")
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        dd = d.get("data") or {}
        if not dd:
            continue
        drinks = 0
        rounds = []
        for r in dd.get("rounds", []):
            q = 0
            for c in r.get("choices", []):
                if c.get("isDefault") == 1:
                    q = max(q, int(c.get("quantity") or 0))
            rounds.append((r.get("name", ""), q))
            if "饮料" in r.get("name", ""):
                drinks = max(drinks, q)
        name = meals[code].get("name", "")
        price = float(meals[code].get("currentPrice") or 0)
        guessed = DR.serves_of(name)
        rows.append((code, name, price, guessed, drinks, rounds))

    print("=" * 88)
    print("供餐人数：名称推断 vs 详情权威")
    print("=" * 88)
    print("  %-34s %7s %8s %8s %s" % ("套餐", "价格", "名称推断", "详情权威", "判定"))
    print("  " + "-" * 84)
    wrong = []
    for code, name, price, g, a, rounds in sorted(rows, key=lambda x: x[1]):
        if a == 0:
            continue
        ok = "✓" if g == a else "✗ 不一致"
        if g != a:
            wrong.append((code, name, price, g, a))
        print("  %-34s %7.1f %8d %8d %s"
              % (name[:32], price, g, a, ok))
    print()
    print("  ★ 不一致 %d / %d 个（%.0f%%）"
          % (len(wrong), len([r for r in rows if r[4] > 0]),
             100.0 * len(wrong) / max(len([r for r in rows if r[4] > 0]), 1)))
    for code, name, price, g, a in wrong:
        print("      %-32s %5.1f元  推断%d人 → 真实%d人" % (name[:30], price, g, a))
    print()

    # 权威人数映射
    auth = {r[0]: r[4] for r in rows if r[4] > 0}
    json.dump(auth, open(os.path.join(HERE, "serves_auth.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    print("  权威人数映射已存 serves_auth.json（%d 条）" % len(auth))
    print()

    # 修正前后池子对比
    print("=" * 88)
    print("修正前后候选池对比（4 人 / 2 人场景差异最大）")
    print("=" * 88)
    for people in [1, 2, 3, 4]:
        for bk, bl in [("under50", "50以内"), ("50to100", "50-100"), ("over100", "100+")]:
            band = DR.normalize_band(bk)
            lo, hi = band["lo"], band["hi"]
            no_spicy = True

            def build(use_auth):
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
                    s = auth.get(code, DR.serves_of(name)) if use_auth else DR.serves_of(name)
                    if s == 1:
                        singles.append((code, name, price))
                    if s < people:
                        continue
                    if price < lo or price > hi:
                        continue
                    pool.append((code, name, price, s))
                return pool, singles

            p_old, s_old = build(False)
            p_new, s_new = build(True)
            # 组合兜底后的有效池
            def eff(pool, singles):
                if pool:
                    return pool
                out = []
                for code, name, price in singles:
                    t = round(price * people, 2)
                    if lo <= t <= hi:
                        out.append((code, name, t, 1))
                return out

            eo, en = eff(p_old, s_old), eff(p_new, s_new)
            mark = "  ← 差异" if len(eo) != len(en) else ""
            print("  %d人/%-8s 修正前 %2d 个 | 修正后 %2d 个%s"
                  % (people, bl, len(eo), len(en), mark))
    print()


if __name__ == "__main__":
    main()
