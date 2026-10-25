# 麦当劳 MCP 接口速查

> 服务：`mcd-mcp` @ `https://mcp.mcd.cn`（streamable HTTP，JSON-RPC 2.0）
> 本文件供 skill 运行时查阅。**所有调用必须经 `scripts/mcd_call.py` 直连**，原因见 §0。

---

## 0. 两条铁律

### 0.1 不要用平台工具层调用
平台工具调用层会把整型参数降级成字符串，导致下列字段全部校验失败：

```
Parameter validation failed: /beType: must be integer;
  /beType: must be equal to one of the allowed values
```

受影响字段：`beType` / `orderType` / `searchType` / `quantity` / `size` / `count` / `pageNum` 等。

**正确做法**：
```bash
python scripts/mcd_call.py <tool_name> '<json_args>'
```

### 0.2 请求体必须 ASCII 转义
服务端按 **GBK** 解码请求体。中文直接发 UTF-8 字节会存成乱码：

| 阶段 | 内容 |
|---|---|
| 发送 | `"无接触配送"` → UTF-8 字节 `e697a0 e68ea5 ...` |
| 存库 | `"޽Ӵ�����"` → U+FFFD 替换字符 |

`mcd_call.py` 内部已固定 `json.dumps(payload, ensure_ascii=True)`，中文自动转 `\uXXXX`。
若自行拼请求体，**必须**这样做。

### 0.3 调用方式
该服务**无需 session id**，`initialize` 后直接 `tools/call`：

```bash
curl -X POST https://mcp.mcd.cn \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"...","arguments":{}}}'
```

鉴权 token 从 `~/.workbuddy/mcp.json` 读取，**不硬编码**。

---

## 1. 枚举定义

| 枚举 | 取值 | 说明 |
|---|---|---|
| `beType` | `1` | 到店自取（返回门店**无** beCode，后续不传） |
| | `2` | 麦乐送外送 |
| | `5` | 得来速车道取餐（返回门店**有** beCode，后续必传） |
| | `6` | 企业团餐 |
| `orderType` | `1` | 到店（含到店自取 + 得来速） |
| | `2` | 外送（含麦乐送 + 团餐） |
| `searchType` | `1` | 搜索收藏餐厅 |
| | `2` | 按位置搜索（需 `city` + `keyword`） |
| `cancelReasonCode` | `1` | 改主意了 |
| | `2` | 重复下单 |
| | `3` | 点错了/点多了/点少了 |
| | `4` | 地址/电话填错了 |
| | `5` | 送达时间选错了 |
| | `-1` | 其它原因 |
| `promotionType` | `31` | 满额减（团餐场景） |
| | `33` | 订单折扣（团餐场景） |
| `ruleCategory` | `30` | 满折/折扣（团餐场景） |
| | `40` | 满减（团餐场景） |

---

## 2. 传参组合速查

**这张表是最容易出错的地方。**

| 场景 | `orderType` | `beType` | `beCode` |
|---|---|---|---|
| 到店自取 | `1` | `1` | **不传** |
| 得来速 | `1` | `5` | 必传 |
| 麦乐送 | `2` | `2` | 必传 |
| 企业团餐 | `2` | `6` | 必传 |

> `beType=1` 时传 `beCode` 会直接报错。

---

## 3. 错误码

