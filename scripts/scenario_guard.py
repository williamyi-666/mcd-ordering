#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
点餐场景参数校验器。

为什么需要它：麦当劳 MCP 服务端**会静默忽略多余参数**（外送传 takeWayCode、
到店传 beCode 都不报错），而且**到店与外送是两套 productCode 体系**——
用错编码会报 60006「商品已售罄」，看起来像库存问题，实际是商品不在该场景菜单里。

这两类错误靠报错兜不住，只能提前拦。本脚本做两件事：

1. 按场景校验 orderType / beType / beCode / takeWayCode 组合
2. 校验商品编码是否属于当前场景的菜单

用法：
    # 校验下单参数
    python scripts/scenario_guard.py --scenario pickup \
        --store-code 1450056 --be-type 1 --items menu_pickup.json

    # 校验商品编码
    python scripts/scenario_guard.py --scenario delivery \
        --store-code 1450056 --be-type 2 --be-code 145005602 \
        --menu menu_delivery.json --items plan.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# ---------- 场景定义（2026-10-24 实测 + 接口 schema 双重确认）----------
# scenario -> (orderType, beType, 是否需要 beCode, 允许的 takeWayCode)
SCENARIOS = {
    "pickup": {
        "label": "到店自取",
        "orderType": 1, "beType": 1,
        "needBeCode": False,
        "takeWayCodes": ["eat-in", "take-in-store", "locker-out"],
        "beCodeSuffix": None,
        "note": "beCode 不传；商品用短码体系（如 1100 巨无霸）",
    },
    "drive_through": {
        "label": "得来速",
        "orderType": 1, "beType": 5,
        "needBeCode": True,
        "takeWayCodes": ["take-dt-quick"],
        "perStore": False,
        "beCodeSuffix": "41",
        "note": "beCode 必传（后缀 41）；商品用短码体系",
    },
    "delivery": {
        "label": "麦乐送（外送）",
        "orderType": 2, "beType": 2,
        "needBeCode": True,
        "takeWayCodes": [],
        "beCodeSuffix": "02",
        "note": "beCode 必传且须用 delivery-query-stores 原值；商品用长码体系；不传 takeWayCode",
    },
    "group": {
        "label": "企业团餐",
        "orderType": 2, "beType": 6,
        "needBeCode": True,
        "takeWayCodes": [],
        "beCodeSuffix": None,
        "note": "beCode 必传；还需 gmServiceCode（普通账号不可用）",
    },
}

# 每个场景的 takeWayCode 合法值
KNOWN_TAKE_WAY = {"eat-in", "take-in-store", "locker-out", "take-dt-quick"}

