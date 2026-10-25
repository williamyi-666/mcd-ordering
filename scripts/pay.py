#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
付款闭环 —— 门禁 → 支付入口 → 等支付结果 → 确认单。

## 它把原来散着的三步收成一条命令

之前要手动跑：pay_confirm.py → fetch_qr.py → order_receipt.py，
中间还得自己判断「用户到底付了没」。本脚本一次做完：

  1. 跑付款门禁（9 项核对，不过就停）
  2. 按场景交付支付入口
       电脑前 → 渲染二维码 PNG
       手机上 → 直接给 payH5Url（--mobile）
  3. 轮询订单状态，等支付结果（--wait）
  4. 付成功才生成订单确认单

## 支付链路（实测每一环）

  payH5Url = https://m.mcd.cn/mcp/scanToPay?orderId=<id>
    → 手机端 H5 单页应用
    → 页内二维码内容是 https://m.mcd.cn/mcp/jumpToApp?orderId=<id>
    → jumpToApp → mcdapp:// scheme → 唤起麦当劳 APP 收银台

MCP 35 个工具里**没有任何支付工具**，只有 payH5Url / payId。
这条链路**不支持小程序支付**（bundle 里 launchMiniProgram / weixin:// 出现次数为 0，
只有 wx-open-launch-app 用于唤起 APP）。不要臆造小程序路径。

## 订单状态码（实测）

| status | orderStatus | 含义 |
|---|---|---|
| 10 | 待支付 | 可以付款 |
| 60 | 已取消 | 超时自动取消 / 主动取消 |
| 其他 | 见文案 | 以 orderStatus 文案为准，未知码不猜 |

订单 **15 分钟**内必须付款，超时服务端自动取消（status=60）。

## 用法

```bash
# 门禁 + 二维码（电脑前）
python scripts/pay.py --order <orderId> --expect-total 27.9

# 手机上：直接给 H5 链接
python scripts/pay.py --order <orderId> --mobile

# 交付入口后等 5 分钟，付成功自动出确认单
python scripts/pay.py --order <orderId> --wait 300

# 只跑门禁，不给支付入口
python scripts/pay.py --order <orderId> --gate-only

# 纯 JSON（给上层调用）
python scripts/pay.py --order <orderId> --json
```

退出码：0=门禁通过且已交付 / 1=门禁未过 / 2=参数错误 /
        3=等待超时仍未付款 / 4=订单已取消或关闭
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from pay_confirm import build_gate, fetch_order  # noqa: E402

PAY_URL = "https://m.mcd.cn/mcp/scanToPay?orderId={order_id}"
JUMP_URL = "https://m.mcd.cn/mcp/jumpToApp?orderId={order_id}"

# 实测状态码
STATUS_KNOWN = {
    "10": "待支付",
    "60": "已取消",
}

# 文案关键词
PAID_HINTS = ["已支付", "制作中", "已完成", "待取餐", "已取餐", "配送中", "已送达"]
FAIL_HINTS = ["已取消", "已关闭", "已退款", "已失效"]


def classify(dd: dict) -> dict:
    """
    判定订单处于哪个阶段。

    优先用 orderStatus 文案（人写的，最可靠）；
    status 数字码只做辅助 —— 未知码不猜，标 unknown 让调用方决策。
    返回 {phase, status, text, known}
      phase: pending | paid | failed | unknown
    """
    text = str(dd.get("orderStatus") or "")
    code = str(dd.get("status") or "")

    if any(h in text for h in FAIL_HINTS) or code == "60":
        return {"phase": "failed", "status": code, "text": text,
                "known": True}
    if any(h in text for h in PAID_HINTS):
        return {"phase": "paid", "status": code, "text": text,
                "known": True}
    if "待支付" in text or code == "10":
        return {"phase": "pending", "status": code, "text": text,
                "known": True}
    return {"phase": "unknown", "status": code, "text": text, "known": False}


def pay_url(order_id: str) -> str:
    return PAY_URL.format(order_id=order_id)


def jump_url(order_id: str) -> str:
    return JUMP_URL.format(order_id=order_id)


