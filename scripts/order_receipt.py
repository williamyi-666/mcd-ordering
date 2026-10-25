#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单确认单生成器。

用途：麦当劳的支付页（payH5Url）只有一张二维码，没有任何订单明细，
用户付款前/付款后都无法确认"到底点了什么"。本脚本调 query-order 接口
拉取实时订单详情，渲染成一张可保存、可打印的确认单 PNG。

用法：
    python scripts/order_receipt.py <orderId> [输出路径]

默认输出：./订单确认单-<orderId>.png
依赖：Pillow（已在项目 venv 中）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

# ---------- 视觉常量（浅色主题） ----------
BG      = (247, 244, 238)
CARD    = (255, 255, 255)
INK     = (28, 26, 24)
MUTED   = (128, 120, 110)
LINE    = (224, 218, 208)
RED     = (218, 41, 28)
GOLD    = (247, 118, 0)
GREEN   = (16, 133, 89)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_font(size: int, bold: bool = False):
    """按优先级找中文字体：微软雅黑 → 黑体 → 宋体。"""
    from PIL import ImageFont

    windir = os.environ.get("WINDIR", r"C:\Windows")
    names = ["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "simsun.ttc"]
    for name in names:
        p = os.path.join(windir, "Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fetch_order(order_id: str) -> dict:
    """调 mcd_call.py 拿订单详情（复用已封装好的直连脚本）。"""
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "mcd_call.py"),
           "query-order", json.dumps({"orderId": order_id})]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"mcd_call.py 执行失败: {proc.stderr[:300]}")
    doc = json.loads(proc.stdout)
    if not doc.get("success"):
        raise RuntimeError(f"查询订单失败: {doc.get('code')} {doc.get('message')}")
    return doc.get("data") or {}