| 码 | 含义 | 处理方式 |
|---|---|---|
| `600022` | 暂不支持多张券使用 | 改用单券方案，见 §7 |
| `600048` | 外送场景下，beType=2/5/6 时必传 beCode | 外送必须带接口返回的 beCode |
| `60002` | 未查询到门店信息，检查 storeCode 和 beCode 是否配对 | beCode 必须是 `delivery-query-stores` 返回的那个原值 |
| `60006` | 商品已售罄或不可售 | 换商品，或改 orderType/beType 重试 |
| `600043` | 取餐方式code错误，请重新获取 | takeWayCode 不属于该门店，重新拉该店的 takeWayList |
| `600010` | 检查必填参数 | 缺必填项（如团餐的 gmServiceCode）|
| `600039` | 今日下单数已经上限 | **账号级全局日限**，跨渠道共享（外送/到店都拦）。等次日 |
| `600064` | 订单已经取消 | 重复取消。cancel-order 对已取消订单返回此码，不是错误 |
| `600014` | 没有查询到该地址 | 换关键词/城市，或用 `searchType=2` |
| `600050` | 收藏餐厅列表为空 | 改用 `searchType=2` + 城市 + 关键词 |
| `600057` | 门店可能已关闭或不在营业时间 | **重新执行 `delivery-query-stores` 拿当前可送门店**，列表是动态的 |
| 校验失败 `must be integer` | 整型参数被降级 | 改用 `mcd_call.py` 直连 |
| 乱码 `޽Ӵ...` | 中文未转义 | 请求体改用 `ensure_ascii=True` |

### 3.1 ⚠️ 可送门店列表是动态的

**实测**：2026-10-22 21:35 可送门店是 1450056 / 1450441 / 1450556；
2026-10-23 23:11（原店 23:00 打烊）变成 1450713 / 1450086 / 1450258，且 `query-meals` 对已打烊门店直接报 `600057`。

**规则**：
- 每次会话**必须重新**执行 `delivery-query-stores`，不要复用历史 storeCode
- 门店返回带 `businessStartTime` / `businessEndTime` / `businessStatus`，展示给用户
- 遇到 `600057` → 重新查可送门店列表，换一家再试，**不要向用户报"点不了"就结束**
- 门店在售商品数会变（实测 105 vs 102），菜单以当次 `query-meals` 为准

---

## 4. 全量工具入参表（35 个）

### 4.1 点餐主链路

| 工具 | 必填 | 可选参数 |
|---|---|---|
| `query-nearby-stores` | `beType`(1\|5)、`searchType`(1\|2) | `city`:string、`keyword`:string |
| `delivery-query-addresses` | — | — |
| `delivery-create-address` | `address`、`addressDetail`、`city`、`contactName`、`phone` | `gender`:string |
| `delivery-query-stores` | `beType`:integer、`addressId`:string | — |
| `query-meals` | `storeCode`、`orderType`、`beType` | `beCode`:string、`reservationDate`:string |
| `query-meal-detail` | `storeCode`、`orderType`、`beType`、`code` | `beCode`:string、`reservationDate`:string |
| `calculate-price` | `storeCode`、`orderType`、`beType` | `beCode`:string、`items`:array、`needTableware`:boolean、`gmServiceCode`:string、`withOrder`:object |
| `create-order` | `storeCode`、`orderType`、`beType` | `beCode`:string、`addressId`:string、`remark`:string、`items`:array、`needTableware`:boolean、`takeWayCode`:string、`withOrder`:object、`gmServiceCode`:string、`reservationDate`:string |
| `query-order` | `orderId`:string | — |
| `order-list` | — | — |
| `cancel-order` | `orderId`、`cancelReasonCode` | — |

### 4.2 优惠券与积分

| 工具 | 必填 | 可选参数 |
|---|---|---|
| `available-coupons` | — | — |
| `auto-bind-coupons` | — | — |
| `query-my-coupons` | — | `page`:string、`pageSize`:string |
| `query-store-coupons` | `orderType`、`beType`、`storeCode` | `beCode`:string、`reservationDate`:string |
| `query-my-account` | — | — |
| `list-nutrition-foods` | — | — |
| `query-survey-coupon` | `orderId`:string | — |
| `campaign-calendar` | — | `specifiedDate`:string |

### 4.3 团餐 / 派对 / 积分商城（本 skill 主链路未启用）

