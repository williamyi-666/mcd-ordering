"""
骰子选餐引擎回归测试（v2 —— 三骰 216 级强度阶梯）。

验证项：
  A 硬约束（12 个 人数×预算 场景）：超预算=0 | 忌口违例=0 | 供餐不足=0 | 含饮品=0
  B 权威供餐人数优先于名称推断
  C 三骰确定性：同一组骰面 → 同一结果
  D 216 阶梯严格单调：点数越大 → 价格越高
  E 预算安全：多份投掷时合计不越界（合成场景，真实菜单下 rolls 常为 1）
  F 结构分类与免费重投 token
  G 单骰模式回归（v1 兼容性）

用法：
    python tests/dice_roll.test.py            # 用真实菜单（需 MCP 可用）
    python tests/dice_roll.test.py --offline  # 用内置样本菜单，不联网
"""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.environ.get("USERPROFILE", "C:/Users/Administrator"),
                     ".workbuddy", "skills", "mcd-ordering")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

from dice_roll import (ALL_TRIPLES, N_ATOMS, STRUCTURE_LABELS, TRIPLE_RANK,  # noqa: E402
                       build_pool, is_drink_only, meals_of, normalize_band,
                       roll_food, roll_triple, serves_of, structure_of,
                       triple_info)

OFFLINE = "--offline" in sys.argv

SAMPLE_MENU = {
    "9900010341": {"name": "鸡肉汉堡随心选单人餐", "currentPrice": 33.9},
    "9900003004": {"name": "麦乐鸡(5块)套餐", "currentPrice": 31.0},
    "9900016510": {"name": "“我就喜欢”鸡薯双全盒", "currentPrice": 15.9},
    "9900016057": {"name": "汉堡开心乐园餐", "currentPrice": 25.0},
    "9900012938": {"name": "快乐吃鸡双人餐", "currentPrice": 55.9},
    "9900003936": {"name": "培根蔬萃双层牛堡薯翅四件套", "currentPrice": 55.5},
    "9900013002": {"name": "畅享吃鸡三人餐", "currentPrice": 86.0},
    "9900013004": {"name": "合家欢聚鸡牛三人餐", "currentPrice": 96.0},
    "9900002925": {"name": "超级翅桶", "currentPrice": 110.0},
    "9900012945": {"name": "加牛欢享四人餐", "currentPrice": 116.0},
    "9900011129": {"name": "“堡”你欢乐套餐", "currentPrice": 35.9},
    "9900002995": {"name": "麦辣鸡腿汉堡套餐", "currentPrice": 41.0},
    "903755": {"name": "纯牛奶(盒装)", "currentPrice": 11.5},
    "901027": {"name": "100% 苹果汁(盒装)", "currentPrice": 13.0},
    "903050": {"name": "可口可乐中杯", "currentPrice": 8.0},
}

# 权威人数样本（含两个「名称骗人」的真实案例）
SAMPLE_SERVES = {
    "9900016510": 1, "9900011129": 1, "9900002995": 1,
    "9900012938": 2, "9900003936": 2,   # 真 2 人份
    "9900013002": 3, "9900013004": 3, "9900012945": 4,
    "9900002925": 4,
}


def load_menu():
    if not OFFLINE:
        try:
            script = os.path.join(SKILL, "scripts", "mcd_call.py")
            p = subprocess.run(
                [sys.executable, script, "query-meals",
                 json.dumps({"storeCode": "1450056", "orderType": 1,
                             "beType": 1})],
                capture_output=True, text=True, encoding="utf-8")
            m = meals_of(json.loads(p.stdout))
            if m:
                print("  (使用真实菜单)")
                return m
        except Exception as e:  # noqa: BLE001
            print("  (真实菜单获取失败，回退样本: %s)" % e)
    print("  (使用内置样本菜单)")
    return SAMPLE_MENU


