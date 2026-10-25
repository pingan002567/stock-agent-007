# 安卓端同步任务（2026-10-25 起）

安卓客户端 `mobile-rn/` 最后一次提交是 **10-17**（`eab1aa0`），之后一周 92 个提交
没有同步。本文是逐项核对后的任务清单，按「先修正确性、再补功能、最后对齐形态」排序。

## 兼容性前提（已核实）

老 APK **不会崩**：本周改动全部是增量字段 + SSE 事件类型未变；
历史里新增的 `reasoning` 消息会被 `messagesToTurns` 自动 fold 进当前轮
（`mobile-rn/src/store/chat.ts:603`），不需要防御性改动。

## 已核实的接口现状（线上实测）

| 接口 | 本周变化 | 安卓能否直接用 |
|---|---|---|
| `/api/stocks/search?q=BTC` | 返回 `market:CRYPTO`、`instrument_type:crypto` | ✅ 能搜到、能加自选 |
| `/api/stocks/BTC/context` `/history` | 200，`market:CRYPTO` | ✅ 能打开详情 |
| `/api/stocks/BTC/financial` | `degraded:true`、`source:unavailable` | ⚠️ 渲染要兜住 |
| `/api/holdings` | item 增 `currency`/`market_value_native`；summary 增 `by_currency`/`weights` | ⚠️ 只读没问题，展示缺币种 |
| `POST /api/holdings` | **本周新增**（`HoldingUpsert.currency` 可选） | ❌ 安卓没有入口 |
| `GET /api/fx/rates` | **本周新增** | 未使用（可选） |
| `/api/settings.tools[].label` | **本次新增**（后端下发中文名） | 待接 |
| `PUT /api/settings/runtime` | 思考开关走这里 | ❌ 安卓没有开关 |

---

## T1 · 工具/技能名单一真源（基建）

**问题**：工具中文名三处各存一份，必然漂移。实测 75 个工具：
安卓缺 27 个（36%）、Web 缺 24 个（36%），聊天里直接显示 `get_crypto_derivatives`。

**改动**
- [x] 后端新增 `backend/config/tool_labels.py`（89 条，单一真源）
- [x] `ToolSpec.to_dict()` 与 `DEFAULT_TOOLS` 兜底路径都带 `label`
- [x] Web `toolLabel()` 优先用 `/api/settings.tools[].label`，静态表降级为 fallback
- [x] 安卓 `src/lib/toolLabels.ts` 同上；连接就绪后 prime

**验收**：聊天工具卡、设置页工具列表全部中文；新加工具只改后端一行。

## T2 · 思考开关（模型与智能）

**问题**：Web 有「思考模式」开关（`PUT /api/settings/runtime {thinking_enabled}`），
安卓没有 —— 手机用户关不掉思考（费钱、慢）。

**改动**
- [x] `ModelServiceScreen` 增加开关，调 `PUT /api/settings/runtime`
- [x] 与 `runtime_config.thinking_enabled` 双向同步

**验收**：手机上关掉后，下一轮对话不再返回 `reasoning`；刷新后开关状态保持。

## T3 · 多币种持仓显示

**问题**：`HoldingsScreen.tsx:178` 全程硬编码 `¥`，没有币种、没有分币种小计。
后端 `summary.by_currency` 已经给了。

**改动**
- [x] 每行显示 `currency`（USD 用 `$`、CNY 用 `¥`）
- [x] 顶部增加分币种小计（对齐 Web `Holdings.tsx:325-333`）
- [x] `market: "CRYPTO"` 中文化为「加密」

**验收**：BTC + A 股混合持仓时，行币种正确、小计正确、总资产仍为折合 CNY。

## T4 · 加加密持仓入口

**问题**：`POST /api/holdings` 本周新增，安卓无入口 → 手机上无法把买的币记进持仓。

**改动**
- [x] 持仓页「添加」按钮 → 搜索标的 → 数量/成本/币种
- [x] 加密标默认 `currency` = 计价币（USDT/USD），股票默认 CNY

**验收**：手机加一笔 BTC，Web 端持仓立即可见且折合正确。

## T5 · 风控上限编辑（含加密上限）

**问题**：安卓只能改 `risk_level` / `notes`，改不了单票/行业/加密上限；
加密上限（`crypto_max_weight_pct`，默认 30%）有了币之后最需要能调。

**改动**
- [x] 画像页增加上限编辑（单票 / 行业 / ETF / 加密）
- [x] 写回 `PUT /api/risk-policies/{id}`（已验证幂等回写）

**验收**：手机把加密上限从 30% 调到 20%，Web 风控页同步显示 20%。

## T6 · 数据与情报合并

**问题**：Web 本周把「数据源 + 情报」合成一页；安卓只有行情源，
没有任何新闻/舆情 provider 的设置入口。

**改动**
- [x] `DataSourcesScreen` 增加情报区（新闻搜索 / 舆情 provider + Key）

**验收**：手机上能看到并启用/停用情报源。