| 工具 | 必填 | 可选参数 |
|---|---|---|
| `query-meal-assistance` | `storeCode` | `beCode`、`beType`(6)、`orderType`、`reservationDate` |
| `query-promotions` | `storeCode`、`orderType`、`beType`(6) | `beCode`、`reservationDate` |
| `query-party-city` | `spuId`:number | — |
| `query-party-store` | `code`:string | `latitude`:number、`longitude`:number、`spuId`:number |
| `query-party-store-date` | `spuId`、`storeCode` | — |
| `query-party-store-session` | `spuId`、`storeCode`、`dateStr` | — |
| `party-order-create` | `partyType`:integer | `code`、`count`、`dateStr`、`id`、`leftNum`、`partyTimeInfo`、`skuId`、`spuId`、`storeCode`、`timeEnd`、`timeStart` |
| `mall-points-products` | — | `catRuleIds`:string |
| `mall-product-detail` | `spuId`:integer | — |
| `mall-create-order` | `skuId`:integer、`spuCategory`:string | `addressId`、`count` |
| `mall-order-list` | — | `lastId`:number、`size`:integer |
| `mall-order-detail` | `orderId`:string | — |
| `draw-lottery` | — | — |
| `query-lottery-info` | — | — |
| `query-my-prizes` | — | `pageNum`:string、`pageSize`:string |
| `now-time-info` | — | — |

---

## 5. 关键返回结构

### 5.1 `query-meals` → 套餐 round 结构

搭配的核心依据：