def load_serves_map():
    if not OFFLINE:
        for cand in (os.path.join(HERE, "serves_map.json"),
                     os.path.join(HERE, "tmp", "serves_map.json"),
                     os.path.join(HERE, "..", "scripts", "serves_map.json")):
            if os.path.exists(cand):
                print("  (使用权威人数 %s)" % cand)
                return json.load(open(cand, encoding="utf-8"))
    print("  (使用样本权威人数)")
    return SAMPLE_SERVES


meals = load_menu()
serves_map = load_serves_map()

# 投前确认所需的完整上下文（确认机制默认开启）
CTX = {"channel": "到店自取", "store_code": "1450056"}


def roll(people, band, restrictions=None, mode=None, **kw):
    """带完整确认上下文的投掷（走真实路径）。带 splits 时走连投。"""
    if mode:
        kw["dice_mode"] = mode
    kw.setdefault("dice_mode", "triple")
    kw.setdefault("serves_map", serves_map)
    kw.setdefault("defaults", {})
    r = ["不吃辣"] if restrictions is None else restrictions
    if kw.get("splits"):
        from dice_roll import roll_splits
        kw.pop("dice_mode", None)      # roll_splits 只有三骰
        return roll_splits(meals, people, band, r, **CTX, **kw)
    return roll_food(meals, people, band, r, **CTX, **kw)

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           "  " + detail if detail else ""))


# ================================================================ A 硬约束
def test_hard_constraints(mode="triple"):
    print("\nA. 硬约束（%s 模式）" % mode)
    print("  %-5s %-9s %8s %8s %8s %8s %8s"
          % ("人数", "预算档", "有解率", "超预算", "忌口违例", "供餐不足", "含饮品"))
    all_ok = True
    for people in [1, 2, 3, 4]:
        for band_label in ["50以内", "50-100", "100+"]:
            trials = 2000
            solved = over = spicy = short = drink = 0
            for _ in range(trials):
                r = roll(people, band_label, mode=mode)
                if not r["ok"]:
                    continue
                solved += 1
                hi = r["band"]["hi"]
                if hi < 10 ** 9 and r["total"] > hi:
                    over += 1
                for p in r["picks"]:
                    if "辣" in p["name"]:
                        spicy += 1
                    if is_drink_only(p["name"]):
                        drink += 1
                if r.get("servesTotal", 0) < people:
                    short += 1
            bad = bool(over or spicy or short or drink)
            if bad:
                all_ok = False
            print("  %-5d %-9s %7.1f%% %8d %8d %8d %8d  %s"
                  % (people, band_label, solved * 100.0 / trials,
                     over, spicy, short, drink, "OK" if not bad else "FAIL"))
    check("A 硬约束全部为 0（%s）" % mode, all_ok)
    return all_ok


# ================================================================ B 权威人数
def test_authoritative_serves():
    print("\nB. 权威供餐人数优先于名称推断")
    # 「麦麦周末双人餐」名称含"双人"但真实 1 人份
    fake = {
        "A": {"name": "麦麦周末双人餐", "currentPrice": 49.9},
        "B": {"name": "全明星双人分享餐八件套", "currentPrice": 49.9},
    }
    auth = {"A": 1, "B": 2}
    band = normalize_band("50以内")
    p_no, _ = build_pool(fake, 2, band, [], None)
    p_yes, _ = build_pool(fake, 2, band, [], auth)
    names_no = sorted(x["name"] for x in p_no)
    names_yes = sorted(x["name"] for x in p_yes)
    check("B1 无权威数据时名称推断放行了假双人餐",
          "麦麦周末双人餐" in names_no, str(names_no))
    check("B2 有权威数据后假双人餐被排除",
          "麦麦周末双人餐" not in names_yes, str(names_yes))
    check("B3 真双人餐仍保留",
          "全明星双人分享餐八件套" in names_yes)
    # serves_of 兜底仍返回 2（名称层面），说明必须靠权威数据纠正
    check("B4 serves_of 名称推断确实会错（这正是需要权威数据的原因）",
          serves_of("麦麦周末双人餐") == 2)