## T7 · 盯盘加密规则

**问题**：本周新增 `crypto_funding_rate_gt`，安卓只能建 `price_change_pct_gt`，
其它类型直接显示原始英文 `rule_type`。

**改动**
- [x] 规则类型下拉增加「资金费率超限」
- [x] 规则列表把 `rule_type` 中文化（含已有的 `price_above` 等）

**验收**：手机上能建一条资金费率规则，Web 盯盘页能看到同一条。

## T8 · 设置首页「概览」

**问题**：Web 有了概览（待确认 / 当前生效 / 健康度），安卓设置是一堆平铺入口。

**改动**
- [x] `SettingsScreen` 顶部加「配置概览」组（模型连通 / 数据源 / 定时任务 / 护栏）
- [x] 待确认项点进去直达对应屏

**验收**：打开设置 3 秒内知道「哪里没配好」。

---

## 顺序与依赖

```
T1（基建）→ T2, T3（互不依赖，可并行）→ T4 → T5 → T6 → T7 → T8
```

T1 先做：T3/T4/T7 的文案与展示都依赖标签真源。

## 追加任务（来自「思考链」分析，尚未开始）

### T9 · 思考状态倒退（P0）✅ 已完成（`e8cc040`）
真实 SSE 顺序是 `tool_call` → `reasoning` → `tool_result`（思维链挂在带
tool_calls 的分片上，晚一拍到），而 `applyStreamUpdate` 的 reasoning 分支
**无条件** `state.phase = 'reasoning'` → 气泡状态从「调用工具…」倒回「思考中…」。
修法：reasoning 到达时若 phase 已是 tools/answering 不回退。

### T10 · 思考与工具交错（P1）✅ 已完成（本次）
安卓把思考塞在独立 tab、工具放另一 tab，看不出「为什么调这个工具」；
Web 是 `steps[]` 有序交错。要在安卓对齐需给 `AssistantState` 增加 `steps: Step[]`。

## 不做

- 设置页 IA 照搬 Web（安卓是独立导航，硬套只会更乱）
- agent loop 的折叠/命令终端（T2 相关的「思考」形态单独评估）
- 桌宠（Tauri 窗口独有）

---

## 追加完成（T9/T10）

| 任务 | 提交 | 验证 |
|---|---|---|
| T9 状态不倒退 | `e8cc040` | reasoning 分支避开 tools/answering/final；加测试守住 |
| T10 steps 交错 | 本次 | AssistantState.steps；气泡与详情页「过程」tab；历史回放自动重建 |

## 本次已完成（2026-10-25）

| 任务 | 提交 | 验证 |
|---|---|---|
| T1 标签单一真源 | `7487012` | 后端 89 条 label + 覆盖测试；Web/安卓都消费 |
| T2 思考开关 | `be4db1f` | 接 `PUT /api/settings/runtime`（整体覆盖，先合并） |
| T3 多币种持仓 | `fe56d44` | 原币 + 折合 + 分币种小计 |
| T4 加持仓入口 | `2b1f999` | `POST /api/holdings`，搜索支持 BTC |
| T5 风控上限 | `8ab3aab` | 线上幂等回写验证 body 形状 |
| T6 情报设置 | `0fbe596` | 线上幂等回写验证 body 形状 |
| T7 加密盯盘规则 | `2208236` | 线上建了 `crypto_funding_rate_gt` 规则再删除 |
| T8 设置概览 | 本次 | 健康度 + 待确认，且「拉不到显示 —」 |

验证方式统一为：`mobile-rn && npm run typecheck`（`tsc --noEmit`）+ 后端接口真跑。
**APK 已打包**（2026-10-25）：`mobile-rn/StockAgent-0.2.0-arm64.apk`（36.6 MB，
versionCode 2 / versionName 0.2.0，只含 arm64-v8a，JS 已内联，可独立安装）。

打包过程中踩到并已修掉的两个环境问题：

1. **Gradle 访问 plugins.gradle.org 失败**（curl 能通、Gradle HEAD 不通）→
   在 `mobile-rn/android/settings.gradle` 的 pluginManagement 前置阿里云镜像；
   RN 的 included build（`@react-native/gradle-plugin/settings.gradle.kts`）
   也硬编码了 gradlePluginPortal，用 `scripts/patch-gradle-mirror.mjs` 打补丁，
   并挂到 `npm run postinstall` 上（`npm install` 后自动重放）。
2. 签名沿用 RN 模板的 **debug keystore**（release 也用它）。要发正式包需替换
   `signingConfigs`，否则同包名同签名只能做内测分发。

复现命令（**只保留最新产物**，旧版本自动删除）：

```bash
cd mobile-rn
npm run package:android
# 产物：StockAgent-<versionName>-arm64.apk（目录里始终只有这一份）
```

脚本 `mobile-rn/scripts/package-android.mjs` 会读 `android/app/build.gradle`
里的 versionName 命名产物，并在复制前删掉所有旧的 `StockAgent-*.apk`。
