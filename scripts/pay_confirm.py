#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
付款前确认门禁 —— **给支付二维码之前的最后一道关**。

## 为什么必须有这道关

麦当劳的支付页（payH5Url）只有一张二维码，**没有任何订单明细**。
用户在付款页看不到点了什么、付多少，只能凭记忆。一旦付错，
钱已经出去了。

而「投前确认」只能保证"意图对"，不能保证"落地对"：
  - 菜单价与实付价可能不一致（discountType 坑，实测差近一倍）
  - 套餐人数可能被名称误导（「双人餐」其实是 1 人份）
  - 优惠券可能没绑上
  - 门店可能选错/已打烊换店

## 铁律

**未通过本门禁 → 不得输出支付二维码。**

本脚本会：
  1. 拉 query-order 实时明细（不是本地缓存）
  2. 逐项核对：金额 / 商品 / 门店 / 取餐方式 / 忌口 / 优惠
  3. 与预期值比对（骰子或算价阶段给出的金额），不符直接 blocked
  4. 输出必须让用户确认的话术

## 用法

```bash
# 基本核对（下单后、付款前必跑）
python scripts/pay_confirm.py --order <orderId>

# 带预期值（推荐：把算价阶段的金额传进来做交叉校验）
python scripts/pay_confirm.py --order <orderId> --expect-total 36.0 \
    --restriction 不吃辣 --expect-store 1450713 --expect-channel 到店自取

# 同时生成确认单 PNG
python scripts/pay_confirm.py --order <orderId> --receipt 订单确认单.png

# 用户确认后放行（写入放行凭证，再给二维码）
python scripts/pay_confirm.py --order <orderId> --user-confirmed

# 只校验不出话术（脚本内调用）
python scripts/pay_confirm.py --order <orderId> --json
```

退出码：0=可付款 / 1=被拦下 / 2=参数错误
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CALLER = os.path.join(SCRIPT_DIR, "mcd_call.py")