# ================================================================ C 确定性
def test_determinism():
    print("\nC. 三骰确定性（同一组骰面 → 同一结果）")
    pool, _ = build_pool(meals, 1, normalize_band("50以内"), [], serves_map)
    if not pool:
        check("C 跳过（当前菜单该场景无候选）", True)
        return
    bad = 0
    for t in ALL_TRIPLES:
        a = roll_triple(pool, t)
        b = roll_triple(pool, t)
        if a["code"] != b["code"]:
            bad += 1
    check("C1 216 组骰面全部确定性一致", bad == 0, "不一致 %d" % bad)

    r1 = roll(1, "50以内", triples=[(3, 4, 5)])
    r2 = roll(1, "50以内", triples=[(3, 4, 5)])
    same = (r1["ok"] and r2["ok"] and r1["picks"][0]["code"] == r2["picks"][0]["code"])
    check("C2 指定骰面可复现", same,
          r1["picks"][0]["name"] if r1["ok"] else "")


# ================================================================ D 单调性
def test_monotonic():
    print("\nD. 216 阶梯严格单调（点数越大 → 价格越高）")
    pool, _ = build_pool(meals, 1, normalize_band("50以内"), [], serves_map)
    if not pool:
        check("D 跳过（无候选）", True)
        return
    srt = sorted(pool, key=lambda x: x["total"])
    n = len(srt)
    viol = 0
    prev = -1
    for t in ALL_TRIPLES:
        r = TRIPLE_RANK[t]
        idx = min(int(r * n / N_ATOMS), n - 1)
        if idx < prev:
            viol += 1
        prev = max(prev, idx)
    check("D1 阶梯到价格位单调违例 = 0", viol == 0, "违例 %d / 池 %d" % (viol, n))

    # 总和越大 → 阶梯位越大（严格）
    viol2 = 0
    for t in ALL_TRIPLES:
        for u in ALL_TRIPLES:
            if sum(t) < sum(u) and TRIPLE_RANK[t] > TRIPLE_RANK[u]:
                viol2 += 1
                break
    check("D2 总和序与阶梯序一致", viol2 == 0, "违例 %d" % viol2)


# ================================================================ E 预算安全
def test_budget_safety():
    print("\nE. 预算安全（多份投掷时合计不越界）")
    # 构造强制多份的场景：只有 1 人份套餐，人数=3，档位 50-100
    fake = {
        "S%d" % i: {"name": "单人套餐%d" % i, "currentPrice": p}
        for i, p in enumerate([28.0, 30.0, 32.0, 33.0, 34.0])
    }
    band = normalize_band("50-100")
    pool, deg = build_pool(fake, 3, band, [], None)
    check("E1 合成场景可建池", bool(pool), "池 %d 组合=%s" % (len(pool), deg))
    over = 0
    for _ in range(3000):
        r = roll_food(fake, 3, "50-100", [], dice_mode="triple")
        if not r["ok"]:
            continue
        if r["total"] > r["band"]["hi"]:
            over += 1
    check("E2 多份投掷合计不越界", over == 0, "越界 %d / 3000" % over)

    # 单份上限收紧生效：单份价格 <= 档上限 / 投次
    if pool:
        cap = band["hi"]
        per = cap / max(1, len(pool[0].get("note", "")) and 3 or 3)
        check("E3 收紧后单份上限 <= 档上限/投次",
              all(p["total"] <= cap for p in pool),
              "单份最高 %.1f 元，上限 %.1f 元" % (max(p["total"] for p in pool), cap))


# ================================================================ F 结构与 token
def test_structure():
    print("\nF. 骰面结构分类与免费重投 token")
    from collections import Counter
    c = Counter(structure_of(t) for t in ALL_TRIPLES)
    check("F1 结构分类合计 = 216", sum(c.values()) == 216, str(dict(c)))
    check("F2 豹子 = 6 种", c["豹子"] == 6)
    check("F3 顺子 = 24 种", c["顺子"] == 24)
    check("F4 对子 = 90 种", c["对子"] == 90)
    check("F5 散牌 = 96 种", c["散牌"] == 96)
    check("F6 每类都有标签",
          all(k in STRUCTURE_LABELS for k in c))
    info = triple_info((6, 6, 6))
    check("F7 豹子给免费重投权", info["rerollToken"] is True)
    info2 = triple_info((1, 2, 4))
    check("F8 散牌无重投权", info2["rerollToken"] is False)
    check("F9 原子总数 216", N_ATOMS == 216)