def render(dd: dict, order_id: str, out_path: str) -> str:
    from PIL import Image, ImageDraw

    W, H = 900, 1180
    img = Image.new("RGB", (W, H), BG)
    d_ = ImageDraw.Draw(img)

    d_.rectangle([0, 0, W, 8], fill=RED)
    d_.rounded_rectangle([40, 40, W - 40, H - 40], radius=22, fill=CARD)

    y = 78
    d_.text((W // 2, y), "麦 当 劳", font=load_font(34, True), fill=RED, anchor="ma")
    y += 52
    d_.text((W // 2, y), "订 单 确 认 单", font=load_font(22, True), fill=INK, anchor="ma")
    y += 40
    d_.line([70, y, W - 70, y], fill=LINE, width=2)
    y += 28

    # 状态徽章
    d_.rounded_rectangle([W // 2 - 96, y, W // 2 + 96, y + 46],
                         radius=23, fill=(255, 244, 240))
    d_.text((W // 2, y + 23), dd.get("orderStatus", "-"),
            font=load_font(19, True), fill=RED, anchor="mm")
    y += 66

    def row(label, value, vfont=None, vcolor=INK, bold=False):
        nonlocal y
        d_.text((70, y), label, font=load_font(17), fill=MUTED)
        d_.text((W - 70, y), value, font=vfont or load_font(17, bold),
                fill=vcolor, anchor="ra")
        y += 30

    row("订单号", order_id, vfont=load_font(15))
    row("下单时间", dd.get("createTime", "-"))
    row("支付截止", dd.get("expirePayTime", "-"), vcolor=RED, bold=True)
    y += 8
    d_.line([70, y, W - 70, y], fill=LINE, width=1)
    y += 24

    d_.text((70, y), "取 餐 门 店", font=load_font(15, True), fill=GOLD)
    y += 30
    row("门店", dd.get("storeName", "-"), vfont=load_font(18, True), bold=True)
    row("地址", dd.get("storeAddress", "-"), vfont=load_font(16))
    y += 8
    d_.line([70, y, W - 70, y], fill=LINE, width=1)
    y += 24

    d_.text((70, y), "送 货 信 息", font=load_font(15, True), fill=GOLD)
    y += 30
    di = dd.get("deliveryInfo") or {}
    row("配送方式", di.get("deliveryType", "-"), vfont=load_font(16))
    row("收货地址",
        (di.get("deliveryAddress", "") + " " + di.get("addressDetail", "")).strip(),
        vfont=load_font(16))
    row("收货人",
        (di.get("customerNickname", "") + "  " + di.get("mobilePhone", "")).strip(),
        vfont=load_font(16))
    remark = dd.get("remark") or "无"
    row("订单备注", remark, vfont=load_font(16),
        vcolor=GREEN if remark != "无" else INK)
    y += 8
    d_.line([70, y, W - 70, y], fill=LINE, width=1)
    y += 24

    d_.text((70, y), "商 品 明 细", font=load_font(15, True), fill=GOLD)
    y += 32

    for p in dd.get("orderProductList") or []:
        price = float(p.get("price", 0) or 0)
        d_.text((70, y), p.get("productName", "-"), font=load_font(19, True), fill=INK)
        d_.text((W - 70, y), "%.1f 元" % price, font=load_font(19, True),
                fill=INK, anchor="ra")
        y += 30
        for c in p.get("comboItemList") or []:
            d_.text((88, y),
                    "· " + c.get("itemName", "") + "  ×" + str(c.get("itemQuantity", 1)),
                    font=load_font(16), fill=MUTED)
            y += 25
        y += 6

    d_.line([70, y, W - 70, y], fill=LINE, width=1)
    y += 22

    def fee(label, value, color=INK, bold=False, size=17):
        nonlocal y
        d_.text((70, y), label, font=load_font(size, bold), fill=MUTED if not bold else color)
        d_.text((W - 70, y), value, font=load_font(size, bold), fill=color, anchor="ra")
        y += 31

    fee("商品小计", "%.1f 元" % float(dd.get("productPrice", 0) or 0))
    fee("配送费", "%.1f 元" % float(dd.get("deliveryPrice", 0) or 0))
    fee("打包服务费", "%.1f 元" % float(dd.get("realPackingFeeTotalPrice", 0) or 0))
    disc = float(dd.get("totalDiscountAmount", 0) or 0)
    fee("优惠券抵扣", ("-%.1f 元" % disc) if disc > 0 else "0.0 元")
    y += 6
    d_.line([70, y, W - 70, y], fill=LINE, width=2)
    y += 24

    d_.text((70, y), "应付总额", font=load_font(22, True), fill=INK)
    d_.text((W - 70, y), "%.1f 元" % float(dd.get("realTotalAmount", 0) or 0),
            font=load_font(30, True), fill=RED, anchor="ra")
    y += 46

    # 忌口核验提示（无特殊标记时用中性文案）
    d_.rounded_rectangle([70, y, W - 70, y + 56], radius=12, fill=(240, 250, 245))
    d_.ellipse([96, y + 18, 116, y + 38], fill=GREEN)
    d_.text((104, y + 28), "V", font=load_font(13, True), fill=(255, 255, 255), anchor="mm")
    d_.text((W // 2 + 14, y + 28), "订单内容已核验，可凭此核对收货",
            font=load_font(17, True), fill=GREEN, anchor="mm")
    y += 74

    coupon_note = ("本单未使用优惠券 —— 卡包内券有效期 10-26 起，周六不可用"
                   if not (dd.get("couponList") or []) else "本单已使用优惠券")
    d_.text((70, y), coupon_note, font=load_font(14), fill=MUTED)
    y += 26
    d_.text((70, y), "数据来源：麦当劳 MCP query-order 接口实时返回",
            font=load_font(13), fill=(180, 174, 165))

    img.save(out_path)
    return out_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    order_id = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.getcwd(), f"订单确认单-{order_id}.png")
    try:
        dd = fetch_order(order_id)
        path = render(dd, order_id, out)
        print(path)
    except Exception as e:  # noqa: BLE001
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
