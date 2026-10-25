---
name: mcd-ordering
description: >-
  麦当劳点餐助手。用户用一句话描述就餐需求时使用，如"4个人吃，不吃辣，其中1人吃素，预算200"
  "中午随便吃点，3个人，别点辣" "来份巨无霸套餐，算下多少钱" "帮我点两单人餐送家里"
  "点份晚餐" "换家店试试"。自动完成：定位门店（支持地标/坐标/外送地址）→ 领取优惠券 →
  按人数与忌口搭配餐品 → 择优使用优惠券 → 场景校验 → 计算价格 → 用户确认后下单 →
  交付支付二维码与订单确认单。核心能力是解析「人数 + 忌口 + 预算」复合意图并给出可执行搭配方案，
  遇到菜单无法满足的忌口会明确告知而非静默替换。触发词：点餐、点麦当劳、帮我点餐、点份、点个、
  几个人吃、几个人份、不吃辣、吃素、素食、纯素、过敏、不要香菜、预算多少、算价、多少钱、
  麦乐送、外送、送到家、得来速、到店自取、领券、有没有券、用券、下单、麦乐鸡、巨无霸、
  开心乐园餐、晚餐、午餐、早餐、投骰子、掷骰子、随机选、随便来、今天吃什么、
  手气、抽签、转盘。Use when the user wants to order McDonald's food by
  describing party size, dietary restrictions and budget in one sentence.
description_zh: 麦当劳一句话点餐：解析人数、忌口、预算，自动搭配并用券下单
description_en: One-sentence McDonald's ordering: parse party size, dietary restrictions and budget, auto-build the combo, apply the best coupon, and place the order
allowed-tools: Bash, Read, Write
agent_created: true
---

# 麦当劳点餐

用户一句话说清就餐需求，你负责把它变成一份能下单的方案。

---

## ⚠️ 五条铁律

### 1. 所有 MCP 调用必须走脚本，禁止用平台工具层

平台工具层会把整型参数降级成字符串，导致 `beType`/`orderType`/`searchType`/`quantity`
全部校验失败。**一律用 `scripts/mcd_call.py`**：

```bash
python scripts/mcd_call.py <tool_name> '<json_args>'
```

### 2. 中文参数会被服务端按 GBK 解码而变乱码

脚本已内置 `ensure_ascii=True` 转义。**若你手写请求体，必须同样处理**。

### 3. 菜单必须按场景分别拉取，绝不能跨场景复用编码

到店与外送是**两套 productCode 体系**（巨无霸：到店 `1100` / 外送 `901100`），
套餐可能只在一侧存在。用错编码报 `60006 商品已售罄` —— **看起来像库存问题，
实际是商品不在该场景菜单里**，极易误判。

### 4. 算价后必须停下，等用户明确说"下单"

下单涉及真实支付。**不要自动创建订单。**

### 5. 未过付款门禁不得输出支付码

下单后必须跑 `scripts/pay.py`（内置门禁），全部通过且用户明确回复「确认付款」，
才能输出支付入口。**支付页没有任何明细，错了钱就出去了。**
投前确认可以用默认值轻量化，**付款前确认不能**。

---

## 主流程（9 步）

### Step 0 · 解析意图（不调工具）

从用户话里抽：**人数 / 忌口 / 预算 / 场景（外送|到店）/ 口味偏好**。

| 用户说 | 抽取结果 |
|---|---|
| "3个人不要辣预算150" | 人数=3, 忌口=[不吃辣], 预算=150, 场景=外送(默认) |
| "一个人，不吃辣，50以内" | 人数=1, 忌口=[不吃辣], 预算=50 |
| "换家店试试" | 沿用上一轮的人数/忌口/预算，只换门店 |

**沿用上一轮偏好**：用户说过"不吃辣""50以内"后，后续不必重复问。
只在偏好可能变化时才确认。

### Step 1 · 定位门店 + 让用户选

