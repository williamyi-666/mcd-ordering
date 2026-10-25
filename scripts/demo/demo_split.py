#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连投模式的端到端下单演练：投骰 → 算价 → 下单 → 门禁 → 支付入口。"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.expanduser("~/.workbuddy/skills/mcd-ordering")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import dice_roll as DR  # noqa: E402

PY = sys.executable
CALL = os.path.join(SKILL, "scripts", "mcd_call.py")
STORE, STORE_NAME = "1450713", "麦当劳上海黄浦华旭国际大厦餐厅"
BAND, PEOPLE, CHANNEL = "50-100", 3, "到店自取"
RESTR = ["不吃辣"]


def call(tool, args):
    p = subprocess.run([PY, CALL, tool, json.dumps(args, ensure_ascii=True)],
                       capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"_raw": p.stdout[:300]}


def step(n, t):
    print("\n" + "─" * 62)
    print("  %s" % t)
    print("─" * 62)


# ---------- 0 门店 ----------
step("0", "确认营业门店")
st = call("query-nearby-stores",
          {"beType": 1, "searchType": 2, "city": "上海市", "keyword": "南京路"})
open_stores = [s for s in (st.get("data") or []) if s.get("businessStatus")]
print("  营业中：%s" % "、".join(
    "%s(%s)" % (s["storeCode"], s["storeName"][:14]) for s in open_stores))

# ---------- 1 菜单 ----------
step("1", "拉菜单")
mq = call("query-meals", {"storeCode": STORE, "orderType": 1, "beType": 1})
if not mq.get("success"):
    print("  失败：", mq.get("code"), mq.get("message"))
    sys.exit(1)
meals = DR.meals_of(mq)
print("  单品 %d 个" % len(meals))

# ---------- 2 连投 ----------
step("2", "连投：3 人各掷一次")
serves_map = json.load(open(os.path.join(ROOT, "scripts", "serves_map.json"),
                            encoding="utf-8"))
r = DR.roll_splits(meals, PEOPLE, BAND, RESTR, splits=3,
                   serves_map=serves_map, seed=20261025,
                   channel=CHANNEL, store_code=STORE, defaults={})
if not r["ok"]:
    print("  无解：", r.get("message"))
    sys.exit(2)
print("  单份上限 %.1f 元   候选池 %d 个" % (r["perCap"], r["poolSize"]))
print()
for p in r["picks"]:
    d = p["dice"]
    print("  第%d份  【%d-%d-%d】=%2d点·%-4s → %-24s %5.1f 元"
          % (p["seq"], d[0], d[1], d[2], p["sum"], p["structure"],
             p["name"][:22], p["price"]))
print()
print("  合计 %.1f 元   人均 %.1f 元   %s"
      % (r["total"], r["perCapita"],
         "预算内 ✓" if r["withinBudget"] else "⚠️ 超预算"))
if r["rerollTokens"]:
    print("  🎁 触发「%s」可免费重投" % "、".join(r["rerollTokens"]))

# ---------- 3 算价 ----------
step("3", "算价（真实接口，不消耗下单额度）")
items = [{"productCode": p["code"], "quantity": 1} for p in r["picks"]]
pr = call("calculate-price", {"storeCode": STORE, "orderType": 1, "beType": 1,
                              "items": items, "takeWayCode": "eat-in"})
if not pr.get("success"):
    print("  失败：", pr.get("code"), pr.get("message"))
    sys.exit(3)
dd = pr["data"]
real = dd.get("price", 0) / 100.0
print("  引擎合计  %.1f 元" % r["total"])
print("  接口实算  %.1f 元" % real)
print("  差额      %+.1f 元  %s"
      % (real - r["total"],
         "✓ 一致" if abs(real - r["total"]) < 0.01 else "✗ 不一致"))
twl = [(t.get("code"), t.get("title")) for t in dd.get("takeWayList", [])]
print("  取餐方式  %s" % "、".join("%s(%s)" % t for t in twl))
take_way = twl[0][0] if twl else None

# ---------- 4 下单 ----------
step("4", "创建订单")
or1 = call("create-order", {"storeCode": STORE, "orderType": 1, "beType": 1,
                            "items": items, "takeWayCode": take_way,
                            "needTableware": True})
if not or1.get("success"):
    code = or1.get("code")
    print("  失败：%s %s" % (code, or1.get("message")))
    if code == 600039:
        print()
        print("  ⚠️ 账号级每日下单额度已用尽（跨门店跨渠道共享，取消不释放）。")
        print("     不是报错也不是风控，次日 00:00 重置。")
        print("     演练到此为止；前 3 步（连投 → 算价一致）已真跑通。")
    sys.exit(4)
od = or1["data"]
oid = od.get("orderId")
print("  订单号    %s" % oid)
print("  应付      %.1f 元" % float(od.get("realTotalAmount") or 0))
print("  支付截止  %s" % od.get("expirePayTime"))
print("  payH5Url  %s" % od.get("payH5Url"))

# ---------- 5 门禁 ----------
step("5", "付款前门禁")
from pay_confirm import build_gate, fetch_order, print_gate  # noqa: E402
g = build_gate(fetch_order(oid), oid, expect_total=r["total"],
               restrictions=RESTR, expect_store=STORE, expect_channel=CHANNEL)
print_gate(g, oid)
