# mcd-ordering Skill

一句话点麦当劳。用户说"3个人，不吃辣，预算150"，自动完成
**定位门店 → 领券 → 搭配 → 用券 → 校验 → 算价 → 下单 → 交付支付**。

---

## 快速开始

### 1. 前置条件

- **MCP 服务**：mcd-mcp 已配置在 `~/.workbuddy/mcp.json`
  （URL `https://mcp.mcd.cn`，Bearer token 在 `headers.Authorization`）
- **Python 3.10+**
- **可选依赖**：
  - `opencv-python` — 二维码解码（`fetch_qr.py` 用，缺了会跳过解码）
  - `Pillow` — 确认单渲染（`order_receipt.py` 必需）
  - `playwright` — 支付页渲染（`fetch_qr.py` 必需）
    - 浏览器：`npx playwright install chromium`

```bash
pip install pillow opencv-python
```

### 2. 安装位置

用户级（全局可用，**推荐**）：

```
~/.workbuddy/skills/mcd-ordering/
```

项目级（仅当前项目生效）：

```
<项目>/.workbuddy/skills/mcd-ordering/
```

### 3. 验证

```bash
cd ~/.workbuddy/skills/mcd-ordering

# 直连是否通
python scripts/mcd_call.py available-coupons '{}'

# 各子命令是否正常
python scripts/menu_helper.py --help
python scripts/locate_store.py --city 上海市 --keyword 人民广场
python scripts/scenario_guard.py --help
```

### 4. 使用

重启会话后直接说人话：

```
4个人吃，不吃辣，其中1人吃素，预算200
```

或：`帮我点个餐，一个人` / `来份巨无霸套餐，算下多少钱` / `点份晚餐`

游戏：说「玩一下」开启 McDCraft 体素跑酷。

---

## 目录结构

```
mcd-ordering/
├── SKILL.md                    触发判定 + 9 步主流程 + 四条铁律
├── scripts/
│   ├── mcd_call.py             MCP 直连封装（唯一网络出口）
│   ├── menu_helper.py          搭配引擎：candidates/coupons/check/nutrition
│   ├── locate_store.py         定位选店（地名/坐标/浏览器定位 + 外送 beCode）
│   ├── scenario_guard.py       场景参数校验器（算价前必跑）
│   ├── fetch_qr.py             支付页二维码抓取 + 解码
│   └── order_receipt.py        订单确认单渲染
├── references/
│   ├── mcp-api.md              35 工具速查 + 传参矩阵 + 错误码 + 支付链路
│   └── dietary.md              忌口映射 + 素食兜底 + 套餐 round 规则 + 话术
└── assets/
    └── mcdcraft.html           麦当劳×我的世界风小游戏（单文件零依赖）
```

---

## 六个脚本的分工

| 脚本 | 干什么 | 什么时候用 |
|---|---|---|
| `mcd_call.py` | MCP 唯一出口 | 所有接口调用 |
| `menu_helper.py` | 候选筛选/忌口检查/券择优/营养查询 | Step 3–5 |
| `locate_store.py` | 定位选店 + 外送 beCode | Step 1 |
| `scenario_guard.py` | 场景参数 + 商品编码校验 | Step 6（算价前必跑）|
| `fetch_qr.py` | 支付二维码 PNG | Step 9 |
| `order_receipt.py` | 订单确认单 PNG | Step 9（必做）|

**为什么必须有 `scenario_guard.py`**：麦当劳服务端会**静默忽略多余参数**，
而且到店/外送是两套商品编码体系 —— 这些错误靠接口报错兜不住，只能提前拦。

---

## 四条铁律（写死在 SKILL.md 里）

1. **所有 MCP 调用走脚本**，不用平台工具层（整型参数会被降级成字符串）
2. **中文参数必须 `\uXXXX` 转义**（服务端按 GBK 解码，会存成乱码）
3. **菜单按场景分别拉取**，绝不能跨场景复用商品编码
4. **算价后停下等确认**，不自动创建订单

---

## 已知边界（如实告知用户，不要静默降级）

| 边界 | 说明 |
|---|---|
| 无素食主餐 | 唯一带"素"的是大米风味麦旋风（甜品）。唯一含素食小食的正餐套餐是「"堡"你欢乐套餐」（含苹果片）|
| 无法去辣 | 特调只支持冰量/酱料/燕麦奶 |
| 无法标注过敏原 | 系统层面做不到，要提醒用户与门店确认 |
| 券按周批次滚动 | 每批覆盖周一~周五，周末领的券要等下周一 |
| 今日下单数上限 | 账号级全局日限（600039），跨店跨渠道，取消不释放 |
| 小程序支付不可用 | 支付链路只到"跳麦当劳APP收银台"，无小程序入口 |
| 企业团餐需企业账号 | 普通账号拿不到 `gmServiceCode` |
| 门店经纬度恒为 0 | 靠 `distance` 排序 |

---

## 测试

项目目录 `tests/` 下有配套测试：

```bash
python tests/api_regression.py              # 接口回归，55 项断言，不消耗下单额度
python tests/api_regression.py --with-order # 真实下单后立即取消（消耗额度！）
python tests/api_regression.py --offline    # 只跑静态校验
node tests/game.test.js                     # 游戏功能回归
node tests/reachability.test.js             # 关卡可达性物理模拟
```

> ⚠️ `600039` 是账号级日限，**检验时每跑一次 `create-order` 就消耗一次额度**，
> 取消也不释放。所以测试默认不下单，参数验证一律用 `calculate-price`。

---

## 双落点约定

skill 目录是**权威副本**，项目目录是镜像：

```
~/.workbuddy/skills/mcd-ordering/scripts/   ← 权威
<项目>/scripts/                              ← 镜像
```

改动后两边同步。`tests/api_regression.py` 里有自动一致性检查。
**skill 改动需重启会话才生效。**