```bash
# 用户说地名
python scripts/locate_store.py --city 上海市 --keyword 人民广场

# 外送场景（带地址，一次拿到「到店门店 + 外送可送门店(含真实 beCode)」）
python scripts/locate_store.py --city 上海市 --keyword 南京路步行街 \
    --address-id <addressId>

# 用户说"我附近" → 浏览器 Geolocation → 逆地理编码 → 查店
python scripts/locate_store.py --city 上海市 --locate

# 已知坐标
python scripts/locate_store.py --city 上海市 --lat 31.2354 --lng 121.4774
```

**⚠️ 必须让用户选门店**：只要返回 ≥1 家门店，就把列表摆出来让用户挑，
**不要自己默认选第一家**（这是硬性要求，不是可选优化）。
用表格给出：门店名 / 编号 / 地址 / 距离 / 营业时间 / 是否营业中。

**⚠️ 接口约束（实测）**：

- `query-nearby-stores` 的 `keyword` **只认地名/地址，传坐标串返回「没有查询到该地址」**
- 门店返回的 `longitude`/`latitude` **恒为 0.0**，不能靠它排序，只能靠 `distance`
- `query-nearby-stores` 的 `beCode` **恒为 null**，外送必须用
  `delivery-query-stores` 返回的 beCode **原值**
- 自己按 `storeCode+后缀` 拼 beCode 会报 `60002`
- `delivery-query-stores` 需要 `addressId`，没有关键词入口
- 所以「按定位选店」必须先做**逆地理编码**（脚本已内置 Nominatim）

**四渠道参数规则（实测 + 接口 schema 双重确认）**：

| 渠道 | orderType | beType | beCode | takeWayCode |
|---|---|---|---|---|
| 到店自取 | 1 | 1 | **不传** | `eat-in` / `take-in-store` / `locker-out` |
| 得来速 | 1 | 5 | 必传（后缀 41）| `take-dt-quick` |
| 麦乐送 | 2 | 2 | 必传（后缀 02）| **不传** |
| 企业团餐 | 2 | 6 | 必传 | 不传（需 `gmServiceCode`，普通账号不可用）|

**外送只有 `beType=2` + 正确 beCode 能通**，其他 beType 配对正确 beCode 也全失败。
**600057 有两种成因**：真打烊，或 **beCode 与 orderType 不匹配（营业中也报）**。
遇到时先看营业时间判断，营业中就换 beCode，**不要无谓换店**。

### Step 2 · 领券 + 判定券状态

```bash
python scripts/mcd_call.py auto-bind-coupons '{}'
python scripts/mcd_call.py query-my-coupons '{}'
python scripts/mcd_call.py query-store-coupons '{"storeCode":"...","orderType":2,"beType":2,"beCode":"..."}'
```

**⚠️ 区分两种"没券"**：

- `auto-bind-coupons` 返回 499（soft_fail）→ **你已经领过了**，不是周末没券
- 用 `available-coupons` 验证：若 `couponStatus=HAVING_RECEIVE` / label「已领取」，
  说明券已到手，只是还没到使用时间
- 若 label 是「可领取」，那才是真能领

**券按周批次滚动**，每批覆盖周一~周五 10:30–23:59。周末领的券要等下周一，
标签「未到使用时间」。**要明说"这批券要到 X 月 X 日才能用"**，
不要说"周末领不到券"。

**卡包券 ≠ 门店可用券** —— 判断能否用一律看 `query-store-coupons`。

### Step 3 · 拉菜单 + 判定人数

```bash
# 到店自取：不传 beCode
python scripts/mcd_call.py query-meals '{"storeCode":"...","orderType":1,"beType":1}'
# 外送：用 delivery-query-stores 返回的 beCode
python scripts/mcd_call.py query-meals '{"storeCode":"...","orderType":2,"beType":2,"beCode":"..."}'
```