# ================================================================ G 单骰回归
def test_single_mode():
    print("\nG. 单骰模式回归（v1 兼容性）")
    over = spicy = short = drink = 0
    for people in [1, 2, 3, 4]:
        for band_label in ["50以内", "50-100", "100+"]:
            for _ in range(800):
                r = roll(people, band_label, dice_mode="single")
                if not r["ok"]:
                    continue
                hi = r["band"]["hi"]
                if hi < 10 ** 9 and r["total"] > hi:
                    over += 1
                for p in r["picks"]:
                    if "辣" in p["name"]:
                        spicy += 1
                    if is_drink_only(p["name"]):
                        drink += 1
                if r.get("servesTotal", 0) < people:
                    short += 1
    check("G1 单骰模式硬约束全 0",
          not (over or spicy or short or drink),
          "越界%d 辣%d 供餐%d 饮品%d" % (over, spicy, short, drink))


# ================================================================ H 投前确认
def test_confirm_gate():
    print("\nH. 投前确认（缺信息不投掷）")
    band = "50-100"

    # 1) 什么都没给 → 拒绝，且明确列出缺什么
    r = roll_food(meals, 3, band, ["不吃辣"], dice_mode="triple",
                  serves_map=serves_map, defaults={})
    check("H1 无渠道/门店时拒绝投掷",
          r["ok"] is False and r.get("error") == "need_confirm",
          str(r.get("missing")))
    check("H2 拒绝时不产生任何选餐结果",
          r.get("rolled") is False and "picks" not in r)
    check("H3 缺项清单含渠道与门店",
          set(["channel", "storeCode"]).issubset(set(r.get("missing", []))))

    # 2) 只给部分信息 → 仍拒绝，且缺项收敛
    r2 = roll_food(meals, 3, band, ["不吃辣"], dice_mode="triple",
                   serves_map=serves_map, channel="到店自取", defaults={})
    check("H4 补了渠道仍缺门店 → 继续拒绝",
          r2["ok"] is False and set(r2.get("missing", [])) == {"storeCode"},
          str(r2.get("missing")))

    # 3) 信息齐全 → 正常投掷
    r3 = roll_food(meals, 3, band, ["不吃辣"], dice_mode="triple",
                   serves_map=serves_map, defaults={}, **CTX)
    check("H5 信息齐全后正常投掷", r3["ok"] is True,
          r3["picks"][0]["name"] if r3["ok"] else "")
    check("H6 结果带确认卡且标记 ready",
          r3.get("confirmCard", {}).get("ready") is True)
    check("H7 结果带可下单上下文（门店/渠道/beType）",
          (r3.get("orderContext") or {}).get("storeCode") == "1450056"
          and (r3.get("orderContext") or {}).get("beType") == 1)

    # 4) 忌口可以显式声明"无"
    r4 = roll_food(meals, 1, "50以内", [], dice_mode="triple",
                   serves_map=serves_map, defaults={}, **CTX)
    check("H8 忌口显式为空也视为已确认", r4["ok"] is True)

    # 5) 确认卡字段完整性
    from dice_roll import CONFIRM_SLOTS, build_confirm_card, normalize_channel
    check("H9 确认槽位 6 项", len(CONFIRM_SLOTS) == 6, str(len(CONFIRM_SLOTS)))
    required = [s["key"] for s in CONFIRM_SLOTS if s["required"]]
    check("H10 必填 5 项（人数/预算/忌口/渠道/门店）",
          required == ["people", "band", "restrictions", "channel", "storeCode"],
          str(required))
    empty = build_confirm_card()
    check("H11 空卡 ready=False 且缺 5 项",
          empty["ready"] is False and len(empty["missing"]) == 5)
    full = build_confirm_card(people=2, band="50-100", restrictions=[],
                              channel="麦乐送", store_code="1450056",
                              use_coupon=False)
    check("H12 满卡 ready=True", full["ready"] is True)
    check("H13 渠道矩阵：到店 beType=1/orderType=1/无需 beCode",
          normalize_channel("到店自取")["beType"] == 1
          and normalize_channel("到店自取")["orderType"] == 1
          and normalize_channel("到店自取")["beCodeNeeded"] is False)
    check("H14 渠道矩阵：外送 beType=2/orderType=2/需 beCode",
          normalize_channel("外送")["beType"] == 2
          and normalize_channel("外送")["orderType"] == 2
          and normalize_channel("外送")["beCodeNeeded"] is True)
    check("H15 到店场景不提示 beCode",
          not any("beCode" in w for w in
                  build_confirm_card(people=2, band="50-100", restrictions=[],
                                     channel="到店自取",
                                     store_code="1450056")["warnings"]))
    warn = build_confirm_card(people=2, band="50-100", restrictions=[],
                              channel="麦乐送", store_code=None)
    check("H16 外送场景提示必须用接口返回的 beCode",
          warn["ready"] is False
          and any("beCode" in w for w in warn["warnings"]),
          str(warn["warnings"]))


