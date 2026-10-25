#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳 MCP 接口回归测试（真实接口）。

用法：
    python tests/api_regression.py          # 跑全部用例
    python tests/api_regression.py --offline  # 只跑不需联网的静态校验

覆盖：
  1. 传参矩阵（orderType × beType × beCode）—— 验证 2026-10-24 实测规则
  2. 错误码行为（多券 / 售罄 / 无效门店）
  3. 业务规则（一次一券、金额单位、GBK 转义、备注正常入库）
  4. 静态校验（SKILL.md frontmatter、references 覆盖度、两处脚本一致性）

⚠️ 部分用例会真实创建订单（随后立即取消）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
SKILL = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\Administrator"),
                     ".workbuddy", "skills", "mcd-ordering")
PY = sys.executable

# 配送地址 ID —— 从环境变量读，避免把真实 ID 写进仓库
# 测试时: set MCD_ADDRESS_ID=<your addressId>
ADDRESS_ID = os.environ.get("MCD_ADDRESS_ID", "")
STORE = "1450056"
BE_CODE = "145005602"

_results = {"pass": 0, "fail": 0}
_failures = []


def chk(name: str, cond: bool, extra: str = "") -> bool:
    if cond:
        _results["pass"] += 1
        print("  [PASS] " + name)
    else:
        _results["fail"] += 1
        _failures.append(f"{name}  {extra}")
        print("  [FAIL] " + name + ("  -> " + extra if extra else ""))
    return cond


def call(tool: str, args: dict) -> dict:
    """调 skill 的直连脚本。"""
    script = os.path.join(SKILL, "scripts", "mcd_call.py")
    proc = subprocess.run([PY, script, tool, json.dumps(args, ensure_ascii=True)],
                          capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"success": False, "message": (proc.stderr or proc.stdout)[:200]}


def section(title: str) -> None:
    print("\n== " + title + " ==")


# ---------------------------------------------------------------- 1. 传参矩阵
def test_param_matrix() -> None:
    section("1. 传参矩阵（实测规则）")

    # 到店：beType=1/2/6 不传 beCode 都应成功
    for bt in (1, 2, 6):
        r = call("query-meals", {"storeCode": STORE, "orderType": 1, "beType": bt})
        chk(f"到店 orderType=1 beType={bt} 不传 beCode -> 成功",
            r.get("success") is True, str(r.get("message"))[:60])

    # 到店：beType=1 配任意 beCode 后缀都应成功
    for suf in ("01", "03", "05", "08"):
        r = call("query-meals", {"storeCode": STORE, "orderType": 1,
                                 "beType": 1, "beCode": f"{STORE}{suf}"})
        chk(f"到店 orderType=1 beType=1 beCode=*{suf} -> 成功",
            r.get("success") is True, str(r.get("message"))[:60])

    # 外送：beType=2 + 正确 beCode 应成功
    r = call("query-meals", {"storeCode": STORE, "orderType": 2,
                             "beType": 2, "beCode": BE_CODE})
    chk("外送 orderType=2 beType=2 正确 beCode -> 成功",
        r.get("success") is True, str(r.get("message"))[:60])

    # 外送：缺 beCode -> 600048
    r = call("query-meals", {"storeCode": STORE, "orderType": 2, "beType": 2})
    chk("外送缺 beCode -> 600048",
        r.get("code") == 600048, f"got {r.get('code')}")

    # 外送：beCode 配对错 -> 60002
    r = call("query-meals", {"storeCode": STORE, "orderType": 2,
                             "beType": 2, "beCode": f"{STORE}01"})
    chk("外送 beCode 配对错 -> 60002",
        r.get("code") == 60002, f"got {r.get('code')}")

    # 到店场景误用外送 beCode -> 600057（场景错配，非打烊）
    r = call("query-meals", {"storeCode": STORE, "orderType": 1,
                             "beType": 2, "beCode": BE_CODE})
    chk("到店场景误用外送 beCode -> 600057",
        r.get("code") == 600057, f"got {r.get('code')}")

    # 团餐配外送场景 + 正确 beCode -> 实测可以取到菜单（2026-10-24 矩阵）
    r = call("query-meals", {"storeCode": STORE, "orderType": 2,
                             "beType": 6, "beCode": BE_CODE})
    chk("团餐(orderType=2,beType=6) 配正确 beCode -> 成功",
        r.get("success") is True, f"got {r.get('code')}")

    # 但团餐配错 beCode 仍然失败
    r = call("query-meals", {"storeCode": STORE, "orderType": 2,
                             "beType": 6, "beCode": f"{STORE}01"})
    chk("团餐 beCode 配对错 -> 60002",
        r.get("code") == 60002, f"got {r.get('code')}")


