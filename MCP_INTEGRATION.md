# MCP_INTEGRATION

本文说明 mcd-ordering Skill 实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

---

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 协议 | Streamable HTTP (JSON-RPC 2.0) |
| 地址 | `https://mcp.mcd.cn` |
| 鉴权 | `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| Token 获取 | https://open.mcd.cn/mcp 手机号登录后在控制台「激活」领取 |
| 配置示例 | 见仓库根目录 `mcp-config.example.json` |

**注意**：该服务**无需 session id**，`initialize` 后可直接调用 `tools/call`。
Token 只存放于本机 `~/.workbuddy/mcp.json`，**仓库内不含任何真实凭证**。

---

## 2. 实际使用的 Tool（20 个 / 全部 35 个中的 20 个）

### 2.1 查询类

| Tool | 用途 | 在流程中的位置 |
|---|---|---|
| `now-time-info` | 获取服务器时间 | 判断券是否已到使用时间 |
| `query-my-account` | 账号信息与积分 | 辅助确认账号状态 |
| `query-nearby-stores` | 按地名查附近门店（到店场景）| Step 1 定位门店 |
| `delivery-query-addresses` | 查询配送地址列表 | Step 1 外送场景 |
| `delivery-create-address` | 新建配送地址 | Step 1 外送场景 |
| `delivery-query-stores` | 查可配送门店（**beCode 的唯一权威来源**）| Step 1 / Step 3 |
| `query-meals` | 拉取门店在售菜单 | Step 3 拉菜单 |
| `query-meal-detail` | 拉取套餐 round 结构 | Step 3 取子商品编码 |
| `query-my-coupons` | 查询卡包优惠券 | Step 2 券状态判定 |
| `available-coupons` | 查询可领取优惠券 | Step 2 区分「已领取」与「可领取」 |
| `query-store-coupons` | 查询**该门店可用**优惠券 | Step 2 判断券能否用 |
| `query-order` | 查询订单详情 | Step 9 支付后查状态 |
| `order-list` | 历史订单列表 | 排查订单状态 |
| `list-nutrition-foods` | 营养成分数据 | 控热量场景 |
| `campaign-calendar` | 活动日历 | 活动查询 |
| `query-promotions` | 促销信息 | 活动查询 |

### 2.2 写入类

| Tool | 用途 | 在流程中的位置 |
|---|---|---|
| `auto-bind-coupons` | 一键领取优惠券 | Step 2 领券 |
| `calculate-price` | 计算价格 | Step 7 算价（**不消耗下单额度**）|
| `create-order` | 创建订单 | Step 9 下单 |
| `cancel-order` | 取消订单 | 异常处理 |

---

## 3. 调用流程

```
用户一句话
  │
  ├─ Step 0  解析意图（本地，无 MCP 调用）
  │    抽取 人数 / 忌口 / 预算 / 场景
  │
  ├─ Step 1  定位门店 + 让用户选
  │    query-nearby-stores {beType:1, searchType:2, city, keyword}
  │    delivery-query-stores {addressId, beType:2}   ← 取 beCode 原值
  │    delivery-create-address {…}                    ← 地址不存在时
  │
  ├─ Step 2  领券与券状态
  │    auto-bind-coupons {}
  │    query-my-coupons {}
  │    query-store-coupons {storeCode, orderType, beType, beCode}
  │    available-coupons {}                            ← 区分已领取/可领取
  │
  ├─ Step 3  拉菜单 + 判定人数
  │    query-meals {storeCode, orderType, beType, beCode?}   ← 按场景分别拉
  │    query-meal-detail {… , code}                        ← 取 round 与 choice.code
  │
  ├─ Step 4  搭配 + 忌口检查
  │    menu_helper.py check（本地规则引擎）
  │
  ├─ Step 5  优惠券择优
  │    menu_helper.py coupons（净省 = 抵扣额 − 加购成本）
  │
  ├─ Step 6  场景校验
  │    scenario_guard.py（本地校验器，拦截 600042/600048/60002/60006/600043）
  │
  ├─ Step 7  算价
  │    calculate-price {storeCode, orderType, beType, beCode, needTableware, items}
  │
  ├─ Step 8  出方案，停下等用户确认
  │
  └─ Step 9  下单 + 双交付
       create-order {… , addressId, remark, items}
       query-order {orderId}                ← 生成确认单
       fetch_qr.py                          ← 渲染支付页抓二维码