def make_qr(order_id: str, out_path: str = None):
    """渲染支付二维码 PNG（复用 fetch_qr.py）。失败返回 (None, 原因)。"""
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "fetch_qr.py"), order_id]
    if out_path:
        cmd.append(out_path)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", timeout=180)
    except subprocess.TimeoutExpired:
        return None, "渲染超时"
    path = (p.stdout or "").strip().splitlines()
    path = path[-1] if path else ""
    if p.returncode == 0 and path and os.path.exists(path):
        return path, None
    return None, (p.stderr or "").strip()[:200] or "渲染失败"


def make_receipt(order_id: str, out_path: str):
    """生成订单确认单 PNG（复用 order_receipt.py）。"""
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "order_receipt.py"),
             order_id, out_path],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        out = (p.stdout or "").strip()
        if p.returncode == 0 and out and os.path.exists(out):
            return out, None
        return None, (p.stderr or "").strip()[:200]
    except subprocess.TimeoutExpired:
        return None, "生成超时"


def wait_paid(order_id: str, timeout: int, interval: int,
              verbose: bool = True) -> dict:
    """
    轮询订单状态直到付款成功 / 失败 / 超时。

    返回 {phase, waited, polls, last, summary}
    """
    t0 = time.time()
    polls = 0
    last = {}
    while True:
        polls += 1
        dd = fetch_order(order_id)
        if dd.get("_error"):
            last = {"phase": "unknown", "text": dd["_error"], "status": ""}
        else:
            last = classify(dd)
        waited = round(time.time() - t0, 1)

        if last["phase"] == "paid":
            if verbose:
                print("  ✓ 已支付（%s，用时 %.0f 秒）"
                      % (last["text"], waited))
            return {"phase": "paid", "waited": waited, "polls": polls,
                    "last": last, "summary": dd}
        if last["phase"] == "failed":
            if verbose:
                print("  ✗ %s（用时 %.0f 秒）"
                      % (last["text"] or "订单已失效", waited))
            return {"phase": "failed", "waited": waited, "polls": polls,
                    "last": last, "summary": dd}
        if waited >= timeout:
            if verbose:
                print("  … 等待 %.0f 秒仍未支付（当前：%s）"
                      % (waited, last["text"] or "待支付"))
            return {"phase": "timeout", "waited": waited, "polls": polls,
                    "last": last, "summary": dd}

        if verbose:
            print("  · %s　已等 %.0f 秒　每 %d 秒查一次"
                  % (last["text"] or "待支付", waited, interval))
        time.sleep(interval)


def print_entry(order_id: str, mobile: bool, qr_path, qr_err) -> None:
    print()
    print("  ── 支付入口 ─────────────────────────────")
    print("  H5 链接  %s" % pay_url(order_id))
    print("  跳转内容  %s" % jump_url(order_id))
    if mobile:
        print()
        print("  📱 在手机上直接打开上面的 H5 链接，")
        print("     在微信里打开可一键唤起麦当劳 APP 收银台（比扫码顺）")
    elif qr_path:
        print("  二维码    %s" % qr_path)
        print()
        print("  💻 电脑前：手机微信扫上面这张二维码")
    else:
        print()
        print("  ⚠️  二维码渲染失败（%s）" % (qr_err or "未知原因"))
        print("     改用手动方式：把 H5 链接发到手机，用微信打开")