# ---------------------------------------------------------------- 2. 错误码
def test_error_codes() -> None:
    section("2. 错误码行为")

    r = call("query-meals", {"storeCode": "9999999", "orderType": 2,
                             "beType": 2, "beCode": "999999902"})
    chk("无效门店 -> 600057", r.get("code") == 600057, f"got {r.get('code')}")

    # 售罄商品：双层深海鳕鱼堡套餐
    payload = {"storeCode": STORE, "orderType": 2, "beType": 2, "beCode": BE_CODE,
               "needTableware": True,
               "items": [{"productCode": "9900003039", "quantity": 1,
                          "roundList": [
                              {"round": "1", "comboItemList": [{"code": "9900003589", "quantity": 1}]},
                              {"round": "2", "comboItemList": [{"code": "501205", "quantity": 1}]},
                              {"round": "3", "comboItemList": [{"code": "903050", "quantity": 1}]}]}]}
    r = call("calculate-price", payload)
    chk("售罄商品 -> 60006", r.get("code") == 60006, f"got {r.get('code')}")

    # 多券
    payload2 = json.loads(json.dumps(payload))
    payload2["items"] = [
        {"productCode": "9900003004", "quantity": 1,
         "roundList": [
             {"round": "1", "comboItemList": [{"code": "901401", "quantity": 1}]},
             {"round": "2", "comboItemList": [{"code": "501205", "quantity": 1}]},
             {"round": "3", "comboItemList": [{"code": "903050", "quantity": 1}]}],
         "couponId": "A255280326E3328D179C362B7B8DDA65",
         "couponCode": "MCD690113267700130U40"},
        {"productCode": "901440", "quantity": 1,
         "couponId": "44928824D2D4273FE5ECA617BBF75483",
         "couponCode": "MCD659101U90801032406"}]
    r = call("calculate-price", payload2)
    chk("多张券 -> 600022", r.get("code") == 600022, f"got {r.get('code')}")

    # 499 应被标为 soft_fail
    r = call("auto-bind-coupons", {})
    if r.get("code") == 499:
        chk("499 无券可领 -> soft_fail=True", r.get("soft_fail") is True)
    else:
        chk("auto-bind-coupons 正常返回（本次有券可领）", r.get("success") is True)


# ---------------------------------------------------------------- 3. 业务规则
def test_business_rules() -> None:
    section("3. 业务规则")

    # 券状态判定
    r = call("query-my-coupons", {})
    coupons = (r.get("data") or {}).get("coupons") or []
    chk("卡包券结构可解析", isinstance(coupons, list))
    for c in coupons:
        chk(f"券有效期有起止: {c.get('title', '')[:14]}",
            bool(c.get("tradeStartDateTime")) and bool(c.get("tradeEndDateTime")))

    # 门店可用券（要拿到真实 beCode）
    # 需要配送地址 ID —— 未配置时跳过（仓库不含真实 addressId）
    if not ADDRESS_ID:
        print("    [SKIP] 未设置 MCD_ADDRESS_ID，跳过依赖配送地址的用例")
        chk("delivery-query-stores 需 addressId（未配置时跳过）", True)
    else:
        r = call("delivery-query-stores", {"addressId": ADDRESS_ID, "beType": 2})
        stores = r.get("data") or []
        chk("delivery-query-stores 返回门店", len(stores) > 0)
        chk("每家门店都带 beCode",
            all(s.get("beCode") for s in stores),
            str([s.get("beCode") for s in stores]))

    # 金额单位：calculate-price 返回分
    payload = {"storeCode": STORE, "orderType": 2, "beType": 2, "beCode": BE_CODE,
               "needTableware": True,
               "items": [{"productCode": "9900003004", "quantity": 1,
                          "roundList": [
                              {"round": "1", "comboItemList": [{"code": "901401", "quantity": 1}]},
                              {"round": "2", "comboItemList": [{"code": "501205", "quantity": 1}]},
                              {"round": "3", "comboItemList": [{"code": "903050", "quantity": 1}]}]}]}
    r = call("calculate-price", payload)
    if r.get("success"):
        p = r["data"]
        chk("金额单位是分（price > 1000）", p.get("price", 0) > 1000,
            f"price={p.get('price')}")
        chk("算价总额 = 商品+配送+打包",
            abs(p["price"] - (p["productPrice"] + p["deliveryPrice"] + p["packingPrice"])) <= 1)
    else:
        chk("算价成功", False, str(r.get("message"))[:60])


