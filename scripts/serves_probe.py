#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
供餐人数权威探测 —— 批量拉 query-meal-detail，用饮料 round 的默认数量
作为真实供餐人数（几杯饮料 = 几人份）。

背景（2026-10-24 全量核对 44 个正餐类套餐）：
  名称推断错误 2/44（5%），且都错在「双人餐」上：
    「麦麦周末双人餐」59.5 元 → 名称推断 2 人，真实 1 人
    「开心亲子双人餐」59.5 元 → 名称推断 2 人，真实 1 人
  名称含「四件套/三件套」是【件数】不是【人数】。

判据：query-meal-detail 的 rounds 里「饮料」round 的默认项 quantity。
  ⚠️ query-meal-detail 的参数名是 code（不是 productCode），
     且必须带 storeCode + beType + orderType。

用法:
  python serves_probe.py --store 1450056 --out serves_map.json
  python serves_probe.py --menu menu.json --out serves_map.json
  python serves_probe.py --menu menu.json --out serves_map.json --refresh
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CALLER = os.path.join(SKILL, "scripts", "mcd_call.py")

sys.path.insert(0, os.path.join(SKILL, "scripts"))
from dice_roll import MAIN_KEYWORDS, is_drink_only, meals_of  # noqa: E402


def fetch_detail(code, store, be_type, order_type, timeout=60):
    """拉单个套餐详情，返回原始 dict。"""
    args = {"code": code, "storeCode": store,
            "beType": be_type, "orderType": order_type}
    try:
        p = subprocess.run(
            [sys.executable, CALLER, "query-meal-detail", json.dumps(args)],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        return json.loads(p.stdout)
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def capacity_from_detail(detail_doc) -> int:
    """
    真实供餐人数 = 饮料 round 的默认项 quantity。
    找不到返回 0（表示未知，需回退到名称推断）。
    """
    dd = detail_doc.get("data") or {}
    drinks = 0
    for r in dd.get("rounds", []):
        if "饮料" in r.get("name", ""):
            for ch in r.get("choices", []):
                if ch.get("isDefault") == 1:
                    drinks = max(drinks, int(ch.get("quantity") or 0))
    return drinks


def main() -> int:
    ap = argparse.ArgumentParser(description="供餐人数权威探测")
    ap.add_argument("--menu", help="菜单 JSON（query-meals 输出），直接给出候选 productCode")
    ap.add_argument("--store", default="1450056", help="门店编码")
    ap.add_argument("--be-type", type=int, default=1, help="1=到店 2=外送 5=得来速")
    ap.add_argument("--order-type", type=int, default=1, help="1=到店 2=外送")
    ap.add_argument("--out", default="serves_map.json", help="输出 JSON 路径")
    ap.add_argument("--refresh", action="store_true", help="忽略已有缓存，重新拉取")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not args.menu or not os.path.exists(args.menu):
        print("需要 --menu 指向 query-meals 的输出 JSON", file=sys.stderr)
        return 2

    meals = meals_of(json.load(open(args.menu, encoding="utf-8")))
    targets = [c for c, v in meals.items()
               if any(k in v.get("name", "") for k in MAIN_KEYWORDS)
               and not is_drink_only(v.get("name", ""))]
    print("候选正餐类套餐：%d 个" % len(targets))

    cache = {}
    if os.path.exists(args.out) and not args.refresh:
        try:
            cache = json.load(open(args.out, encoding="utf-8"))
            print("已有缓存 %d 条（--refresh 可强制刷新）" % len(cache))
        except Exception:
            cache = {}

    todo = [c for c in targets if c not in cache]
    if not todo:
        print("全部命中缓存，无需联网")
        return 0
    print("待探测：%d 个" % len(todo))

    def work(code):
        return code, fetch_detail(code, args.store, args.be_type, args.order_type)

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for code, doc in ex.map(work, todo):
            cap = capacity_from_detail(doc)
            if cap > 0:
                results[code] = cap

    cache.update(results)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("已写入 %s（%d 条）" % (args.out, len(cache)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