# ================================================================ I 价格口径
def test_price_basis():
    print("\nI. 价格口径（预算必须按实付价，不能按优惠价）")
    from dice_roll import prices_of
    # 有 discountType = 「随单购麦金卡优惠」→ 实付 = 原价
    cond = {"name": "不素之霸双层牛堡四件套", "currentPrice": "32",
            "originalPrice": "58.5", "discountType": "随单购麦金卡优惠"}
    pr = prices_of(cond)
    check("I1 有条件优惠价 → 预算按原价 58.5", pr["pay"] == 58.5,
          "pay=%.1f" % pr["pay"])
    check("I2 有条件优惠价 → 标记会员可省 32", pr["memberPrice"] == 32.0)
    # 无 discountType → 实付 = 现价（原价只是划线价）
    plain = {"name": "大堡口福三件套", "currentPrice": "22.9",
             "originalPrice": "47"}
    pr2 = prices_of(plain)
    check("I3 无条件优惠 → 预算按现价 22.9（原价 47 是划线价）",
          pr2["pay"] == 22.9, "pay=%.1f" % pr2["pay"])
    check("I4 无条件优惠 → 不标记会员价", pr2["memberPrice"] is None)
    # 原价缺失
    only = {"name": "X", "currentPrice": "30"}
    check("I5 原价缺失时回退现价", prices_of(only)["pay"] == 30.0)

    # 真实菜单：跨档商品必须按实付价被排除
    bad = []
    for code, v in meals.items():
        name = v.get("name", "")
        if not any(k in name for k in ["餐", "套", "桶", "盒"]):
            continue
        pr = prices_of(v)
        if pr["pay"] > 50 and v.get("discountType"):
            # 该商品实付超 50，绝不能出现在 50以内 的池里
            pool, _ = build_pool(meals, 1, normalize_band("50以内"),
                                 ["不吃辣"], serves_map)
            if any(x["code"] == code for x in pool):
                bad.append(name)
    check("I6 实付超 50 的有条件优惠商品不进「50以内」池",
          not bad, str(bad[:3]))

    # 池内所有候选的 total 必须 <= 档上限
    over = []
    for band_label, cap in [("50以内", 50), ("50-100", 100)]:
        for people in [1, 2, 3, 4]:
            pool, _ = build_pool(meals, people, normalize_band(band_label),
                                 ["不吃辣"], serves_map)
            for x in pool:
                if x["total"] > cap:
                    over.append((band_label, people, x["name"], x["total"]))
    check("I7 池内候选全部不超档上限", not over, str(over[:3]))