```json
{
  "rounds": [
    {
      "id": 2,
      "name": "选择套餐内小食",
      "minQuantity": 1,
      "maxQuantity": 1,
      "choices": [
        { "code": "501205", "name": "中薯条", "quantity": 1,
          "maxQuantity": -1, "isDefault": 1, "diffPrice": "+ ¥0",
          "supportModify": false }
      ]
    }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `minQuantity` / `maxQuantity` | 该轮必须/最多选几个（**不可突破**） |
| `choices[].diffPrice` | 替换差价，`+ ¥5` 表示比默认贵 5 元 |
| `choices[].isDefault` | `1` = 默认选中 |
| `choices[].quantity` | 默认数量（如饮料轮 `x4`） |
| `choices[].supportModify` | 是否可特调 |

### 5.2 `calculate-price` → 价格结构

```json
{
  "productOriginalPrice": 6690,
  "productPrice": 5680,
  "deliveryOriginalPrice": 600, "deliveryPrice": 600,
  "packingOriginalPrice": 380, "packingPrice": 300,
  "originalPrice": 7670,
  "discount": 1090,
  "price": 6580,
  "productList": [
    { "productCode": "9900016490", "productName": "龙焰鸡腿堡四件套",
      "quantity": 1, "originalSubtotal": 3690, "subtotal": 3690 }
  ]
}
```

⚠️ **金额单位是「分」**，展示必须除以 100。

### 5.3 `query-store-coupons` → 券结构

```json
{
  "title": "19.9元王牌炸鸡任选2",
  "couponId": "44928824D2D4273FE5ECA617BBF75483",
  "couponCode": "MCD659101U90801032406",
  "tradeDateTime": "2026-10-19 10:30:00-2026-10-23 23:59:59",
  "products": [{ "productCode": "9900016534", "productName": "王牌炸鸡任选2" }],
  "promotionId": "112479004"
}
```

⚠️ **`available-coupons` 拿不到 `couponId`**，只有标题和图片。必须先 `auto-bind-coupons`，再从 `query-my-coupons` / `query-store-coupons` 取 ID。

---

## 6. 特调（modification）规则

```json
"modification": { "values": [
  { "code": "120549", "key": "0-1", "quantity": 1 },
  { "code": "120512", "key": "0-1", "quantity": 1 }
]}
```

**传参规则**：
- 用户**选中**的项 → `key` = 该项的 `selectedKey`
- 用户**未选中**的项 → 若该项 `unselectedKey` 不为空，`key` = `unselectedKey`，**且必须传**
- 即：含 `unselectedKey` 的特调组，**组内所有项都要传**

**实测可用范围极窄**（门店 1450056）：
| 类型 | 可选项 |
|---|---|
| 冰量 | 标准 / 去冰 / 多冰 / 少冰 |
| 酱料 | 辣椒黄油风味酱 / 切块生菜 |
| 奶类 | 换燕麦奶 |
| 咖啡 | 奶油球 / 白砂糖 |

**没有"去辣"、没有"换素食堡"、无法标注过敏原。**

---

## 7. 业务规则速记

| 规则 | 说明 |
|---|---|
| **一次仅一券** | 多张券报 `600022`。择优只选一张，其余留给下一单 |
| **卡包 ≠ 门店可用** | `query-my-coupons` 是卡包全量；判断能否用一律看 `query-store-coupons` |
| **券绑定商品** | 券有 `products[].productCode`，必须点了对应品才能用 |
| **券按周批次滚动** ⭐ | 见 §7.1，**不是"几天就过期"** |
| **productCode 双编码** | 券绑 `1440`（麦辣鸡腿汉堡），菜单是 `901440`（麦辣鸡腿汉堡）。需别名映射，见 `menu_helper.py` |
| **口味由酱料决定** | 特调只能换酱料，"不吃辣"无法完全去除 |
| **多人套餐固定结构** | 每个 round 有 min/max 数量约束，不能自由组合 |
| **打包费** | 需餐具时收 3 元左右；`needTableware: false` 可免 |
| **订单 15 分钟有效** | `expirePayTime`，超时需重下 |

### 7.1 券的有效期是「周批次滚动」（重要）

**实测记录**：

| 查询时间 | 卡包券有效期 | 状态标签 |
|---|---|---|
| 2026-10-22 21:38 | 2026-10-19 10:30 ~ 2026-10-23 23:59 | 可用 |
| 2026-10-24 11:09 | 2026-10-26 10:30 ~ 2026-10-30 23:59 | **未到使用时间** |

**规律**：每批券覆盖一个完整工作周（周一~周五，10:30–23:59）。
上一批过期后，服务端**自动把卡包里的券换成下一批**，不是让券消失。
所以周末领的券通常要等到**下周一**才能用。

**字段差异**（两种结构都要支持解析）：

| 来源 | 有效期字段 | 绑定商品字段 |
|---|---|---|
| `query-store-coupons`（门店券） | `tradeDateTime`: `"起-止"` 拼在一个字符串里 | `products[]` 有 |
| `query-my-coupons`（卡包券） | `tradeStartDateTime` / `tradeEndDateTime` 分开两个字段 | 无 `products` |

**踩坑提醒**：
1. 日期本身含 `-`，**不能用 `split("-")`** 解析 `tradeDateTime`，必须用正则
2. 卡包券**没有绑定商品信息**，无法判断是否需加购 → 需人工确认
3. `weekdays` 字段编码与直觉相反：`[2,3,4,5,6]` 对应标签「周一、二、三、四、五」，
   判定时**以 `instructions.availableTime` 里的中文标签为准**

**状态判定**（`menu_helper.py coupon_state()`）：

| state | 含义 | 可用 |
|---|---|---|
| `not_started` | 未到使用时间 | ❌ |
| `usable` | 有效期内且剩 > 24h | ✅ |
| `expiring` | 有效期内但剩 < 24h | ✅（但要提醒用户） |
| `expired` | 已过期 | ❌ |
| `unknown` | 接口未返回有效期 | ❌（需人工确认） |

### 7.2 业务性返回（soft fail）

服务端把「业务上正常、但 success=false」的情况也用 `success=false` 返回。
`mcd_call.py` 会给这些打上 `soft_fail: true` + `hint`，**不要当错误处理**：

| code | 含义 | 处理 |
|---|---|---|
| `499` | 暂无可领取的优惠券 | 正常，继续用卡包里的券 |
| `600050` | 收藏餐厅列表为空 | 改用 `searchType=2` |
| `600057` | 门店可能已关闭 | 重新查可送门店换一家 |

---

## 8. 快速调用示例

```bash
# 拉菜单
python scripts/mcd_call.py query-meals \
  '{"storeCode":"1450056","orderType":2,"beType":2,"beCode":"145005602"}'