**人数不能靠套餐名判断**（「大吉大利吃鸡双人餐」真实是 2 人份，名字里的"双人"
指含 2 种汉堡）。以 round 里**饮料默认数量**为准，几杯=几人份。
用 `menu_helper.py candidates --details <详情目录>` 拿精确人数，
没有正好 N 人套餐时自动拆成"大套餐 + 小套餐"。

对候选套餐拉详情（**只在需要时拉**，避免浪费调用）：

```bash
python scripts/mcd_call.py query-meal-detail '{"storeCode":"...","orderType":2,"beType":2,"beCode":"...","code":"9900010341"}'
```

### Step 4 · 搭配（核心）

**子商品编码必须从 `query-meal-detail` 的 `choices[].code` 取，不要猜** ——
猜错会报 `60006`，很容易误判成"商品售罄"。

用 `menu_helper.py` 做候选筛选与忌口过滤：

```bash
# 候选套餐（按人数）
python scripts/menu_helper.py candidates --menu menu.json --people 3 --details det/

# 忌口检查
python scripts/menu_helper.py check --menu menu.json --plan plan.json --restriction 不吃辣 吃素 过敏
```

**忌口处理原则：尽力满足 + 显式告知。菜单无法满足时明说，并把忌口写进
订单 `remark`，同时推荐麦当劳实际有的替代品保底。不要静默降级。**

已知硬边界（详见 `references/dietary.md`）：

- **菜单没有素食主餐**（唯一带"素"的是大米风味麦旋风，是甜品）
- **特调没有"去辣"选项**，无法标注过敏原
- 唯一含素食小食的正餐套餐是 `9900011129`「"堡"你欢乐套餐」（含苹果片）

### Step 4b · 骰子模式（可选，用户说"随便/今天吃什么"时）

**这是决策加速器，不是替代品** —— 默认仍走精确匹配，用户明确要"随机"才用。

> 🔴 **铁律：先确认关键信息，再掷骰。**
> 骰子掷出后用户看到的是「结果」而非「选项」——此时再说"其实我不吃辣/我要外送"，
> 整轮就白掷了。所以五个必填槽位必须在**投掷之前**问清，缺一不可。

#### 4b-0 投前确认（强制，不可跳过；有默认值则只问 2 项）

先运行确认卡，看还缺什么：

```bash
python scripts/dice_roll.py --menu menu.json --confirm-only --people 3 --band 50-100
```

**必填 5 项**（引擎硬拦截，缺项直接 `ok=false, error="need_confirm"`，不投掷）：

| 槽位 | 问法 | 能否用默认值 | 为什么不能事后补 |
|---|---|---|---|
| 人数 | 几个人吃？ | ❌ **每次都问** | 决定供餐量与投掷次数 |
| 预算档 | 总预算 50以内 / 50-100 / 100+？ | ❌ **每次都问** | 决定候选池价格区间（总价，不是人均）|
| 忌口 | 不吃辣 / 具体忌口 / 无？ | ✅ 可默认 | 建池阶段过滤，掷完再提池子得重建 |
| 取餐方式 | 到店自取 / 麦乐送 / 得来速？ | ✅ 可默认 | 到店与外送是**两套 productCode**，用错报 60006 |
| 门店 | 哪家店？ | ✅ 可默认 | 菜单随门店与营业时段变化 |

选填 1 项：是否用券（可默认，影响净价不影响骰子结果）。

**默认值规则（用户约定）**：

| 情况 | 行为 |
|---|---|
| 有默认值 | 直接沿用，**不再重复问**；确认卡上标 `(默认)` |
| 无默认值 | **5 项全问**，逐条列 `questions` |
| 想临时改 | 显式传参即覆盖默认值，无需先清默认 |
| 想全部重问 | 加 `--no-defaults` |