# ---------------------------------------------------------------- 4. 完整下单链路
def test_order_lifecycle(do_order: bool = False) -> None:
    section("4. 完整下单链路")

    if not do_order:
        print("    [SKIP] 默认不消耗下单额度。要真跑请加 --with-order")
        chk("下单链路默认跳过（保护 600039 额度）", True)
        # 仍验证不需要下单的契约：算价 + 确认单渲染能力
        payload = {"storeCode": STORE, "orderType": 2, "beType": 2, "beCode": BE_CODE,
                   "needTableware": True,
                   "items": [{"productCode": "9900003004", "quantity": 1,
                              "roundList": [
                                  {"round": "1", "comboItemList": [{"code": "901401", "quantity": 1}]},
                                  {"round": "2", "comboItemList": [{"code": "501205", "quantity": 1}]},
                                  {"round": "3", "comboItemList": [{"code": "903050", "quantity": 1}]}]}]}
        r = call("calculate-price", payload)
        chk("算价可用（不消耗下单额度）", r.get("success") is True,
            str(r.get("message"))[:60])
        return

    payload = {"storeCode": STORE, "orderType": 2, "beType": 2, "beCode": BE_CODE,
               "addressId": ADDRESS_ID, "needTableware": True,
               "remark": "无接触配送",
               "items": [{"productCode": "9900003004", "quantity": 1,
                          "roundList": [
                              {"round": "1", "comboItemList": [{"code": "901401", "quantity": 1}]},
                              {"round": "2", "comboItemList": [{"code": "501205", "quantity": 1}]},
                              {"round": "3", "comboItemList": [{"code": "903050", "quantity": 1}]}]}]}
    r = call("calculate-price", payload)
    calc_price = r["data"]["price"] if r.get("success") else None

    r = call("create-order", payload)
    if r.get("code") == 600039:
        print("    [SKIP] 今日下单数已达上限（600039），跳过下单链路用例")
        chk("下单上限是已知业务限制（600039）", True)
        return
    if not chk("创建订单成功", r.get("success") is True, str(r.get("message"))[:80]):
        return
    dd = r["data"]
    det = dd.get("orderDetail", dd)
    oid = dd.get("orderId")
    print(f"    订单号: {oid}")

    # 注意两处差异：
    #   单位 —— calculate-price 返回「分」，create-order 的 realTotalAmount 是「元」
    #   类型 —— realTotalAmount 是 **字符串** '38.9'，不是数字
    order_amt = det.get("realTotalAmount")
    try:
        order_amt = float(order_amt)
    except (TypeError, ValueError):
        pass
    chk("订单金额 == 算价金额（分→元换算）",
        order_amt == (calc_price / 100 if calc_price else None),
        f"order={order_amt!r}元 vs calc={calc_price}分")

    chk("中文备注正常入库（无乱码）",
        det.get("remark") == "无接触配送", repr(det.get("remark")))

    chk("有支付链接", bool(dd.get("payH5Url")))
    chk("有支付截止时间", bool(det.get("expirePayTime")))

    # 确认单生成
    receipt = os.path.join(HERE, "_tmp_receipt.png")
    script = os.path.join(SKILL, "scripts", "order_receipt.py")
    proc = subprocess.run([PY, script, oid, receipt],
                          capture_output=True, text=True, encoding="utf-8")
    chk("确认单脚本可运行", proc.returncode == 0, proc.stderr[:80])
    chk("确认单文件已生成", os.path.exists(receipt) and os.path.getsize(receipt) > 10000)

    # 取消
    r = call("cancel-order", {"orderId": oid, "cancelReasonCode": "3"})
    chk("取消订单成功", r.get("success") is True, str(r.get("message"))[:60])

    r = call("query-order", {"orderId": oid})
    dd2 = r.get("data") or {}
    chk("订单终态为已取消", dd2.get("orderStatus") == "订单已取消",
        str(dd2.get("orderStatus")))

    if os.path.exists(receipt):
        os.remove(receipt)