def main() -> int:
    ap = argparse.ArgumentParser(description="付款闭环（门禁 → 入口 → 结果）")
    ap.add_argument("--order", required=True, help="订单号 orderId")
    ap.add_argument("--expect-total", type=float,
                    help="预期应付金额（元），与订单实付比对")
    ap.add_argument("--expect-store", help="预期门店编码")
    ap.add_argument("--expect-channel", help="预期取餐方式：到店自取 / 麦乐送 / 得来速")
    ap.add_argument("--restriction", nargs="*", default=None, help="忌口，如 不吃辣")
    ap.add_argument("--mobile", action="store_true",
                    help="手机场景：只给 H5 链接，不渲染二维码")
    ap.add_argument("--gate-only", action="store_true",
                    help="只跑门禁，不交付支付入口")
    ap.add_argument("--wait", type=int, default=0,
                    help="交付入口后等待支付结果的秒数（0=不等待）")
    ap.add_argument("--interval", type=int, default=5,
                    help="轮询间隔秒数（默认 5）")
    ap.add_argument("--receipt", help="支付成功后生成确认单 PNG 到该路径")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    out = {"orderId": args.order, "paid": False, "stages": {}}

    # ---------- 1 门禁 ----------
    dd = fetch_order(args.order)
    g = build_gate(dd, args.order,
                   expect_total=args.expect_total,
                   restrictions=args.restriction,
                   expect_store=args.expect_store,
                   expect_channel=args.expect_channel)
    out["stages"]["gate"] = {"passed": g["readyToPay"],
                             "blockers": g["blockers"]}
    out["summary"] = g.get("summary") or {}

    if not args.json:
        print("=" * 60)
        print("💳 付款闭环")
        print("=" * 60)
        for c in g["checks"]:
            print("  %s %-14s %s" % ("✓" if c["ok"] else "✗",
                                     c["item"], c["detail"]))
        for w in g["warnings"]:
            print("  ⚠️  %s" % w)

    if not g["readyToPay"]:
        out["error"] = "gate_blocked"
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print()
            print("  ⛔ 门禁未通过，不交付支付入口：")
            for b in g["blockers"]:
                print("     · %s" % b)
            print()
        return 1

    if args.gate_only:
        out["stages"]["entry"] = {"skipped": True}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print()
            print("  ✅ 门禁通过（--gate-only，未交付支付入口）")
            print()
        return 0

    # ---------- 2 支付入口 ----------
    qr_path = qr_err = None
    if not args.mobile:
        default_qr = os.path.join(os.getcwd(), "支付二维码-%s.png" % args.order)
        qr_path, qr_err = make_qr(args.order, default_qr)

    out["stages"]["entry"] = {
        "payUrl": pay_url(args.order),
        "jumpUrl": jump_url(args.order),
        "qrPath": qr_path,
        "qrError": qr_err,
        "mobile": args.mobile,
    }

    if not args.json:
        print_entry(args.order, args.mobile, qr_path, qr_err)

    # ---------- 3 等支付结果 ----------
    if args.wait > 0:
        if not args.json:
            print()
            print("  ── 等待支付（最多 %d 秒）────────────────" % args.wait)
        w = wait_paid(args.order, args.wait, args.interval,
                      verbose=not args.json)
        out["stages"]["wait"] = {"phase": w["phase"], "waited": w["waited"],
                                 "polls": w["polls"], "status": w["last"]}
        if w["phase"] == "timeout":
            out["error"] = "pay_timeout"
            if args.json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                print()
                print("  ⏳ 仍未支付。订单 15 分钟内有效，超时会被取消。")
                print("     可以再跑一次本命令继续等，或让用户重新下单。")
                print()
            return 3
        if w["phase"] == "failed":
            out["error"] = "order_failed"
            if args.json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                print()
                print("  ⛔ 订单已失效（取消/关闭），不能再付款。需要重新下单。")
                print()
            return 4
        out["paid"] = True
    else:
        cur = classify(dd)
        out["paid"] = cur["phase"] == "paid"

    # ---------- 4 确认单 ----------
    if out["paid"]:
        path = args.receipt or os.path.join(
            os.getcwd(), "订单确认单-%s.png" % args.order)
        rp, rerr = make_receipt(args.order, path)
        out["stages"]["receipt"] = {"path": rp, "error": rerr}
        if not args.json:
            print()
            if rp:
                print("  📄 订单确认单：%s" % rp)
            else:
                print("  ⚠️  确认单生成失败：%s" % (rerr or "未知"))
            print()

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        if out["paid"]:
            print("  ✅ 已付款，流程结束")
        else:
            print("  ⏳ 已交付支付入口，等待用户付款")
            print("     付款完成后再跑一次：")
            print("     python scripts/pay.py --order %s --wait 120" % args.order)
        print("=" * 60)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