# 查门店可用券
python scripts/mcd_call.py query-store-coupons \
  '{"storeCode":"1450056","orderType":2,"beType":2,"beCode":"145005602"}'

# 算价（注意 remark 用 \u 转义）
python scripts/mcd_call.py calculate-price '{
  "storeCode":"1450056","orderType":2,"beType":2,"beCode":"145005602",
  "needTableware":true,
  "items":[{"productCode":"9900016490","quantity":1,
    "roundList":[{"round":"1","comboItemList":[{"code":"521952","quantity":1}]},
                 {"round":"2","comboItemList":[{"code":"501205","quantity":1}]},
                 {"round":"3","comboItemList":[{"code":"901401","quantity":1}]},
                 {"round":"4","comboItemList":[{"code":"903050","quantity":1}]}]}]}'
```

> 上例省略了 `modification`。含特调时，**该项组内所有 values 都要传**（见 §6）。


## ⚠️ 金额单位与类型不一致（2026-10-24 实测）

**同一个"38.9 元"，在不同接口里形态不同**：

| 接口 | 字段 | 值 | 类型 |
|---|---|---|---|
| `calculate-price` | `price` | 3890 | **int（分）** |
| `calculate-price` | `productPrice` | 3100 | int（分） |
| `create-order` | `realTotalAmount` | `'38.9'` | **str（元）** |
| `query-order` | `realTotalAmount` | `'38.9'` | **str（元）** |
| `query-order` | `productPrice` | `31` | int（元）|

**踩坑点**：
- 算价接口全用**分**，订单接口全用**元**
- 订单接口的金额是**字符串**，直接 `== 38.9` 会 False，必须 `float()`
- 展示时统一除以 100 只适用于算价接口，订单接口不要除

---

## ⚠️ 600057 的两种成因（2026-10-24 实测纠正）

原文档把 `600057` 一律解释为"门店打烊"，**这是不准确的**。实测发现它有两种成因：

### 成因①：门店真的打烊
夜间（23:00 后）查 1450056 会返回此码，此时确实该换店。

### 成因②：beCode 与 orderType 不匹配（**门店营业中也报！**）

实测：门店 1450056 营业时间 06:30–23:00，**14:48 明明营业中**，
但传 `orderType=1`（到店）+ `beCode=145005602`（麦乐送渠道的 beCode）时报：

```
600057 门店可能已关闭或不在营业时间
```

**判据不是营业时间，而是 beCode 后缀与场景的匹配关系。**

### 完整传参矩阵（storeCode=1450056 实测）

| orderType | beType | beCode | 结果 |
|---|---|---|---|
| 1（到店） | 1（自取） | 不传 | ✅ 115 单品 |
| 1 | 1 | 任意后缀 01–08 | ✅ 115 单品 |
| 1 | 2（麦乐送） | 不传 | ✅ 115 单品 |
| 1 | 6（团餐） | 不传 | ✅ 115 单品 |
| 1 | **5（得来速）** | 不传 | ❌ 600048 |
| 1 | 2/5/6 | **145005602** | ❌ 600057（场景不匹配）|
| 1 | 2/5/6 | 145005601 / 601 / 606 | ❌ 60002（配对错）|
| 2（外送） | 1/2/5/6 | 不传 | ❌ 600048 |
| 2 | **2** | **145005602** | ✅ 117 单品 |
| 2 | 1/2/5/6 | 145005601/603/604/605/606/607/608 | ❌ 60002 |

**结论（重要）**：

1. **到店场景（orderType=1）**：beCode **任意后缀都行，甚至不传也行**。
   唯一例外是 `beType=5`（得来速）必须传 beCode。
2. **外送场景（orderType=2）**：**只有 `beType=2` + 接口原样返回的 beCode 可用**
   （本例是 `145005602`）。其他 beType 即使配了正确 beCode 也全失败。
3. **beCode 不能自己拼**！必须用 `delivery-query-stores` 返回的 `beCode` 原值。
   自己按 `storeCode + 后缀` 拼会撞 60002。
4. **得来速（beType=5）在本店根本用不了** —— 即使 beType=5 配 145005602 也报 600057。
   这类门店需要找真正支持得来速的门店，不能靠猜 beCode。

### 实操建议

- 外送：**只走 `delivery-query-stores`**，直接用它返回的 storeCode + beCode，
  不要用 `query-nearby-stores` 的结果（那里的 beCode 是 null）。
- 到店：`query-nearby-stores` 拿到的 storeCode 直接用，beCode 可省略。
- 遇 600057：先确认是不是 beCode 场景错配（对比营业时间），再决定是否换店。


## ⚠️ 四渠道完整参数规则（2026-10-24 实测 + 接口 schema 双重确认）

| 渠道 | orderType | beType | beCode | takeWayCode | 商品编码体系 |
|---|---|---|---|---|---|
| 到店自取 | 1 | 1 | **不传** | `eat-in` 堂食 / `take-in-store` 外带 | 短码 `1100` |
| 得来速 | 1 | 5 | 必传（后缀 **41**）| `take-dt-quick` | 短码 `1100` |
| 麦乐送 | 2 | 2 | 必传（后缀 **02**）| **不传** | 长码 `901100` |
| 企业团餐 | 2 | 6 | 必传 | 不传 | 需 `gmServiceCode` |

### ⚠️ takeWayCode 是「每家店自己的」，不能跨店复用（2026-10-24 实测）

同样叫「外带」，不同门店的 code 不一样。**传错报 600043**。

| 门店 | beType | takeWayList |
|---|---|---|
| 1450056 上海食品一店 | 1 | `eat-in`, **`take-in-store`**（店内自提）|
| 1450441 上海福州路 | 1 | `eat-in`, `take-in-store` |
| 1450556 福州路上海书城 | 1 | `eat-in`, **`locker-out`**（店外取餐柜）|
| 1450713 华旭国际大厦 | 1 | `eat-in`, `locker-out` |
| 1450086 / 1450258 夜间店 | 1 | `eat-in`, `locker-out` |
| 得来速门店（如 1450214）| 5 | **`take-dt-quick`** |

**规律**：`eat-in`（堂食）所有店都有；外带分两种 ——
有取餐柜的店 `locker-out`，没有的 `take-in-store`。

**必须每次从目标门店的 `calculate-price` 返回的 `takeWayList` 取值**，
不能沿用上一家店的结果。

### takeWayCode（漏了这个会报 600042）

`takeWayCode` 是 **orderType=1 场景的必填项**，值必须从
`calculate-price` 返回的 `takeWayList[].code` 中选取：

| takeWayCode | 含义 |
|---|---|
| `eat-in` | 堂食（店内用餐）|
| `take-in-store` | 外带（店内自提）|
| `take-dt-quick` | 得来速（车道取餐）|

**外送场景（orderType=2）的 `takeWayList` 为空数组**，不要传 `takeWayCode`。

实测取值为 4 种：`eat-in` / `take-in-store` / `locker-out` / `take-dt-quick`。

### ⚠️ 服务端会静默忽略多余参数

| 场景 | 传了不该传的 | 结果 |
|---|---|---|
| 外送 | `takeWayCode: "eat-in"` | ✅ 成功（静默忽略）|
| 到店 | `beCode: "145005602"` | ✅ 成功（静默忽略）|

**不要指望报错来兜底**。"到店不传 beCode""外送不传 takeWayCode" 这类约定
必须主动遵守。

---

## ⚠️ 到店与外送是两套 productCode 体系（2026-10-24 实测）

**同一个商品在两个场景下编码不同**，且**套餐可能只在一侧存在**。

| 商品 | 到店（115 单品）| 外送（117 单品）|
|---|---|---|
| 巨无霸 | `1100` | `901100` |
| 麦辣鸡腿堡 | `1440` | `901440` |
| 薯条 | — | `501205` |
| 麦乐鸡5块 | — | `901401` |
| 巨无霸四件套 | `9900000888` | — |
| 麦乐鸡(5块)中套餐 | — | `9900003004` |

### 后果：用错编码会伪装成"库存问题"

用外送编码 `9900003004` 去到店场景下单，会报：

```
60006 商品已售罄或不可售，换一个商品或检查orderType/beType
```

看起来像卖完了，**实际是这个商品根本不在到店菜单里**。

### 硬性规则

**菜单必须按场景分别拉取，绝不能跨场景复用编码。**

```python
# 到店
query-meals {storeCode, orderType:1, beType:1}                        # 不传 beCode
# 外送
query-meals {storeCode, orderType:2, beType:2, beCode: 来自 delivery-query-stores}
```

### 得来速门店（实测，上海）

`1450214` 锦绣路 / `1450664` 江场西路和典创意园 / `1450546` 沪太支路飞马旅创新园 /
`1450228` 五星路 / `1450407` 康建商务广场

用 `query-nearby-stores {beType:5, searchType:2, city, keyword}` 查，
其 beCode 后缀是 `41`（如 `145021441`），与麦乐送的 `02` 完全不同。

### 企业团餐：普通账号不可用

`query-meal-assistance` 报 `610501`「仅支持企业团餐场景下使用助餐服务」，
需企业团餐身份才能取 `gmServiceCode`。普通账号走不通团餐流程。


## ⚠️ 600039「今日下单数已经上限」详解（2026-10-24 实测）

### ⭐ 不是风控（2026-10-24 对照实验证实）

容易误判成"下单被风控"，但**不是**。五条依据：

| # | 观察 | 说明 |
|---|---|---|
| 1 | 响应体只有 4 个字段 | `success/code/message/datetime/traceId`，**无 riskCode / verifyCode / captcha / deviceId** 等风控标识 |
| 2 | 错误码属 6xxxxx 业务码段 | 与 `600022`(多券)、`600057`(门店)、`60006`(售罄) 同族 |
| 3 | 文案是「今日下单数已经上限」 | 描述计数状态，不是"异常/风险/验证" |
| 4 | **只卡 create-order，其它能力全正常** | 建地址、抽奖、领券、查询全部成功（风控通常会连坐）|
| 5 | 账号无异常标记 | `query-my-account` 正常，积分账户无 frozen/risk |

**对照表**：

| 接口 | 结果 |
|---|---|
| `create-order` | ❌ 600039 |
| `mall-create-order` | ✅ 走到参数校验（400 缺参数，非 600039）|
| `delivery-create-address` | ✅ 成功，能新建地址 |
| `draw-lottery` | ✅ 成功 |
| 各类 query-* | ✅ 成功 |

**直接证据**：今天 5 笔订单全部创建成功，第 6 笔起开始报 600039 —— 典型**计数器触发**，
而非风控的"频次异常"。

**结论**：不需要申诉、不需要解封，等次日自然重置。

### 这是账号级全局限制，不是门店级

实测：同一天内尝试 3 家门店 × 2 种渠道，全部返回 600039：

| 门店 | 渠道 | 结果 |
|---|---|---|
| 1450056 | 外送（orderType=2）| ❌ 600039 |
| 1450556 | 外送 | ❌ 600039 |
| 1450441 | 外送 | ❌ 600039 |
| 1450056 | 到店自取（orderType=1）| ❌ 600039 |

**换店、换渠道都无效**，只能等次日额度重置。

### ⚠️ 计数规则：按「创建数」算，取消不释放

实测：今天创建 5 笔订单（12:22 用户自己点的 1 笔 + 14:53/14:59/15:00
检验时创建的 3 笔 + 另一笔），**全部已取消，但额度仍被占满**。

**结论**：`600039` 按订单**创建**次数计数，**取消不返还额度**。

→ **做接口检验时要注意**：每跑一次 `create-order` 就消耗一次额度，
   哪怕立刻取消也一样。测试脚本要尽量少下单，
   并且优先用 `calculate-price` 验证参数（它不消耗额度）。

### 恢复时机

- 次日额度重置后可继续下单
- 账号历史里已取消的订单**不能再次取消**（返回 `600064`）
- 判断能否下单的唯一可靠方法：直接调 `create-order`，看是否 600039

### 测试脚本的正确姿势

```python
r = call("create-order", payload)
if r.get("code") == 600039:
    print("[SKIP] 今日下单数已达上限，跳过下单链路用例")
    return          # 优雅跳过，不要当失败