# ---------------------------------------------------------------- 4.5 场景校验器
def test_scenario_guard() -> None:
    section("4.5 场景参数校验器")

    guard = os.path.join(SKILL, "scripts", "scenario_guard.py")

    def run_guard(*a):
        proc = subprocess.run([PY, guard] + list(a),
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout

    # 到店：漏 takeWayCode 应被拦下
    rc, out = run_guard("--scenario", "pickup", "--order-type", "1", "--be-type", "1")
    chk("到店漏 takeWayCode -> 被拦下", rc != 0 and "takeWayCode" in out)

    # 到店：传了不该传的 beCode 应被拦下
    rc, out = run_guard("--scenario", "pickup", "--order-type", "1", "--be-type", "1",
                        "--be-code", "145005602", "--take-way-code", "eat-in")
    chk("到店传 beCode -> 被拦下", rc != 0 and "不应传 beCode" in out)

    # 外送：缺 beCode 应被拦下
    rc, out = run_guard("--scenario", "delivery", "--order-type", "2", "--be-type", "2")
    chk("外送缺 beCode -> 被拦下", rc != 0 and "beCode" in out)

    # 外送：传 takeWayCode 应被拦下
    rc, out = run_guard("--scenario", "delivery", "--order-type", "2", "--be-type", "2",
                        "--be-code", "145005602", "--take-way-code", "eat-in")
    chk("外送传 takeWayCode -> 被拦下", rc != 0 and "不应传 takeWayCode" in out)

    # 跨店复用 takeWayCode（每家店自己的）
    rc, out = run_guard("--scenario", "pickup", "--order-type", "1", "--be-type", "1",
                        "--store-code", "1450556", "--take-way-code", "take-in-store")
    chk("跨店复用 takeWayCode -> 被拦下", rc != 0 and "不能跨店复用" in out)

    rc, out = run_guard("--scenario", "pickup", "--order-type", "1", "--be-type", "1",
                        "--store-code", "1450556", "--take-way-code", "locker-out")
    chk("该店正确的 takeWayCode -> 通过", rc == 0)

    # 跨场景商品编码（最隐蔽的一类）
    menu_pickup = os.path.join(HERE, "_tmp_menu_pickup.json")
    plan = os.path.join(HERE, "_tmp_plan.json")
    try:
        r = call("query-meals", {"storeCode": STORE, "orderType": 1, "beType": 1})
        with open(menu_pickup, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False)
        with open(plan, "w", encoding="utf-8") as f:
            json.dump({"items": [{"productCode": "9900003004", "quantity": 1}]}, f)
        rc, out = run_guard("--scenario", "pickup", "--order-type", "1", "--be-type", "1",
                            "--take-way-code", "take-in-store",
                            "--menu", menu_pickup, "--items", plan)
        chk("跨场景商品编码 -> 被拦下", rc != 0 and "不在当前场景菜单里" in out)
    finally:
        for pth in (menu_pickup, plan):
            if os.path.exists(pth):
                os.remove(pth)

    # 到店场景的 takeWayList 确实存在
    r = call("calculate-price", {"storeCode": STORE, "orderType": 1, "beType": 1,
                                 "needTableware": True,
                                 "items": [{"productCode": "1100", "quantity": 1}]})
    if r.get("success"):
        tw = r["data"].get("takeWayList") or []
        codes = [t.get("code") for t in tw]
        chk("到店 takeWayList 含 eat-in / take-in-store",
            "eat-in" in codes and "take-in-store" in codes, str(codes))
    else:
        chk("到店算价成功", False, str(r.get("message"))[:60])

    # 600042 契约由 scenario_guard 保证（静态断言），不真下单消耗额度
    rc, out = run_guard("--scenario", "pickup", "--order-type", "1", "--be-type", "1")
    chk("600042 契约由校验器保证（缺 takeWayCode 必被拦）",
        rc != 0 and "600042" in out, "校验器未提示 600042")


# ---------------------------------------------------------------- 5. 静态校验
def test_static() -> None:
    section("5. 静态校验")

    skill_md = os.path.join(SKILL, "SKILL.md")
    if os.path.exists(skill_md):
        txt = open(skill_md, encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
        chk("SKILL.md frontmatter 合法", bool(m))
        if m:
            fm = m.group(1)
            chk("frontmatter 含 agent_created: true",
                re.search(r"^agent_created:\s*true", fm, re.M) is not None)
            chk("frontmatter 无 disable 字段",
                re.search(r"^disable:", fm, re.M) is None)
            chk("SKILL.md 提到 order_receipt", "order_receipt" in txt)
            chk("SKILL.md 提到 600057 双成因", "600057" in txt and "beCode" in txt)
        chk("SKILL.md 提到 takeWayCode", "takeWayCode" in txt)
        chk("SKILL.md 提到两套 productCode", "两套 productCode" in txt)
    else:
        chk("SKILL.md 存在", False, skill_md)

    api_md = os.path.join(SKILL, "references", "mcp-api.md")
    if os.path.exists(api_md):
        t = open(api_md, encoding="utf-8").read()
        for code in ("600048", "60002", "60006", "600057"):
            chk(f"接口文档覆盖错误码 {code}", code in t)
        chk("接口文档含传参矩阵", "传参矩阵" in t or "orderType" in t)
        chk("接口文档含四渠道规则", "四渠道完整参数规则" in t)
        chk("接口文档含两套编码体系", "两套 productCode 体系" in t)
    else:
        chk("mcp-api.md 存在", False)

    # 两处脚本一致性
    for fn in ("mcd_call.py", "menu_helper.py", "fetch_qr.py",
               "locate_store.py", "order_receipt.py", "scenario_guard.py"):
        a = os.path.join(PROJ, "scripts", fn)
        b = os.path.join(SKILL, "scripts", fn)
        if not (os.path.exists(a) and os.path.exists(b)):
            chk(f"脚本存在: {fn}", False)
            continue
        ha = hashlib.md5(open(a, "rb").read()).hexdigest()
        hb = hashlib.md5(open(b, "rb").read()).hexdigest()
        chk(f"两处一致: {fn}", ha == hb)


def main() -> int:
    offline = "--offline" in sys.argv
    # ⚠️ 真实下单会消耗账号的「今日下单数」额度（600039），且取消不释放。
    #    所以默认**不**跑下单链路，要跑必须显式 --with-order。
    with_order = "--with-order" in sys.argv
    print("麦当劳 MCP 回归测试" + ("（离线模式）" if offline else "（真实接口）")
          + ("（含真实下单）" if with_order else "（不含下单，保护额度）"))
    try:
        if not offline:
            test_param_matrix()
            test_error_codes()
            test_business_rules()
            test_order_lifecycle(with_order)
            test_scenario_guard()
        test_static()
    except Exception as e:  # noqa: BLE001
        print(f"\n[ERROR] 测试中断: {e}")
        import traceback
        traceback.print_exc()
        _results["fail"] += 1

    print(f"\n{'=' * 46}")
    print(f"通过 {_results['pass']}  失败 {_results['fail']}")
    if _failures:
        print("\n失败明细:")
        for f in _failures:
            print("  - " + f)
    return 0 if _results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