```bash
# 首次：确认后存为默认（只存门店/渠道/忌口/用券）
python scripts/dice_roll.py --menu menu.json --people 1 --band 50以内 \
    --restriction 不吃辣 --channel 到店自取 --store 1450713 \
    --store-name "华旭国际大厦" --serves-map serves_map.json --remember

# 之后：只需人数 + 预算档
python scripts/dice_roll.py --menu menu.json --people 3 --band 50-100 \
    --serves-map serves_map.json

# 管理默认值
python scripts/dice_roll.py --menu menu.json --show-defaults
python scripts/dice_roll.py --menu menu.json --forget-defaults
```

默认值存 `config/defaults.json`（门店/门店名/渠道/忌口/用券 + updatedAt）。

**执行要点**：
1. 用 AskUserQuestion 一次性把**缺的项**问全，不要边问边掷
2. 用户说"随便"时，**人数与预算档仍需确认** ——「随便」不等于「不用知道几个人」
3. 忌口即便有默认值，确认卡也**必须显式展示** —— 用户某天想吃辣却没看到默认的"不吃辣"就会误过滤
4. 外送/得来速还要先取 `beCode`（`delivery-query-stores` 返回，**不能自己拼**）
5. **投前确认可用默认值轻量化，但付款前必须重新强确认**（见 Step 9）

#### 4b-1 备齐权威供餐人数（每店首次，或菜单变更后）

```bash
python scripts/serves_probe.py --menu menu.json --out serves_map.json
```

⚠️ **套餐人数必须用权威数据，不能靠名称推断**。实测 44 个套餐全量核对，
名称含「双人餐」有两个是假的：

| 套餐 | 价格 | 名称推断 | 真实 |
|---|---:|---:|---:|
| 麦麦周末双人餐 | 49.9 | 2 人 | **1 人** |
| 开心亲子双人餐 | 59.5 | 2 人 | **1 人** |

另外「四件套/三件套」是**件数**不是**人数**。
权威判据 = `query-meal-detail` 的饮料 round 默认项 quantity（几杯饮料 = 几人份）。
⚠️ `query-meal-detail` 参数名是 `code`（不是 `productCode`），
且必须带 `storeCode` + `beType` + `orderType`。

#### 4b-2 投骰（确认通过后）

```bash
python scripts/dice_roll.py --menu menu.json --people 3 --band 50-100 \
    --restriction 不吃辣 --channel 到店自取 --store 1450056 \
    --serves-map serves_map.json
```

用户先给**预算档**：`50以内` / `50-100` / `100+`（总预算，不是人均）。

**两种骰子模式**（默认 `triple`）：

| 模式 | 原子数 | 说明 |
|---|---:|---|
| `triple` 三骰（默认） | 216 | 216 级强度阶梯，概率近均匀 + 点数↔价格严格单调 + 可复现 |
| `single` 单骰 | 6 | v1 兼容模式，池切 6 段段内随机 |

引擎会：先建合规池（**总价在档内 + 供餐人数够 + 忌口合规 + 非纯饮品**），
再按骰面在池内选。无解时降级为「N 份单人正餐组合」，
仍无解则如实告知"该条件下无合规套餐"。

**三骰模式的两个要点**：

1. **不是按「点数总和 18 档」映射，而是按 216 个有序三元组映射。**
   总和只有 16 个取值且极不均匀（点数 10/11/12 占 36.6%，3 与 18 各占 0.46%）。
   候选数 > 8 时，16 档下均匀映射**数学上不可能**（单原子 12.5% > 1/n）。
   统一口径实测平均 Gini：单骰 0.0780 → 总和 16 档 0.3744（更差）→ 216 级 0.0194。
2. **骰面结构（豹子/对子/顺子/散牌）只作叙事标签 + 免费重投权，不作决策维度。**
   结构与点数总和强相关（豹子只在 3/6/9/12/15/18 出现），同时用会互相打架。