```


## ⚠️ 支付能力全解析（2026-10-24 深挖 bundle 实测）

### MCP 没有支付工具

35 个工具里**支付相关工具数为 0**（无 pay / wechat / wx / mini / alipay / charge / settle）。
支付完全依赖 `create-order` 返回的两个字段：

| 字段 | 值 | 用途 |
|---|---|---|
| `payH5Url` | `https://m.mcd.cn/mcp/scanToPay?orderId=xxx` | 手机端 H5 收银台 |
| `payId` | `111034096226823303168` | 纯 ID，**无跳转能力** |

### 支付链路全貌（实测每一环）

```
create-order
  └─ payH5Url: m.mcd.cn/mcp/scanToPay?orderId=xxx
       └─ H5 页面（React SPA，标题「麦当劳点餐」）
            └─ 渲染 1 张二维码（1131×1203 PNG）
                 └─ 二维码内容（OpenCV 解码得到）：
                    https://m.mcd.cn/mcp/jumpToApp?orderId=xxx
                      └─ 301 → /mcp/jumpToApp/?orderId=xxx
                           └─ 「麦当劳MCP」页（React）
                                └─ 目标 scheme：
                                   mcdapp://page?iosPageName=MCDOrderDetailViewController
                                   &androidPageName=ComponentOrder
                                   &parameters={"orderId":"xxx","openCashierDesk":"1"}
                                   └─ 唤起麦当劳 APP → 收银台
```

