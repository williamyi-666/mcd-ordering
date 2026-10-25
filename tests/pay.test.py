"""付款闭环回归测试（tests/pay.test.py）。

覆盖：
  A 订单状态判定（classify）—— 已知码 / 文案优先 / 未知码不猜
  B 支付链接构造（payH5Url / jumpToApp）
  C 轮询等待（wait_paid）—— 付成功 / 被取消 / 超时三种结局
  D 与 pay_confirm 门禁的衔接

不需要网络：fetch_order 被 monkeypatch 替换。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.environ.get("USERPROFILE", "C:/Users/Administrator"),
                     ".workbuddy", "skills", "mcd-ordering")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import pay  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           "  " + detail if detail else ""))


# ================================================================ A 状态判定
def test_classify():
    print("\nA. 订单状态判定")

    c = pay.classify({"orderStatus": "待支付", "status": "10"})
    check("A1 待支付 → pending", c["phase"] == "pending", str(c))

    c = pay.classify({"orderStatus": "订单已取消", "status": "60"})
    check("A2 已取消 → failed", c["phase"] == "failed", str(c))

    c = pay.classify({"orderStatus": "已支付"})
    check("A3 已支付 → paid", c["phase"] == "paid", str(c))

    c = pay.classify({"orderStatus": "制作中"})
    check("A4 制作中视为已付款", c["phase"] == "paid", str(c))

    c = pay.classify({"orderStatus": "已完成"})
    check("A5 已完成视为已付款", c["phase"] == "paid", str(c))

    # 文案优先于数字码：status=60 但没有取消文案时，仍按码判 failed
    c = pay.classify({"orderStatus": "", "status": "60"})
    check("A6 无文案时按 status=60 判 failed", c["phase"] == "failed", str(c))

    # 未知码不猜
    c = pay.classify({"orderStatus": "", "status": "99"})
    check("A7 未知码不猜 → unknown",
          c["phase"] == "unknown" and c["known"] is False, str(c))

    # 未知码 + 已知文案 → 信文案
    c = pay.classify({"orderStatus": "已支付", "status": "55"})
    check("A8 未知码但文案明确 → 以文案为准",
          c["phase"] == "paid", str(c))

    # 已退款算失败
    c = pay.classify({"orderStatus": "已退款"})
    check("A9 已退款 → failed", c["phase"] == "failed", str(c))


# ================================================================ B 链接
def test_urls():
    print("\nB. 支付链接构造")
    oid = "1030835320000662091908872974"
    u = pay.pay_url(oid)
    check("B1 payH5Url 是 scanToPay", u ==
          "https://m.mcd.cn/mcp/scanToPay?orderId=" + oid, u)
    j = pay.jump_url(oid)
    check("B2 二维码内容是 jumpToApp", j ==
          "https://m.mcd.cn/mcp/jumpToApp?orderId=" + oid, j)
    check("B3 两条链接都带 orderId",
          oid in u and oid in j)


# ================================================================ C 轮询
def test_wait():
    print("\nC. 轮询等待（fetch_order 打桩）")
    calls = {"n": 0}
    real_fetch = pay.fetch_order

    def stub(seq):
        calls["n"] = 0

        def _f(_oid):
            i = min(calls["n"], len(seq) - 1)
            calls["n"] += 1
            return seq[i]
        return _f

    # 第 3 次查到已支付
    pay.fetch_order = stub([{"orderStatus": "待支付", "status": "10"},
                            {"orderStatus": "待支付", "status": "10"},
                            {"orderStatus": "已支付", "status": "20"}])
    w = pay.wait_paid("X", timeout=10, interval=0.01, verbose=False)
    check("C1 等到已支付 → paid", w["phase"] == "paid" and w["polls"] == 3,
          "phase=%s polls=%d" % (w["phase"], w["polls"]))

    # 直接被取消
    pay.fetch_order = stub([{"orderStatus": "订单已取消", "status": "60"}])
    w = pay.wait_paid("X", timeout=10, interval=0.01, verbose=False)
    check("C2 订单被取消 → failed", w["phase"] == "failed", str(w["phase"]))

    # 一直待支付 → 超时
    pay.fetch_order = stub([{"orderStatus": "待支付", "status": "10"}])
    w = pay.wait_paid("X", timeout=0.05, interval=0.02, verbose=False)
    check("C3 一直待支付 → timeout", w["phase"] == "timeout",
          "waited=%s polls=%s" % (w["waited"], w["polls"]))

    # 查单报错不崩，继续等
    pay.fetch_order = stub([{"_error": "网络抖动"},
                            {"orderStatus": "已支付"}])
    w = pay.wait_paid("X", timeout=10, interval=0.01, verbose=False)
    check("C4 查单报错后能恢复", w["phase"] == "paid", str(w["phase"]))

    pay.fetch_order = real_fetch


# ================================================================ D 衔接
def test_integration():
    print("\nD. 与门禁衔接")
    from pay_confirm import build_gate

    good = {
        "orderStatus": "待支付", "status": "10",
        "storeName": "麦当劳测试店", "storeCode": "1450713",
        "expirePayTime": "2099-01-01 00:00:00",
        "orderProductList": [{"productName": "麦香鸡套餐", "quantity": 1,
                              "price": 28.0, "comboItemList": []}],
        "productPrice": 28.0, "deliveryPrice": 0,
        "realPackingFeeTotalPrice": 0, "totalDiscountAmount": 0,
        "realTotalAmount": 28.0, "couponList": [{"x": 1}],
    }
    g = build_gate(good, "T1", expect_total=28.0)
    check("D1 正常待支付订单门禁通过", g["readyToPay"] is True,
          str(g["blockers"]))
    check("D2 门禁给出的金额与摘要可用于交付",
          g["summary"]["total"] == 28.0)

    g2 = build_gate(dict(good, realTotalAmount=35.0), "T2", expect_total=28.0)
    check("D3 金额不符时门禁拦住（不会走到付款）",
          g2["readyToPay"] is False, str(g2["blockers"])[:80])

    # 待支付但已过期 → 拦
    g3 = build_gate(dict(good, expirePayTime="2020-01-01 00:00:00"), "T3")
    check("D4 已过期订单被拦", g3["readyToPay"] is False)


def main():
    print("=" * 66)
    print("付款闭环回归测试（pay.py）")
    print("=" * 66)
    test_classify()
    test_urls()
    test_wait()
    test_integration()

    print("\n" + "=" * 66)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, detail in results:
        if not ok:
            print("  ✗ %s  %s" % (name, detail))
    print("  通过 %d / %d" % (passed, total))
    print("  结论：", "全部通过 ✓" if passed == total else "有失败 ✗")
    print("=" * 66)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