| 结构 | 概率 | 标签 | 权益 |
|---|---:|---|---|
| 豹子 | 2.8% | 幸运三连 | 免费重投一次 |
| 顺子 | 11.1% | 顺水一局 | 免费重投一次 |
| 对子 | 41.7% | 双拼日 | 仅标签 |
| 散牌 | 44.4% | 日常局 | 仅标签 |

**呈现要点**：骰面（如 6-5-3=14点·日常局）→ 选中的套餐 → 费用拆解 → 人均。
必须同时说明「不满意可以说『重投』」，触发免费重投时明确告知可重投一次。

⚠️ 投掷次数由**需要几份**决定而非人数 —— 一份四人套餐喂饱四人，只投 1 次。
⚠️ 多份投掷时单份上限自动收紧为「档上限 / 投掷次数」，保证合计不越界。

#### 4b-3 投完之后：接算价 / 下单

投掷结果自带 `orderContext`（storeCode / channel / beType / orderType / takeWayCode），
可直接喂给 `scenario_guard.py` → `calculate-price` → `create-order`。
不需要重新问一遍场景参数 —— 它们在 4b-0 已经确认过了。

#### 4b-4 用户要改信息怎么办

改信息 → **必须重投**，不能拿旧骰子结果套新条件。
例：从「不吃辣」改成「不吃辣 + 不吃牛」→ 候选池变了 → 旧结果可能违规。
直接重新走 4b-0 确认卡即可。

详见 `docs/骰子选餐方案.md`（含 60 万次模拟的实测数据与三骰推导）。

### Step 5 · 优惠券择优

```bash
python scripts/menu_helper.py coupons --menu menu.json --plan plan.json --coupons cards.json
```

算法：净省 = 券抵扣额 − 加购成本，选净省最大者。全部为负则不凑单。

**⚠️ 一次只能用一张券**（多张报 `600022`）。

**⚠️ productCode 双编码**：券绑 `1440`，菜单是 `901440`（同一商品）。
引擎已内置别名映射，但你改动时不要把两者当不同商品。

券的绑定商品不在方案里时，需加购才能用 —— 要把加购成本算进去告诉用户。

**券处于「未到使用时间」时不可用**，引擎会标 `usable=false` 并说明等到哪天。

### Step 6 · 场景校验（算价前必跑）

```bash
# 外送
python scripts/scenario_guard.py --scenario delivery --order-type 2 --be-type 2 \
    --be-code <接口原值> --store-code <门店号> --menu menu.json --items plan.json

# 到店
python scripts/scenario_guard.py --scenario pickup --order-type 1 --be-type 1 \
    --store-code <门店号> --take-way-code <该店的 takeWayCode> \
    --menu menu.json --items plan.json
```

`--scenario` 取值：`pickup`(到店自取) / `drive_through`(得来速) /
`delivery`(麦乐送) / `group`(企业团餐)

它会拦下四类**靠报错兜不住**的错误：

- 漏 `takeWayCode`（→ 600042）
- 该传的 beCode 没传 / 不该传的却传了
- **跨场景的商品编码**（到店编码拿到外送用，报 60006 售罄）
- **跨店复用 takeWayCode**（→ 600043，takeWayCode 是每家店自己的）

**takeWayCode 每店不同**（实测）：

| 门店 | takeWayList |
|---|---|
| 1450056 / 1450441 | `eat-in`, `take-in-store` |
| 1450556 / 1450713 / 1450086 / 1450258 | `eat-in`, `locker-out` |
| 得来速门店 | `take-dt-quick` |

**必须每次从目标门店的 `calculate-price` 返回的 `takeWayList` 取值。**

### Step 7 · 算价

```bash
python scripts/mcd_call.py calculate-price '{"storeCode":"...","orderType":2,"beType":2,"beCode":"...","needTableware":true,"items":[...]}'
```

**⚠️ 算价接口金额单位是「分」**（`price`/`productPrice`/`deliveryPrice`/`packingPrice`），
展示除以 100。**订单接口（`create-order`/`query-order`）的金额是「元」且为字符串**，
不要再除以 100，比较前先 `float()`。详见 `references/mcp-api.md` 的「金额单位与类型不一致」。