# 金额比对容差（元）—— 一分钱内视为一致
TOL = 0.01


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_order(order_id: str) -> dict:
    """调 query-order 拉实时明细。"""
    proc = subprocess.run(
        [sys.executable, CALLER, "query-order",
         json.dumps({"orderId": order_id})],
        capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        return {"_error": "mcd_call 执行失败: %s" % proc.stderr[:300]}
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_error": "返回非 JSON: %s" % proc.stdout[:300]}
    if not doc.get("success"):
        return {"_error": "%s %s" % (doc.get("code"), doc.get("message"))}
    return doc.get("data") or {}


def build_gate(dd: dict, order_id: str, expect_total: float = None,
               restrictions: list = None, expect_store: str = None,
               expect_channel: str = None) -> dict:
    """
    生成付款前门禁结果。

    返回 {readyToPay, blockers, warnings, checks, summary, mustConfirm}
    """
    blockers = []
    warnings = []
    checks = []

    def chk(name, ok, detail="", skip=False):
        """
        记录一项核对。

        skip=True 表示「订单没返回该字段，无法核实」——
        这种情况只记 warning，**不算阻断**：字段缺失是接口问题，不是订单错。
        """
        if skip:
            checks.append({"item": name, "ok": True, "skipped": True,
                           "detail": detail})
            warnings.append("%s：%s（未阻断，请自行确认）" % (name, detail))
            return True
        checks.append({"item": name, "ok": bool(ok), "detail": detail})
        if not ok:
            blockers.append("%s：%s" % (name, detail))
        return ok

    if not dd or dd.get("_error"):
        return {
            "readyToPay": False,
            "blockers": ["订单查询失败：%s" % (dd or {}).get("_error", "空返回")],
            "warnings": [], "checks": [],
            "summary": {}, "mustConfirm": [],
        }

    products = dd.get("orderProductList") or []
    total = _f(dd.get("realTotalAmount"))
    product_price = _f(dd.get("productPrice"))
    delivery = _f(dd.get("deliveryPrice"))
    packing = _f(dd.get("realPackingFeeTotalPrice"))
    discount = _f(dd.get("totalDiscountAmount"))
    store_name = dd.get("storeName") or ""
    status = dd.get("orderStatus") or ""
    expire = dd.get("expirePayTime") or ""
    coupon_list = dd.get("couponList") or []

    # ---- 1. 商品明细必须非空
    chk("商品明细", len(products) > 0,
        "%d 项" % len(products) if products else "订单里没有商品")

    # ---- 2. 应付金额必须 > 0
    chk("应付金额", total > 0,
        "%.2f 元" % total if total > 0 else "应付为 %.2f 元，不正常" % total)

    # ---- 3. 金额勾稽：小计 + 配送 + 打包 - 优惠 == 应付
    calc = round(product_price + delivery + packing - discount, 2)
    balance = abs(calc - total) < TOL
    chk("费用勾稽", balance,
        ("小计%.2f + 配送%.2f + 打包%.2f - 优惠%.2f = %.2f"
         % (product_price, delivery, packing, discount, calc)) if balance
        else ("小计%.2f + 配送%.2f + 打包%.2f - 优惠%.2f = %.2f，与应付 %.2f 不符"
              % (product_price, delivery, packing, discount, calc, total)))

    # ---- 4. 与预期金额比对（防价格口径坑）
    if expect_total is not None:
        same = abs(total - expect_total) < TOL
        chk("金额与预期一致", same,
            ("%.2f 元，与预期一致" % total) if same
            else ("预期 %.2f 元，实际 %.2f 元（差 %+.2f）"
                  % (expect_total, total, total - expect_total)))

    # ---- 5. 门店一致性
    # ⚠️ 实测：到店自取订单 query-order **不返回 storeCode**，只有 storeName。
    #    此时无法用编码核实，只能标记为「未核实」，不能判失败。
    if expect_store:
        sc = dd.get("storeCode") or ""
        if sc:
            hit = expect_store in sc or expect_store in store_name
            chk("门店一致", hit,
                ("%s / %s" % (sc, store_name)) if hit
                else ("预期门店 %s，订单是 %s / %s"
                      % (expect_store, sc, store_name)))
        elif store_name:
            chk("门店一致", True,
                "订单未返回门店编码，按名称核对：%s" % store_name, skip=True)
        else:
            chk("门店一致", False, "订单既无门店编码也无名称，无法核实")

    # ---- 6. 取餐方式
    # ⚠️ 实测字段：到店单是 `takeWay`（"堂食"/"外带"），外送单在 deliveryInfo。
    if expect_channel:
        di = dd.get("deliveryInfo") or {}
        parts = [
            dd.get("takeWay") or "",
            dd.get("takeWayName") or "",
            dd.get("takeWayCode") or "",
            di.get("deliveryType") or "",
            di.get("deliveryName") or "",
        ]
        text = " ".join(p for p in parts if p).strip()
        if not text:
            chk("取餐方式一致", True, "订单未返回取餐方式字段", skip=True)
        else:
            hit = any(k in text for k in _channel_keys(expect_channel))
            chk("取餐方式一致", hit,
                text if hit
                else ("预期「%s」，订单是「%s」" % (expect_channel, text)))

    # ---- 7. 忌口核验（订单里带辣但用户要求不吃辣）
    if restrictions:
        need_no_spicy = any("辣" in r for r in restrictions)
        if need_no_spicy:
            spicy = [p.get("productName", "") for p in products
                     if "辣" in (p.get("productName") or "")]
            chk("忌口（不吃辣）", not spicy,
                "全部不含辣" if not spicy
                else ("含辣商品：%s" % "、".join(spicy)))

    # ---- 8. 支付时限
    if expire:
        try:
            exp = datetime.datetime.strptime(expire, "%Y-%m-%d %H:%M:%S")
            left = (exp - datetime.datetime.now()).total_seconds() / 60
            chk("支付时限", left > 0,
                ("剩余 %.1f 分钟" % left) if left > 0
                else ("已于 %s 过期（订单 15 分钟有效）" % expire))
            if 0 < left < 5:
                warnings.append("距支付截止仅剩 %.1f 分钟，请立即付款" % left)
        except Exception:  # noqa: BLE001
            warnings.append("支付截止时间格式异常：%s" % expire)

    # ---- 9. 订单状态
    if status:
        bad = "取消" in status or "已关闭" in status
        chk("订单状态", not bad,
            status if not bad else ("订单状态为「%s」，无法付款" % status))

    # ---- 优惠券提示
    if not coupon_list and discount <= 0:
        warnings.append("本单未使用优惠券（一次只能用一张，确认是否漏用）")

    summary = {
        "orderId": order_id,
        "status": status,
        "storeName": store_name,
        "storeAddress": dd.get("storeAddress") or "",
        "expirePayTime": expire,
        "products": [{
            "name": p.get("productName", ""),
            "quantity": p.get("quantity", 1),
            "price": _f(p.get("price")),
            "comboItems": [{
                "name": c.get("itemName", ""),
                "quantity": c.get("itemQuantity", 1),
            } for c in (p.get("comboItemList") or [])],
        } for p in products],
        "productPrice": product_price,
        "deliveryPrice": delivery,
        "packingFee": packing,
        "discount": discount,
        "total": total,
        "couponUsed": bool(coupon_list) or discount > 0,
        "remark": dd.get("remark") or "",
    }

    must_confirm = []
    if not blockers:
        must_confirm = [
            "请核对：%s" % "、".join(
                "%s×%d" % (p["name"], p["quantity"]) for p in summary["products"]),
            "应付总额：%.2f 元" % total,
            "取餐门店：%s" % (store_name or "-"),
            "确认无误后再付款，回复「确认付款」我才发支付码。",
        ]

    return {
        "readyToPay": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "summary": summary,
        "mustConfirm": must_confirm,
    }


def _channel_keys(channel: str) -> list:
    """把渠道标签映射成订单里可能出现的文字线索。"""
    c = str(channel)
    if "外送" in c or "麦乐送" in c or "到家" in c:
        return ["外送", "配送", "麦乐送", "到家", "delivery"]
    if "得来速" in c or "DT" in c.upper():
        return ["得来速", "车道", "drive", "dt"]
    return ["自取", "到店", "外带", "堂食", "eat-in", "take"]


def print_gate(g: dict, order_id: str) -> None:
    print("=" * 60)
    print("🔒 付款前确认门禁")
    print("=" * 60)
    if not g["checks"] and g["blockers"]:
        for b in g["blockers"]:
            print("  ✗ %s" % b)
        return
    for c in g["checks"]:
        if c.get("skipped"):
            mark = "－"
        else:
            mark = "✓" if c["ok"] else "✗"
        print("  %s %-14s %s" % (mark, c["item"], c["detail"]))
    for w in g["warnings"]:
        print("  ⚠️  %s" % w)
    print()
    s = g["summary"]
    if s:
        print("  ── 订单明细 ─────────────────────────────")
        print("  订单号  %s" % order_id)
        print("  门店    %s" % s.get("storeName", "-"))
        if s.get("storeAddress"):
            print("  地址    %s" % s["storeAddress"])
        if s.get("expirePayTime"):
            print("  支付截止 %s" % s["expirePayTime"])
        print()
        for p in s["products"]:
            print("  %s  ×%d   %.1f 元"
                  % (p["name"], p["quantity"], p["price"]))
            for c in p["comboItems"]:
                print("      · %s ×%d" % (c["name"], c["quantity"]))
        print()
        print("  商品小计   %.1f 元" % s["productPrice"])
        if s["deliveryPrice"]:
            print("  配送费     %.1f 元" % s["deliveryPrice"])
        if s["packingFee"]:
            print("  打包费     %.1f 元" % s["packingFee"])
        if s["discount"]:
            print("  优惠抵扣  -%.1f 元" % s["discount"])
        print("  ────────────────────────────────────────")
        print("  应付总额   %.1f 元" % s["total"])
        print()
    print("=" * 60)
    if g["readyToPay"]:
        print("  ✅ 可以付款")
        for m in g["mustConfirm"]:
            print("  · %s" % m)
    else:
        print("  ⛔ 被拦下，**不得输出支付二维码**")
        print()
        for b in g["blockers"]:
            print("  · %s" % b)
        print()
        print("  请先解决以上问题（改单 / 换店 / 重新下单）再付款。")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="付款前确认门禁")
    ap.add_argument("--order", required=True, help="订单号 orderId")
    ap.add_argument("--expect-total", type=float,
                    help="预期应付金额（元），与订单实付比对")
    ap.add_argument("--expect-store", help="预期门店编码")
    ap.add_argument("--expect-channel", help="预期取餐方式：到店自取 / 麦乐送 / 得来速")
    ap.add_argument("--restriction", nargs="*", default=None, help="忌口，如 不吃辣")
    ap.add_argument("--receipt", help="同时生成确认单 PNG 到该路径")
    ap.add_argument("--user-confirmed", action="store_true",
                    help="标记用户已确认（写入放行凭证）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    dd = fetch_order(args.order)
    g = build_gate(dd, args.order,
                   expect_total=args.expect_total,
                   restrictions=args.restriction,
                   expect_store=args.expect_store,
                   expect_channel=args.expect_channel)

    if args.receipt and g["readyToPay"]:
        try:
            sys.path.insert(0, SCRIPT_DIR)
            from order_receipt import render
            path = render(dd, args.order, args.receipt)
            g["receiptPath"] = path
        except Exception as e:  # noqa: BLE001
            g["warnings"].append("确认单生成失败：%s" % e)

    if args.user_confirmed and g["readyToPay"]:
        stamp = {
            "orderId": args.order,
            "confirmedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": g["summary"].get("total"),
            "products": [p["name"] for p in g["summary"].get("products", [])],
            "receiptPath": g.get("receiptPath"),
        }
        out = os.path.join(os.path.dirname(SCRIPT_DIR), "config",
                           "pay_confirm_%s.json" % args.order)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(stamp, f, ensure_ascii=False, indent=2)
        g["payToken"] = out
        g["mayIssueQr"] = True

    if args.json:
        print(json.dumps(g, ensure_ascii=False, indent=2))
    else:
        print_gate(g, args.order)
        if g.get("receiptPath"):
            print("\n  确认单：%s" % g["receiptPath"])
        if g.get("payToken"):
            print("  放行凭证：%s" % g["payToken"])
        print()
        print(json.dumps(g, ensure_ascii=False, indent=2))

    return 0 if g["readyToPay"] else 1


if __name__ == "__main__":
    sys.exit(main())