```

---

## 4. 业务价值

### 4.1 解决的问题

| 用户痛点 | 本 Skill 的解法 |
|---|---|
| **多人点餐不知道各点什么** | 按 round 里的**饮料数量**判定套餐真实供餐人数，自动拆成"大套餐 + 小套餐"组合 |
| **忌口说不清也吃不到** | 解析"不吃辣/吃素/过敏"并逐项核验；**菜单无法满足时明确告知**（如麦当劳无素食主餐），不静默替换 |
| **优惠券找不到、不会用** | 自动领券 → 判定券状态 → 按**净省最大**择优，一次只用一张（接口硬限制） |
| **下单参数繁琐易错** | `scenario_guard.py` 提前拦截 5 类静默错误（服务端会静默忽略多余参数）|
| **付款页看不到买了什么** | 生成**订单确认单 PNG**（逐项商品 + 费用拆解），与二维码一并交付 |

### 4.2 关键设计决策（均由实测得出）

| 决策 | 依据 |
|---|---|
| 菜单**按场景分别拉取** | 到店与外送是两套 productCode 体系（巨无霸：到店 `1100` / 外送 `901100`），跨场景复用会报 `60006`，形似"售罄"实为"不在该菜单" |
| `beCode` **必须用接口原值** | `query-nearby-stores` 的 beCode 恒为 null；自行拼接 `storeCode+后缀` 报 `60002` |
| `takeWayCode` **每店不同** | 1450056 是 `take-in-store`，1450556 是 `locker-out`；跨店复用报 `600043` |
| 请求体 **`ensure_ascii=True`** | 服务端按 GBK 解码请求体，中文直发会存成乱码；转成 `\uXXXX` 纯 ASCII 可规避 |
| 走脚本而非平台工具层 | 工具层会把整型参数降级成字符串，`beType`/`orderType` 等全部校验失败 |
| 券状态分五态判定 | 券**按周批次滚动**（每批覆盖周一至周五），周末领的券要到下周一才生效，非"几天就过期" |

### 4.3 能力边界（如实告知用户）

- 菜单**没有素食主餐**（唯一含"素"的是大米风味麦旋风，属甜品）
- 特调**无"去辣"选项**，无法标注过敏原
- **无小程序支付**（支付链路只到"跳麦当劳 APP 收银台"）
- 企业团餐需企业账号（普通账号取不到 `gmServiceCode`）
- 账号级**每日下单数上限**（跨店跨渠道共享，取消不释放额度）

---

## 5. 复现方式

```bash
# 1) 申请 MCP Token 并配置（见 mcp-config.example.json）
# 2) 安装依赖
pip install pillow opencv-python
npx playwright install chromium

# 3) 验证接口连通
python scripts/mcd_call.py available-coupons '{}'

# 4) 跑回归测试（不消耗下单额度）
python tests/api_regression.py
```

---

## 6. 使用的第三方资源

| 资源 | 用途 | 许可 |
|---|---|---|
| 麦当劳 MCP Server | 全部业务数据来源 | 见 [MCPServerRules](https://cdn.mcd.cn/cms/pages/MCPServerRules.html) |
| Nominatim (OpenStreetMap) | 坐标 → 地名逆地理编码（`locate_store.py`）| ODbL |
| OpenCV | 支付二维码解码（`fetch_qr.py`）| Apache-2.0 |
| Pillow | 订单确认单渲染（`order_receipt.py`）| MIT-CMU |
| Playwright | 支付页渲染（`fetch_qr.py`）| Apache-2.0 |

本项目未使用任何 AI 模型推理服务，全部能力由 MCP 接口 + 确定性规则引擎实现。