套餐用 `roundList` 传各 round 的 choice：

```json
"roundList": [
  {"round":"1","comboItemList":[{"code":"521952","quantity":1}]},
  {"round":"2","comboItemList":[{"code":"501205","quantity":1}]}
]
```

**特调**：含 `unselectedKey` 的组，组内**所有项都要传**，选中用 `selectedKey`，
未选中用 `unselectedKey`。

### Step 8 · 出方案，停下等确认 ⭐

呈现必须包含：

- 门店名 + 地址 + 营业时间
- 商品构成（套餐名 + 逐项内容）
- 费用拆解（商品 / 配送 / 打包 / 券抵扣 → 总额 + 人均）
- 忌口满足情况（满足 / 部分满足 + 原因）
- 券使用情况（用了哪张 / 为什么不能用）
- 明确的「等待你确认下单」

**然后停住。不要自动下单。**

### Step 9 · 下单与交付

```bash
# 下单
python scripts/mcd_call.py create-order '{"storeCode":"...","orderType":2,"beType":2,"beCode":"...","addressId":"...","needTableware":true,"remark":"...","items":[...]}'

# 查状态（用户说"支付完成"时）
python scripts/mcd_call.py query-order '{"orderId":"..."}'

# 取消
python scripts/mcd_call.py cancel-order '{"orderId":"...","cancelReasonCode":"3"}'
```

`remark` 里的中文（如"无接触配送"）由脚本自动转义，不会乱码。
外送场景主动问配送备注。

**⚠️ 600039「今日下单数已经上限」= 账号级全局日限**（跨门店跨渠道共享，
取消不释放额度，按订单**创建数**计数）。换店换渠道都无效，只能等次日。
**这不是风控**（无风控字段、其它接口正常、计数器触发），不需要申诉。

### 支付交付（双交付，必做）

> 🔴 **铁律：未通过付款前确认门禁 → 不得输出支付二维码。**

**支付页只有二维码、没有任何订单明细** —— 用户没法确认"到底点了什么"。
投前确认只能保证「意图对」，不能保证「落地对」：
菜单价可能是麦金卡优惠价（实测差近一倍）、套餐人数可能被名称误导、
券可能没绑上、门店可能已打烊换店。所以**付款前必须再确认一次**。

#### Step 9.1 · 跑付款门禁（下单后、给二维码前）

```bash
# 基本核对
python scripts/pay_confirm.py --order <orderId>

# 推荐：带预期值做交叉校验（把算价阶段的金额/门店/渠道传进来）
python scripts/pay_confirm.py --order <orderId> \
    --expect-total 36.0 --expect-store 1450713 --expect-channel 到店自取 \
    --restriction 不吃辣 --receipt 订单确认单.png
```

门禁逐项核对 **9 项**：

| 检查 | 拦下的条件 |
|---|---|
| 商品明细 | 订单里没有商品 |
| 应付金额 | 应付 ≤ 0 |
| 费用勾稽 | 小计+配送+打包−优惠 ≠ 应付 |
| 金额与预期一致 | 与算价阶段金额不符（防价格口径坑）|
| 门店一致 | 与确认的门店不符 |
| 取餐方式一致 | 与确认的渠道不符 |
| 忌口（不吃辣）| 订单里含辣商品但用户要求不吃辣 |
| 支付时限 | 已过期（订单 15 分钟有效）|
| 订单状态 | 已取消 / 已关闭 |

- 全部通过 → `readyToPay: true`，输出必须让用户确认的话术
- 任一失败 → `readyToPay: false`，**⛔ 不得输出支付二维码**，先改单/换店/重下单

退出码：`0`=可付款 / `1`=被拦下。

#### Step 9.2 · 用户确认后才交付（一条命令做完）