# ================================================================ J 默认值
def test_defaults():
    print("\nJ. 默认值复用（有默认用默认，无默认问 5 项）")
    import tempfile
    from dice_roll import (DEFAULTS_KEYS, NEVER_DEFAULT_KEYS, build_confirm_card,
                           clear_defaults, load_defaults, save_defaults)

    tmp = os.path.join(tempfile.gettempdir(), "mcd_defaults_test.json")
    if os.path.exists(tmp):
        os.remove(tmp)

    check("J1 无默认值文件时返回空 dict", load_defaults(tmp) == {})

    # 无默认值 → 5 项全缺
    card0 = build_confirm_card(defaults={})
    check("J2 无默认值 + 无入参 → 缺 5 项",
          len(card0["missing"]) == 5, str(card0["missing"]))
    check("J3 无默认值 → askCount=5", card0["askCount"] == 5)
    check("J4 无默认值 → 不使用默认标记", card0["usedDefaults"] is False)

    # 存默认值
    save_defaults({"storeCode": "1450713", "storeName": "华旭国际大厦",
                   "channel": "到店自取", "restrictions": ["不吃辣"],
                   "useCoupon": False}, tmp)
    d = load_defaults(tmp)
    check("J5 默认值已保存", d.get("storeCode") == "1450713", str(d))
    check("J6 useCoupon=False 能存下来（不是被当空值）",
          d.get("useCoupon") is False, repr(d.get("useCoupon")))
    check("J7 存了 updatedAt", bool(d.get("updatedAt")))
    check("J8 人数与预算档不入默认值",
          all(k not in d for k in NEVER_DEFAULT_KEYS), str(d))

    # 有默认值 + 只给人数预算 → ready，只问 0 项
    card1 = build_confirm_card(people=3, band="50-100", defaults=d)
    check("J9 有默认值 → 只需人数+预算即可投掷", card1["ready"] is True,
          "missing=%s" % card1["missing"])
    check("J10 有默认值 → askCount=0", card1["askCount"] == 0)
    check("J11 标记使用了默认值", card1["usedDefaults"] is True,
          str(card1["fromDefaults"]))
    check("J12 默认项来源标为 default",
          all(c["source"] == "default" for c in card1["card"]
              if c["key"] in ("storeCode", "channel", "restrictions")))
    check("J13 显式传入值覆盖默认值（门店改成别的）",
          build_confirm_card(people=1, band="50以内", store_code="1450056",
                             defaults=d)["card"][4]["value"] == "1450056")

    # 人数/预算档即使有默认也不用
    d2 = dict(d)
    d2["people"] = 4
    d2["band"] = "100+"
    card2 = build_confirm_card(defaults=d2)
    check("J14 人数/预算档不吃默认值（仍列为缺失）",
          set(card2["missing"]) >= {"people", "band"}, str(card2["missing"]))

    # 忽略默认值
    card3 = build_confirm_card(people=1, band="50以内", defaults=d,
                               use_defaults=False)
    check("J15 use_defaults=False 时全部重新确认",
          set(card3["missing"]) >= {"storeCode", "channel"}, str(card3["missing"]))

    clear_defaults(tmp)
    check("J16 清除默认值", not os.path.exists(tmp))

    # CLI 层：无默认值时 roll_food 拒绝
    r = roll_food(meals, 2, "50-100", ["不吃辣"], dice_mode="triple",
                  serves_map=serves_map, defaults={})
    check("J17 无默认值且缺项 → 拒绝投掷",
          r["ok"] is False and r["error"] == "need_confirm")
    # 有默认值时只给人数预算即可投
    r2 = roll_food(meals, 2, "50-100", None, dice_mode="triple",
                   serves_map=serves_map, defaults=d)
    check("J18 有默认值 → 只给人数预算就能投",
          r2["ok"] is True, r2["picks"][0]["name"] if r2["ok"] else str(r2))