**最终落点是麦当劳 APP 的收银台**（`openCashierDesk: 1`），不是小程序。

### ⚠️ 小程序支付：此链路不支持

扒 `Index.d81d351c.8e27521e.chunk.js`（614KB）逐关键词统计：

| 关键词 | 出现次数 | 含义 |
|---|---|---|
| `launchMiniProgram` | **0** | 没有打开小程序的调用 |
| `miniprogram` | **0** | 没有小程序相关代码 |
| `applet` | **0** | 同上 |
| `weixin://` | **0** | 没有小程序 scheme |
| `chooseWXPay` | 0 | 没走 JSAPI 支付 |
| `wx-open-launch-app` | 1 | **开放标签：微信内直接唤起 APP** |
| `weappMiniContext` | 1 | 仅用于**检测**是否在小程序环境，不做跳转 |
| `mcdapp://` | 1 | 唤起麦当劳 APP 的 scheme |

**结论**：这条支付链路**没有小程序入口**。`weappMiniContext` 只是环境探测。

### 微信内的实际行为

H5 页仅在 **UA 含 micromessenger/wechat** 时注入 `jweixin-1.6.0.js`，
并配置 `openTagList: ["wx-open-launch-app"]`，`appid = wx6d8030a2f43b09a2`。

- **在微信里打开** → 页面显示「打开麦当劳APP支付」按钮，
  点了直接唤起 APP（比扫码更快）
- **在微信外打开** → 只能显示二维码，让用户用微信/APP 扫

### 实践建议

| 场景 | 最佳做法 |
|---|---|
| 用户在电脑前 | 抓二维码图片交付，用户用手机微信扫（当前做法）|
| 用户在手机上 | 直接给 `payH5Url`，用户在**微信里打开**可一键唤起 APP |
| 想在微信内直接付 | **此链路做不到**，只能跳 APP |

**不要臆造小程序支付路径** —— 接口层没有支付工具，页面层没有小程序入口。