把确认单明细（商品构成 + 费用拆解）逐条列给用户，等用户明确回复「确认付款」，
然后跑 `pay.py` —— 它把门禁、支付入口、等结果、出确认单串成一条命令：

```bash
# 电脑前：门禁 → 二维码 PNG
python scripts/pay.py --order <orderId> --expect-total 27.9 --restriction 不吃辣

# 手机上：门禁 → 直接给 H5 链接（微信打开可唤起 APP）
python scripts/pay.py --order <orderId> --mobile

# 交付后等 5 分钟，付成功自动出确认单
python scripts/pay.py --order <orderId> --wait 300

# 只跑门禁，先不给支付入口
python scripts/pay.py --order <orderId> --gate-only
```

`pay.py` 四个阶段：

| 阶段 | 做什么 | 失败时 |
|---|---|---|
| 1 门禁 | 9 项核对（金额/商品/门店/渠道/忌口/时限/状态）| 退出码 **1**，不交付入口 |
| 2 入口 | 电脑→二维码 PNG；手机→payH5Url | 渲染失败自动降级为「给链接」 |
| 3 等结果 | 轮询 `query-order`，5 秒一次 | 超时 **3** / 被取消 **4** |
| 4 确认单 | 仅付成功才生成 PNG | 失败只告警，不算流程失败 |

退出码：`0`=已交付（或已付款）/ `1`=门禁未过 / `2`=参数错 / `3`=等超时未付 / `4`=订单已失效

用 `present_files` 把**二维码**和**确认单**一起交给用户。
文字回复里也要把「商品构成 + 费用拆解」列成表格，不要只给链接。

**必须同时说明**：15 分钟内支付有效，超时服务端自动取消（`status=60`）。

#### 订单状态码（实测）

| status | orderStatus | 含义 | pay.py 判为 |
|---|---|---|---|
| `10` | 待支付 | 可付款 | pending |
| `60` | 已取消 | 超时自动取消 / 主动取消 | failed |
| 其他 | 见文案 | 以 `orderStatus` 文案为准 | 按关键词归类 |

⚠️ **未知状态码不猜** —— 文案里有「已支付/制作中/已完成/待取餐/配送中」就算 paid，
有「已取消/已关闭/已退款」就算 failed，其余返回 `unknown` 让上层决策。

#### 按用户场景选支付方式

支付链路（实测每一环）：

```
payH5Url = https://m.mcd.cn/mcp/scanToPay?orderId=<id>   ← 手机端 H5 单页
  ├─ 页内二维码内容 = https://m.mcd.cn/mcp/jumpToApp?orderId=<id>
  └─ jumpToApp → mcdapp:// scheme → 唤起麦当劳 APP 收银台
```

**MCP 的 35 个工具里没有任何支付工具**，只有 `payH5Url`（H5 收银台）和
`payId`（纯 ID，无跳转能力）。

**这条链路不支持小程序支付** —— bundle 里 `launchMiniProgram`/`miniprogram`/
`applet`/`weixin://` 出现次数均为 0，只有 `wx-open-launch-app`（唤起 APP）。
**不要臆造小程序支付路径。**

| 用户在 | 交付方式 | pay.py 参数 |
|---|---|---|
| 电脑前 | 抓二维码图片，用户用手机微信扫 | 默认（`--mobile` 不加）|
| 手机上 | 直接给 `payH5Url`，在**微信里打开**可一键唤起 APP | `--mobile` |

`fetch_qr.py` 会额外输出解码后的二维码内容（`QR:` 开头），用于核对与排查。

---

## 附：小游戏（可选）

`assets/mcdcraft.html` —— 麦当劳×我的世界风体素跑酷，零依赖单文件，
localStorage 存档。

- **只在用户主动要求时开启**（"玩一下" / "开个游戏"）
- 提供 `?demo=1` 录制模式（隐藏底部说明）
- `window.__MCD_DEBUG__` 暴露只读状态接口，供自动化测试用
- **绝不影响点餐主链路**，不自动弹出