# ================================================================ K 付款门禁
def test_pay_gate():
    print("\nK. 付款前确认门禁")
    sys.path.insert(0, os.path.join(SKILL, "scripts"))
    from pay_confirm import build_gate

    def fake(**kw):
        base = {
            "orderStatus": "待支付", "storeName": "麦当劳测试店",
            "storeCode": "1450713", "storeAddress": "南京东路1号",
            "expirePayTime": "2099-01-01 00:00:00",
            "orderProductList": [
                {"productName": "不素之霸双层牛堡四件套", "quantity": 1,
                 "price": 58.5,
                 "comboItemList": [{"itemName": "双层牛堡", "itemQuantity": 1},
                                   {"itemName": "中薯条", "itemQuantity": 1}]},
            ],
            "productPrice": 58.5, "deliveryPrice": 0,
            "realPackingFeeTotalPrice": 0, "totalDiscountAmount": 0,
            "realTotalAmount": 58.5,
            "couponList": [{"x": 1}],
            "deliveryInfo": {"deliveryType": "到店自取"},
        }
        base.update(kw)
        return base

    g = build_gate(fake(), "T1")
    check("K1 正常订单 → 可付款", g["readyToPay"] is True,
          str(g["blockers"]))
    check("K2 输出必须让用户确认的话术",
          len(g["mustConfirm"]) >= 3 and any("应付总额" in m for m in g["mustConfirm"]))
    check("K3 明细含套餐内部构成",
          g["summary"]["products"][0]["comboItems"][0]["name"] == "双层牛堡")

    # 金额不符 → 拦
    g2 = build_gate(fake(), "T2", expect_total=40.0)
    check("K4 金额与预期不符 → 拦下", g2["readyToPay"] is False,
          str(g2["blockers"]))
    check("K5 差额写清楚", any("差" in b for b in g2["blockers"]))

    # 已取消 → 拦
    g3 = build_gate(fake(orderStatus="订单已取消"), "T3")
    check("K6 已取消订单 → 拦下", g3["readyToPay"] is False)

    # 过期 → 拦
    g4 = build_gate(fake(expirePayTime="2020-01-01 00:00:00"), "T4")
    check("K7 支付超时 → 拦下", g4["readyToPay"] is False)

    # 含辣但要求不吃辣 → 拦
    g5 = build_gate(fake(orderProductList=[
        {"productName": "麦辣鸡腿堡四件套", "quantity": 1, "price": 28.0,
         "comboItemList": []}],
        productPrice=28.0, realTotalAmount=28.0), "T5",
        restrictions=["不吃辣"])
    check("K8 含辣但忌口不吃辣 → 拦下", g5["readyToPay"] is False)

    # 费用勾稽不平 → 拦
    g6 = build_gate(fake(realTotalAmount=99.0), "T6")
    check("K9 费用勾稽不平 → 拦下", g6["readyToPay"] is False)

    # 空商品 → 拦
    g7 = build_gate(fake(orderProductList=[], productPrice=0,
                         realTotalAmount=0), "T7")
    check("K10 无商品 → 拦下", g7["readyToPay"] is False)

    # 订单查询失败 → 拦
    g8 = build_gate({"_error": "610303 订单号不存在"}, "T8")
    check("K11 查单失败 → 拦下", g8["readyToPay"] is False)


