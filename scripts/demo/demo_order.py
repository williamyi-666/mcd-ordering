#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端演示：投骰 → 算价 → 下单 → 付款门禁 → 交付物。"""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.expanduser("~/.workbuddy/skills/mcd-ordering")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import dice_roll as DR  # noqa: E402

PY = sys.executable
CALL = os.path.join(SKILL, "scripts", "mcd_call.py")
STORE = "1450713"
STORE_NAME = "麦当劳上海黄浦华旭国际大厦餐厅"
BAND = "50以内"
PEOPLE = 1
CHANNEL = "到店自取"
RESTR = ["不吃辣"]


def call(tool, args):
    p = subprocess.run([PY, CALL, tool, json.dumps(args, ensure_ascii=True)],
                       capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"_raw": p.stdout, "_err": p.stderr}


def step(n, title):
    print()
    print("─" * 62)
    print("  %d. %s" % (n, title))
    print("─" * 62)


# ---------------------------------------------------------------- 1 投骰
meals = DR.meals_of(json.load(open(os.path.join(HERE, "menu_now.json"),
                                  encoding="utf-8")))
serves_map = json.load(open(os.path.join(ROOT, "scripts", "serves_map.json"),
                            encoding="utf-8"))

step(1, "投骰（三骰 216 级，真随机）")
dice = tuple(random.randint(1, 6) for _ in range(3))
r = DR.roll_food(meals, PEOPLE, BAND, RESTR, dice_mode="triple",
                 serves_map=serves_map, triples=[list(dice)],
                 channel=CHANNEL, store_code=STORE, defaults={})
if not r["ok"]:
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(1)

pick = r["picks"][0]
print("  骰面      %s = %d 点 · %s · %s"
      % ("-".join(map(str, dice)), sum(dice),
         pick["structure"], pick["label"]))
print("  候选池    %d 个" % r["poolSize"])
print("  选中      %s" % pick["name"])
print("  引擎价    %.1f 元" % pick["total"])
if pick.get("memberPrice"):
    print("  会员可省  %.1f 元（原价 %.1f）"
          % (pick["listPrice"] - pick["memberPrice"], pick["listPrice"]))

# ---------------------------------------------------------------- 2 算价
step(2, "算价（calculate-price，不消耗下单额度）")
price_args = {
    "storeCode": STORE, "orderType": 1, "beType": 1,
    "items": [{"productCode": pick["code"], "quantity": 1}],
    "takeWayCode": "eat-in",
}
pr = call("calculate-price", price_args)
if not pr.get("success"):
    print("  算价失败:", pr.get("code"), pr.get("message"))
    sys.exit(1)
dd = pr["data"]
real = dd.get("price", 0) / 100.0
print("  商品价    %.1f 元" % (dd.get("productPrice", 0) / 100.0))
print("  优惠      %.1f 元" % (dd.get("discount", 0) / 100.0))
print("  应付      %.1f 元" % real)
print("  与引擎价  %s" % ("一致 ✓" if abs(real - pick["total"]) < 0.01
                          else "不一致 ✗ (差 %+.1f)" % (real - pick["total"])))
print("  可选取餐方式: %s" % ", ".join(
    "%s(%s)" % (t.get("code"), t.get("title")) for t in dd.get("takeWayList", [])))

# ---------------------------------------------------------------- 3 下单
step(3, "创建订单（create-order）")
# ⚠️ takeWayCode 必须来自算价返回的 takeWayList，不能硬编码 eat-in
#    实测该店只支持 locker-out(外带)，传 eat-in 报 600043
twl = dd.get("takeWayList") or []
take_way = twl[0].get("code") if twl else None
if not take_way:
    print("  算价未返回 takeWayList，无法下单")
    sys.exit(1)
print("  取餐方式  %s（来自 takeWayList，不是硬编码）" % take_way)

order_args = dict(price_args)
order_args["takeWayCode"] = take_way
order_args["needTableware"] = True
or1 = call("create-order", order_args)
if not or1.get("success"):
    code = or1.get("code")
    print("  下单失败: %s %s" % (code, or1.get("message")))
    if code == 600039:
        print()
        print("  ⚠️ 这是账号级每日下单额度用尽（跨门店跨渠道共享，取消不释放）。")
        print("     不是报错，也不是风控 —— 只能等次日 00:00 重置。")
        print("     本次演示到此为止，付款门禁用真实历史订单单独验证。")
    sys.exit(2)

od = or1["data"]
order_id = od.get("orderId")
print("  订单号    %s" % order_id)
print("  应付      %.1f 元" % float(od.get("realTotalAmount") or 0))
print("  支付截止  %s" % od.get("expirePayTime"))
json.dump({"orderId": order_id, "total": float(od.get("realTotalAmount") or 0),
           "name": pick["name"], "dice": list(dice)},
          open(os.path.join(HERE, "demo_order.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ---------------------------------------------------------------- 4 门禁
step(4, "付款前门禁（pay_confirm）")
from pay_confirm import build_gate, fetch_order, print_gate  # noqa: E402
g = build_gate(fetch_order(order_id), order_id,
               expect_total=pick["total"], restrictions=RESTR,
               expect_store=STORE, expect_channel=CHANNEL)
print_gate(g, order_id)

# ---------------------------------------------------------------- 5 交付物
step(5, "交付物")
if g["readyToPay"]:
    qr = subprocess.run([PY, os.path.join(SKILL, "scripts", "fetch_qr.py"),
                         order_id], capture_output=True, text=True,
                        encoding="utf-8")
    print("  二维码：", qr.stdout.strip().splitlines()[-1] if qr.stdout else qr.stderr[:200])
    rc = subprocess.run([PY, os.path.join(SKILL, "scripts", "order_receipt.py"),
                         order_id, os.path.join(ROOT, "docs", "media",
                                                "订单确认单-%s.png" % order_id)],
                        capture_output=True, text=True, encoding="utf-8")
    print("  确认单：", rc.stdout.strip() or rc.stderr[:200])
else:
    print("  ⛔ 门禁未通过，不输出二维码")