---

## 参考资料

| 文件 | 何时读 |
|---|---|
| `references/mcp-api.md` | 35 工具全量入参表、枚举、传参矩阵、错误码、金额单位、支付链路 |
| `references/dietary.md` | 忌口映射表、素食兜底清单、套餐 round 规则、话术模板、控热量数据 |
| `scripts/menu_helper.py --help` | 需要搭配/择优/营养计算时 |
| `scripts/locate_store.py --help` | 需要按定位/地名查附近门店时 |
| `scripts/scenario_guard.py --help` | 算价/下单前校验场景参数与商品编码 |
| `scripts/dice_roll.py --help` | 用户要"随便来/今天吃什么"时投骰子选餐（三骰 216 级，支持默认值） |
| `scripts/serves_probe.py --help` | 生成权威供餐人数映射（套餐人数不能靠名称推断） |
| `scripts/pay.py --help` | **付款闭环**：门禁 → 支付入口 → 等结果 → 确认单（首选）|
| `scripts/pay_confirm.py --help` | 只要门禁（`pay.py` 已内置，单独跑用于排查）|
| `scripts/fetch_qr.py <orderId>` | 下单后需要支付二维码时 |
| `scripts/order_receipt.py <orderId>` | 下单后生成订单确认单时 |

---

## 常见错误处理

| 情况 | 怎么办 |
|---|---|
| `must be integer` | 用了平台工具层 → 改走脚本 |
| `600039` 今日下单数上限 | **账号级全局日限**（跨门店跨渠道），取消不释放额度，只能等次日。**这不是风控**。**检验时也要注意额度消耗** |
| `600057` 门店打烊**或 beCode 场景错配** | 先比营业时间：营业中 → beCode 用错了，换成 `delivery-query-stores` 的原值；真打烊 → 换一家 |
| `600048` 外送缺 beCode | 必须带 `delivery-query-stores` 返回的 beCode 原值 |
| `60002` beCode 配对错 | 同上，别自己拼 `storeCode+后缀` |
| `600043` 取餐方式code错误 | takeWayCode 不属于该门店，重新拉该店 takeWayList |
| `600042` orderType=1 缺 takeWayCode | 先算价拿 `takeWayList[].code`，再带上下单 |
| `60006` 商品售罄 | **可能是跨场景用错编码**，先确认菜单是否按场景拉取 |
| `600010` 缺必填参数 | 如团餐的 gmServiceCode（普通账号拿不到）|
| `600050` 收藏为空 | 改 `searchType=2` + 城市 + 关键词 |
| `600022` 多张券 | 只保留一张券 |
| `600014` 地址查不到 | 换关键词或城市 |
| `600064` 订单已取消 | 重复取消。检查订单当前状态再操作 |
| `610501` 非企业团餐身份 | 团餐走不通，告诉用户需企业账号 |
| `499` 无券可领 | **不是错误**（`soft_fail: true`）→ 检查是否已领过 |
| 中文乱码 | 确认用了脚本而非手写请求体 |
| **预算超支 / 报价与实付不符** | ⚠️ **价格口径坑**：`currentPrice` 不一定能买到。有 `discountType`（如「随单购麦金卡优惠」）时按 `originalPrice` 实付。实测「不素之霸双层牛堡四件套」现价 32 元、实付 58.5 元。**预算判断必须用实付价** → 用 `dice_roll.prices_of()`，或直接 `calculate-price` 复核 |
| **套餐人数看起来不对** | 名称不可信（「麦麦周末双人餐」其实 1 人份）。用 `serves_probe.py` 取 `query-meal-detail` 的饮料数作权威值 |
| 算价报 `60003` 门店暂停营业 | 门店已打烊。`query-nearby-stores` 的 `businessStatus` 是权威营业状态，先筛 true 的 |