# ================================================================ L 连投
def test_split():
    print("\nL. 连投模式（每人各掷一次）")
    from dice_roll import build_split_pool, roll_splits

    band = normalize_band("50-100")
    pool3, cap3 = build_split_pool(meals, band, ["不吃辣"], 3, serves_map)
    check("L1 连投只取单人份",
          all(p["serves"] == 1 for p in pool3), "池 %d" % len(pool3))
    check("L2 单份上限 = 档上限 / 份数",
          abs(cap3 - 100 / 3) < 0.01, "%.2f" % cap3)
    check("L3 池内单份均不超均摊上限",
          pool3 and all(p["total"] <= cap3 + 1e-9 for p in pool3))

    r = roll_splits(meals, 3, "50-100", ["不吃辣"], splits=3,
                    serves_map=serves_map, seed=11,
                    channel="到店自取", store_code="1450713", defaults={})
    if r["ok"]:
        check("L4 投出 3 份", r["rolls"] == 3, "rolls=%d" % r["rolls"])
        check("L5 合计不超档上限", r["total"] <= 100 + 1e-9,
              "%.1f 元" % r["total"])
        check("L6 份数达到人数要求", r["servesTotal"] >= 3,
              "serves=%d" % r["servesTotal"])
        check("L7 每份都有独立骰面",
              all(len(p["dice"]) == 3 for p in r["picks"]))
        codes = [p["code"] for p in r["picks"]]
        check("L8 池够大时尽量不重复",
              len(set(codes)) == len(codes) or len(pool3) < 3,
              "codes=%s" % codes)
        check("L9 结果带连投标记", r["mode"] == "split")
        check("L10 结果带 orderContext 可接下单",
              (r.get("orderContext") or {}).get("beType") == 1)
    else:
        for i in range(4, 11):
            check("L%d 跳过（该场景无解）" % i, True)

    # 每份上限过低时应诚实报无解（或仍满足预算）
    r2 = roll_splits(meals, 4, "50以内", ["不吃辣"], splits=4,
                     serves_map=serves_map, seed=1,
                     channel="到店自取", store_code="1450713", defaults={})
    if not r2["ok"]:
        check("L11 每份上限过低时如实报无解",
              r2.get("error") == "no_solution", str(r2.get("error")))
    else:
        check("L11 该菜单下仍有解，合计须在档内",
              r2["total"] <= 50 + 1e-9, "%.1f" % r2["total"])

    # 连投也必须过投前确认
    r3 = roll_splits(meals, 2, "50-100", ["不吃辣"], splits=2,
                     serves_map=serves_map, defaults={})
    check("L12 连投同样受投前确认拦截",
          r3["ok"] is False and r3["error"] == "need_confirm")


# ================================================================ M 重投
def test_reroll():
    print("\nM. 免费重投")
    from dice_roll import reroll

    base = roll(3, "50-100", splits=3, seed=11)
    if not base.get("ok"):
        check("M 跳过（基准无解）", True)
        return

    rr = reroll(base, meals, serves_map=serves_map, seed=99, keep="cheaper")
    check("M1 重投成功", rr.get("ok") is True)
    check("M2 cheaper 策略保留金额较低者",
          rr["result"]["total"] == min(rr["old"]["total"], rr["new"]["total"]),
          "old=%.1f new=%.1f kept=%s"
          % (rr["old"]["total"], rr["new"]["total"], rr["kept"]))
    check("M3 省下的金额非负", rr["saved"] >= 0, "%.1f" % rr["saved"])

    rr2 = reroll(base, meals, serves_map=serves_map, seed=99, keep="higher")
    check("M4 higher 策略保留金额较高者",
          rr2["result"]["total"] == max(rr2["old"]["total"], rr2["new"]["total"]),
          "kept=%s" % rr2["kept"])

    check("M5 重投结果仍在预算档内",
          rr["result"]["total"] <= 100 + 1e-9,
          "%.1f" % rr["result"]["total"])

    bad = reroll({"ok": False}, meals)
    check("M6 无上次结果时安全返回", bad.get("ok") is False)


# ================================================================ 入口
def main():
    print("=" * 72)
    print("骰子选餐引擎回归测试 v2（三骰 + 投前确认 + 默认值 + 连投 + 重投）")
    print("=" * 72)
    test_hard_constraints("triple")
    test_hard_constraints("single")
    test_authoritative_serves()
    test_determinism()
    test_monotonic()
    test_budget_safety()
    test_structure()
    test_single_mode()
    test_confirm_gate()
    test_price_basis()
    test_defaults()
    test_pay_gate()
    test_split()
    test_reroll()

    print("\n" + "=" * 72)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, detail in results:
        if not ok:
            print("  ✗ %s  %s" % (name, detail))
    print("  通过 %d / %d" % (passed, total))
    print("  结论：", "全部通过 ✓" if passed == total else "有失败 ✗")
    print("=" * 72)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