# ⚠️ takeWayCode 是「每家店自己的」，不能跨店复用（2026-10-24 实测）
# 实测各店 to-store 场景的 takeWayList：
#   1450056 上海食品一店    -> eat-in, take-in-store（店内自提）
#   1450441 上海福州路      -> eat-in, take-in-store
#   1450556 福州路上海书城  -> eat-in, locker-out（店外取餐柜）
#   1450713 华旭国际大厦    -> eat-in, locker-out
#   得来速门店             -> take-dt-quick
# 传错会报 600043「取餐方式code错误，请重新获取」
STORE_TAKE_WAY = {
    "1450056": ["eat-in", "take-in-store"],
    "1450441": ["eat-in", "take-in-store"],
    "1450556": ["eat-in", "locker-out"],
    "1450713": ["eat-in", "locker-out"],
    "1450086": ["eat-in", "locker-out"],
    "1450258": ["eat-in", "locker-out"],
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def meals_of(doc):
    return (doc.get("data") or {}).get("meals") or {}


def check(scenario_key: str, args) -> tuple[bool, list, dict]:
    """返回 (是否通过, 问题列表, 附加信息)。"""
    sc = SCENARIOS.get(scenario_key)
    problems = []
    info = {"scenario": sc["label"] if sc else scenario_key}

    if not sc:
        problems.append(f"未知场景 '{scenario_key}'，可选：{', '.join(SCENARIOS)}")
        return False, problems, info

    # ---- 1. beType 校验
    if args.be_type is not None and args.be_type != sc["beType"]:
        problems.append(
            f"beType 不符：{sc['label']} 应为 {sc['beType']}，传了 {args.be_type}")
    if args.order_type is not None and args.order_type != sc["orderType"]:
        problems.append(
            f"orderType 不符：{sc['label']} 应为 {sc['orderType']}，传了 {args.order_type}")

    # ---- 2. beCode 校验
    if args.be_code:
        if not sc["needBeCode"]:
            problems.append(
                f"{sc['label']} 场景不应传 beCode（服务端会静默忽略，但会误导后续判断）")
        else:
            suffix = sc.get("beCodeSuffix")
            if suffix and not str(args.be_code).endswith(suffix):
                problems.append(
                    f"beCode 后缀可疑：{sc['label']} 期望以 '{suffix}' 结尾，"
                    f"传的是 '{args.be_code}'")
    else:
        if sc["needBeCode"]:
            problems.append(
                f"{sc['label']} 场景必须传 beCode（缺失会报 600048 / 60002）")

    # ---- 3. takeWayCode 校验
    if args.take_way_code:
        if not sc["takeWayCodes"]:
            problems.append(
                f"{sc['label']} 场景不应传 takeWayCode（外送/团餐无取餐方式）")
        elif args.take_way_code not in sc["takeWayCodes"]:
            problems.append(
                f"takeWayCode 取值不合法：{sc['label']} 允许 {sc['takeWayCodes']}，"
                f"传的是 '{args.take_way_code}'")
        elif args.take_way_code not in KNOWN_TAKE_WAY:
            problems.append(f"takeWayCode '{args.take_way_code}' 不是已知取值")
    else:
        if sc["orderType"] == 1:
            problems.append(
                f"{sc['label']} 场景必须传 takeWayCode（缺失会报 600042）。"
                f"先跑 calculate-price，从返回的 takeWayList[].code 里选")

    # ---- 3b. 门店维度的 takeWayCode 校验
    if (args.take_way_code and args.store_code
            and str(args.store_code) in STORE_TAKE_WAY):
        allowed = STORE_TAKE_WAY[str(args.store_code)]
        if args.take_way_code not in allowed:
            problems.append(
                f"门店 {args.store_code} 不支持 takeWayCode='{args.take_way_code}'，"
                f"该店可选：{allowed}。"
                f"**takeWayCode 是每家店自己的，不能跨店复用**（传错报 600043）")

    # ---- 4. 商品编码校验（需要菜单文件）
    if args.menu and args.items:
        menu = meals_of(load_json(args.menu))
        if not menu:
            problems.append("菜单文件里没解析到 meals，无法校验商品编码")
        else:
            plan = load_json(args.items)
            items = plan.get("items") if isinstance(plan, dict) else plan
            codes = [str(i.get("productCode")) for i in (items or [])]
            missing = [c for c in codes if c not in menu]
            if missing:
                problems.append(
                    f"这些商品编码不在当前场景菜单里：{missing}。"
                    f"**到店与外送是两套编码体系**，请用对应场景重新拉菜单")
            else:
                info["itemsChecked"] = len(codes)

    return (len(problems) == 0), problems, info


def main() -> int:
    ap = argparse.ArgumentParser(description="点餐场景参数校验器")
    ap.add_argument("--scenario", required=True, choices=list(SCENARIOS),
                    help="到店渠道")
    ap.add_argument("--order-type", type=int)
    ap.add_argument("--be-type", type=int)
    ap.add_argument("--be-code")
    ap.add_argument("--take-way-code", dest="take_way_code")
    ap.add_argument("--store-code", dest="store_code",
                    help="门店编号 —— 用于校验该店支持的 takeWayCode")
    ap.add_argument("--menu", help="当前场景的菜单 JSON（mcd_call.py 的输出）")
    ap.add_argument("--items", help="方案 JSON（含 items 数组）")
    args = ap.parse_args()

    ok, problems, info = check(args.scenario, args)

    sc = SCENARIOS[args.scenario]
    print(f"场景：{sc['label']}（orderType={sc['orderType']} beType={sc['beType']}）")
    print(f"规则：{sc['note']}")
    if info.get("itemsChecked"):
        print(f"已校验商品编码：{info['itemsChecked']} 个，均在当前场景菜单内 ✓")

    if ok:
        print("\n✓ 参数校验通过")
        return 0

    print("\n✗ 发现问题：")
    for p in problems:
        print("  - " + p)
    return 1


if __name__ == "__main__":
    sys.exit(main())
