# 麦麦 mcd-ordering · 麦当劳骰子点餐 Skill

> 说出人数、忌口和预算，**掷三颗骰子**决定今天吃什么 —— 自动完成
> 定位门店 → 领券 → 选餐 → 用券 → 校验 → 算价 → 下单 → 付款。

[![参赛作品](https://img.shields.io/badge/麦当劳程序员节-参赛作品-DA291C)](https://github.com/M-China/mcd-developer-innovation-challenge/issues/1358)
[![报名 Issue](https://img.shields.io/badge/报名_Issue-%231358-181717)](https://github.com/M-China/mcd-developer-innovation-challenge/issues/1358)
[![Star](https://img.shields.io/github/stars/williamyi-666/mcd-ordering?style=social)](https://github.com/williamyi-666/mcd-ordering/stargazers)

基于麦当劳 MCP（Model Context Protocol）能力开发的创意 Skill，
面向中国大陆地区开发者参加 **麦当劳程序员节创意开发大赛**。

> ⚠️ 本项目为**非麦当劳官方产品**，仅为参赛作品。所有订单与支付均由用户本人确认。

---

## 一、项目介绍

### 1.1 解决什么问题

日常点麦当劳的三个真实痛点：

| 痛点 | 具体表现 | 本项目的解法 |
|---|---|---|
| **多人点餐不知道各点什么** | 套餐名写着"双人餐"其实是 2 种汉堡；不知道几人份该点几个套餐 | 按 round 里的**饮料数量**判定真实供餐人数，自动拆成「大套餐 + 小套餐」组合 |
| **忌口说不清也吃不到** | 说了"不吃辣"，端上来才发现酱料是辣的；系统悄悄换成别的 | 逐项核验忌口；**菜单无法满足时明确告知**（如麦当劳无素食主餐），绝不静默替换 |
| **优惠券找不到也不会用** | 领了券不知道能不能用、该不该用 | 自动领券 → 判定券状态 → 按**净省最大**择优（不是看面值）|

### 1.2 核心能力

| 能力 | 说明 |
|---|---|
| **人数解析** | 一句话里抽人数，按真实供餐人数匹配套餐档位，凑不齐自动组合 |
| **忌口核验** | 不吃辣 / 吃素 / 过敏 / 不要香菜 / 无糖 / 控热量，**满足不了会明说** |
| **搭配方案** | 套餐每个 round 都能按忌口和预算替换，差价实时计算 |
| **优惠券择优** | 自动领券、门店可用性判定、净省算法择优、即将过期提醒 |
| **场景校验** | 提前拦截 5 类"服务端不报错但结果错"的隐性坑 |
| **骰子选餐** | **默认选餐方式**。三颗骰子掷出 216 种组合之一，按 216 级强度阶梯落到候选池对应价位 |
| **连投** | 多人各点各的：预算均摊 N 份，每份独立掷一次骰，合计必然在预算档内 |
| **免费重投** | 掷出豹子/顺子（13.9%）送一次重投，默认保留更便宜的那份 |
| **投前确认** | 人数/预算/忌口/渠道/门店五项硬校验，缺项**不投掷**；有默认值则只问两项 |
| **付款闭环** | 门禁 9 项核对 → 按场景出支付入口（二维码 / H5）→ 轮询支付结果 → 付成功才出确认单 |
| **控热量** | 160 项营养数据，可按 kcal 筛单品 |
| **附赠小游戏** | McDCraft 体素跑酷，单文件零依赖 |

### 1.3 目标用户

| 用户 | 典型诉求 |
|---|---|
| **上班族 / 学生** | 一个人或两人快速下单，不想纠结搭配，要求不踩忌口 |
| **家庭 / 聚餐组织者** | 3~6 人点餐，要控制总价、要照顾不同忌口 |
| **减脂健身人群** | 要低卡搭配、不吃辣、不想要高糖酱料 |
| **麦当劳重度用户** | 熟悉会员活动与优惠券，想知道当前哪家店能省最多 |

---

## 二、安装方法

### 2.1 前置条件

- **腾讯 WorkBuddy**（官方合作伙伴，推荐）
- **麦当劳 MCP Token**：访问 https://open.mcd.cn/mcp ，手机号登录后在控制台点「激活」领取
- **Python 3.10+**

### 2.2 配置 MCP 连接器

在 WorkBuddy 左侧边栏【专家·技能·连接器】→【自定义连接器】→【配置 MCP】，填入：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

> ⚠️ 记得把 `YOUR_MCP_TOKEN` 替换成真实 Token，并点【保存】。
> 保存后回到【自定义连接器】把 `mcd-mcp` **启用**。

仓库根目录的 `mcp-config.example.json` 是同一份配置的脱敏示例，
**只含环境变量占位符**，不含任何真实凭证。

### 2.3 安装 Skill

本仓库根目录就是一个标准 Skill 结构，一条命令装好。

**Windows（PowerShell，在仓库根目录执行）**

```powershell
.\install.ps1 -Copy        # 复制（推荐，无需开发者模式）
.\install.ps1              # 软链（改动实时同步，需开发者模式）
.\install.ps1 -Uninstall   # 卸载
```

**macOS / Linux / Git Bash**

```bash
./install.sh --copy
./install.sh
./install.sh --uninstall
```

装到 `~/.workbuddy/skills/mcd-ordering/`，包含：

```
SKILL.md              技能入口（模型读这个）
scripts/              10 个可执行脚本
references/           MCP 接口表、忌口规则、骰子方案
assets/               骰子动画页、小游戏
config/               默认值（门店/渠道/忌口）
```

> 安装脚本**不做递归删除**。覆盖或卸载时把原目录移到
> `~/.workbuddy/skills/.trash/mcd-ordering-<时间戳>`，可随时找回。

### 2.4 安装可选依赖

```bash
pip install pillow opencv-python     # 订单确认单渲染 + 二维码解码
npx playwright install chromium       # 支付页渲染（抓二维码用）
```

只做「查询 / 算价」不需要这些；**下单交付环节**需要。

### 2.5 验证安装

```bash
cd ~/.workbuddy/skills/mcd-ordering

# 接口是否通
python scripts/mcd_call.py available-coupons '{}'

# 各子命令是否正常
python scripts/menu_helper.py --help
python scripts/pay.py --help
python scripts/locate_store.py --city 上海市 --keyword 人民广场
python scripts/scenario_guard.py --help

# 离线自检（不联网、不消耗下单额度）
python scripts/dice_roll.test.py --offline   # 骰子引擎 93 项
python tests/pay.test.py                     # 付款闭环 20 项
```

> ⚠️ **改动 Skill 后需重启会话**才生效。

---

## 三、使用示例

### 3.1 一句话点餐

```
4个人吃，不吃辣，其中1人吃素，预算200
```

输出是一份带明细的方案：

```
【4 人份方案】麦当劳上海食品一店餐厅（南京东路720号）

商品                     数量   小计
──────────────────────────────
畅享吃鸡三人餐             1   86.0
"堡"你欢乐套餐            1   43.8
──────────────────────────────
商品小计                      129.8
配送费                         6.0
打包费                         5.6
应付                          141.4 元    人均 35.4

忌口：⚠️ 部分满足
  · 不吃辣 —— 已全部换成不辣款
  · 1人吃素 —— ⚠️ 麦当劳无素食主餐，该位安排
              「单人餐 + 泷愿成真麦旋风(大米风味)」
              属甜品类，主食无法满足，建议另行准备

优惠券：本次未使用（卡包券需等到 10-26 才能用）

⏸  已停下，等待你说「下单」
```

### 3.2 常用句式

| 你说 | 它会做 |
|---|---|
| `3个人不要辣预算150` | 抽人数=3、忌口=[不吃辣]、预算=150，给方案 |
| `一个人，不吃辣，50以内` | 沿用已记下的偏好，给单人方案 |
| `来份巨无霸套餐，算下多少钱` | 直接算价，不下单 |
| `换家店试试` | 只换门店，人数/忌口/预算沿用 |
| `下单` | 才真正创建订单，出支付二维码 + 确认单 |
| `支付完成` | 查订单状态与配送进度 |
| `玩一下` | 打开 McDCraft 小游戏 |

### 3.3 手动调用（调试用）

```bash
cd ~/.workbuddy/skills/mcd-ordering

# 拉菜单（注意：到店与外送是两套编码体系，必须按场景分别拉）
python scripts/mcd_call.py query-meals \
  '{"storeCode":"<STORE>","orderType":2,"beType":2,"beCode":"<BE_CODE>"}'

# 按人数挑候选套餐
python scripts/menu_helper.py candidates --menu menu.json --people 3

# 忌口检查
python scripts/menu_helper.py check --menu menu.json --plan plan.json --restriction 不吃辣

# 优惠券择优
python scripts/menu_helper.py coupons --menu menu.json --plan plan.json --coupons cards.json

# 场景校验（算价前必跑）
python scripts/scenario_guard.py --scenario delivery --order-type 2 --be-type 2 \
    --be-code <BE_CODE> --store-code <STORE> --menu menu.json --items plan.json
```

---

## 四、目录结构

```
mcd-ordering/
├── SKILL.md                      触发判定 + 9 步主流程 + 5 条铁律
├── README.md                     本文件
├── install.sh / install.ps1      一键安装为 WorkBuddy Skill（卸载只移不删）
├── CONTEST_DECLARATION.md        参赛声明（官方原文，零改动）
├── MCP_INTEGRATION.md            MCP Server / Tool / 调用流程 / 业务价值
├── mcp-config.example.json       脱敏 MCP 配置（仅环境变量占位符）
├── workbuddy.md                  WorkBuddy 开发全过程对话上下文
├── scripts/                      10 个脚本
│   ├── mcd_call.py               MCP 直连封装（唯一网络出口）
│   ├── menu_helper.py            搭配引擎（candidates/coupons/check/nutrition）
│   ├── locate_store.py           定位选店（地名/坐标/浏览器定位 + 外送 beCode）
│   ├── scenario_guard.py         场景参数校验器（算价前必跑）
│   ├── dice_roll.py              骰子选餐引擎（三骰 216 级 + 投前确认）
│   ├── serves_probe.py           权威供餐人数探测（饮料数）
│   ├── pay.py                    付款闭环（门禁 → 入口 → 等结果 → 确认单）
│   ├── pay_confirm.py            付款前门禁（9 项核对）
│   ├── fetch_qr.py               支付页二维码抓取 + 解码
│   ├── order_receipt.py          订单确认单渲染
│   └── demo/                     骰子动画页生成与校验
├── references/
│   ├── mcp-api.md                35 工具速查 + 传参矩阵 + 错误码 + 支付链路
│   ├── dietary.md                忌口映射 + 素食兜底 + 套餐 round 规则 + 话术
│   └── dice-design.md            三骰方案的数学推导与 60 万次模拟
├── assets/
│   ├── dice-demo.html            骰子动画页（全屏剧场 + 真实映射计算）
│   └── mcdcraft.html             McDCraft 小游戏（单文件零依赖）
├── config/
│   └── defaults.json             默认值（门店/渠道/忌口，本地生成不入库）
├── tests/
│   ├── dice_roll.test.py         骰子引擎回归（93 项断言）
│   ├── pay.test.py               付款闭环回归（26 项断言）
│   ├── api_regression.py         接口回归（55 项断言）
│   ├── game.test.js              游戏功能回归
│   ├── reachability.test.js      关卡可达性物理模拟
│   └── exports.js                测试用内部符号导出
└── docs/
    ├── 开发文档.md                17 章技术文档
    ├── 骰子选餐方案.md            骰子方案完整设计与实测
    ├── 参赛清单.md                参赛申请模板与注意事项
    └── 参赛文案.md                报名原文 + 短/中/长版传播文案
```


---

## 五、跑测试

```bash
python tests/api_regression.py              # 接口回归，55 项断言，不消耗下单额度
python tests/api_regression.py --offline    # 只跑静态校验，不联网
python tests/api_regression.py --with-order # 真实下单后立即取消（消耗额度，慎用）

node tests/game.test.js                     # 游戏功能回归
node tests/reachability.test.js             # 关卡可达性物理模拟
```

> ⚠️ 麦当劳接口有**账号级每日下单数上限**（`600039`，跨店跨渠道共享，取消不释放）。
> 所以测试默认**不下单**，参数验证一律用 `calculate-price`（不消耗额度）。

---

## 六、两个必须知道的坑

**1. 不能用平台工具层调 MCP**

工具层会把 `beType` / `orderType` 这类整数降级成字符串，接口校验直接失败。
所有调用必须走 `scripts/mcd_call.py` 直连。

**2. 中文参数会被服务端按 GBK 解码**

直接发 UTF-8 字节，「无接触配送」会存成 `޽Ӵ�����`。
脚本已内置 `ensure_ascii=True` 转义，**若手写请求体务必同样处理**。

细节见 [`docs/开发文档.md`](docs/开发文档.md) 与 [`references/mcp-api.md`](references/mcp-api.md)。

---

## 七、已知能力边界（如实告知，不静默降级）

| 边界 | 说明 |
|---|---|
| 菜单**没有素食主餐** | 唯一带"素"的是大米风味麦旋风（甜品）。唯一含素食小食的正餐套餐是「"堡"你欢乐套餐」（含苹果片）|
| **无法去辣** | 特调只支持冰量 / 酱料 / 燕麦奶 |
| **无法标注过敏原** | 系统层面做不到，需提醒用户与门店确认 |
| 券**按周批次滚动** | 每批覆盖周一至周五 10:30–23:59，周末领的券要等下周一 |
| **每日下单数上限** | 账号级全局日限，换店换渠道均无效 |
| **无小程序支付** | 支付链路只到「跳麦当劳 APP 收银台」 |
| 企业团餐需企业账号 | 普通账号取不到 `gmServiceCode` |
| 门店经纬度恒为 0 | 按 `distance` 排序 |

---

## 八、小游戏

点完餐如果还有空档，说一句「玩一下」。

麦当劳 × 我的世界风，体素跑酷，收集可乐 / 汉堡 / 薯条，集齐 3 个能合成升级版，
躲开可恶的倒垃圾工。零依赖单文件，`localStorage` 存档，随时关随时续。

也可以直接双击 `assets/mcdcraft.html` 试玩。

---

## 九、相关文档

| 文档 | 内容 |
|---|---|
| [`MCP_INTEGRATION.md`](MCP_INTEGRATION.md) | 用了哪些 MCP Server / Tool、调用流程、业务价值 |
| [`docs/开发文档.md`](docs/开发文档.md) | 17 章技术文档（架构、实现、风险登记、调试记录）|
| [`references/mcp-api.md`](references/mcp-api.md) | 35 工具速查 + 传参矩阵 + 错误码 |
| [`references/dietary.md`](references/dietary.md) | 忌口映射 + 素食兜底 + 套餐规则 |
| [`workbuddy.md`](workbuddy.md) | WorkBuddy 开发全过程对话上下文 |

---

> 本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。
> 项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态
> 以麦当劳官方渠道的实时结果为准。
