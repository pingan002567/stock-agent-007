# Android 客户端技术选型

> 状态：按「技术成熟度」权重重新定稿；落地前请复核第 5.5 节版本号
> 日期：2026-10-16
> 范围：为 Stock Agent 工作台新增 **Android 客户端**
> 注：iOS 原生客户端（原 `mobile-native/`）已于 2026-10-23 整体移除，本文中涉及 iOS 的描述保留为当时的历史依据
> 依据：仓库源码实测 + 2026-10-16 外部调研（关键结论已标注来源，未核实项已显式标注）

---

## 1. 摘要与结论

**结论（按技术成熟度权重）：推荐 React Native + Expo（development build），原生 Kotlin + Compose 为并列备选。不用 Flutter、不复活 WebView、现阶段不做 KMP 统一。**

| 项 | 结论 |
| --- | --- |
| 客户端栈 | **Expo SDK 57（RN 0.86）+ React 19**（dev build / CNG，非 Expo Go） |
| 主要依据 | 技术成熟度 + 团队既有 React/TS 技能 + **直接复用 Web 端已存在的流式 Markdown/图表/分块逻辑** |
| 并列备选 | 原生 Kotlin 2.4.21 + Compose（平台运行时最成熟：okhttp-sse 一等公民、TLS 配置即文件） |
| 明确排除 | Flutter（SSE 无一等公民、markdown/chart 生态停更）、KMP 统一（需重写可用 iOS 应用）、WebView（已否决） |
| 推送 | 排除 FCM；优先**个推免费版**，按「订阅式提醒」设计交互 |
| 分发 | **自用/熟人分发的 APK + 应用内更新**；主流商店对股票类 App 实质关闭 |
| 工作量 | 对齐 iOS 功能面约 **36–55 人天**（RN 因复用 Web 逻辑，预计可再压缩） |
| 服务端前置工作 | 设备注册端点 + 推送服务（挂到既有 `CompositeAlertSink`）——**必做，且与客户端选型无关** |

**成熟度视角的三个理由**（详见第 5、6 节）：

1. **「原生形状」不是选型依据**：聚合推送 SDK 对 RN/Flutter/原生都有客户端，自签 TLS 三种栈也都能做——「能不能做」已被抹平，剩下的是「做得多成熟」。
2. **真正的生态成熟度差在 SSE 与 Markdown/图表**：原生 `okhttp-sse` 一等公民；RN 二线但可用；Flutter 无一等公民 SSE 且 markdown/chart 依赖停更 → 这是排除 Flutter 的实证依据。
3. **代码复用是最大的成熟度红利**：Web 端已有的 `splitStableBlocks` / `MarkdownRenderer` / `StockHistoryChart` 全是 TypeScript，RN 直接复用；原生/Flutter 要第三遍重写同一套易错逻辑（iOS 已用 Swift 重写了一遍）。

**与上一版的差异**：删除「原生形状」这一首要理由后，原生与 RN 得分接近；RN 赢在「技能契合 + 代码复用」，原生赢在「平台运行时成熟度」。最终综合取 RN，触发回原生的条件见 6.3。

**仍需正视的是分发（非技术问题）**：股票类 App 属受限品类，上架须核验证券资质而该牌照个人无法取得，小米等商店也不接受个人开发者。现实定位是**自用/熟人分发**。详见 8.1。

---

## 2. 背景与硬约束

### 2.1 既有事实（可在仓库中核对）

| 事实 | 证据 |
| --- | --- |
| WebView 方案已被**主动否决** | 原 `mobile/README.md` 仅一行指向 iOS 工程（该文件已随 iOS 客户端一并移除） |
| ~~已有原生 iOS 客户端（SwiftUI）~~ | 已于 2026-10-23 移除（原 `mobile-native/StockAgent/`） |
| 客户端不持有业务状态 | 会话真相在 DeerFlow checkpoint，SQLite 只做 UI 投影（`doc/STACK_DECISIONS.md`） |
| 鉴权是**静态共享密钥**，无账号体系 | `backend/access_auth.py:16-17`：REST 用 `X-Workbench-Token`（或 `Bearer`），SSE 可用 `?access_token=` |
| 后端常以**自签 HTTPS** 暴露 | Android 端需自行配置 trust（原 iOS 实现已随客户端移除） |
| ~~推送目前只有 APNs~~ | 已于 2026-10-23 随 iOS 客户端整体移除（`routes_devices.py`、`apns_push.py`、`apns_device` 表均已删除，当前**没有任何推送通道**） |
| 告警下发走 **IM 通道** | `backend/bootstrap.py`：`alert_sink = channel_notifier.push`；IM 通道含 Slack / Telegram / 企业微信（`backend/channels/`） |
| 后端已提供**服务端推送式监控流** | `backend/api/routes_monitor.py:99` → `MonitorService.stream_snapshot()`（状态变化即推，含心跳）；原 iOS 端未使用，走轮询（客户端已移除） |
| 团队规模 | 1 人维护 Python 后端 + React Web + Tauri 桌面 + SwiftUI iOS |

### 2.2 选型必须服从的约束

1. **不走回头路**：不再回到 WebView / Capacitor 套壳。移动端已确立「原生」路线。
2. **薄客户端**：客户端只做展示与交互，不在本地重做业务逻辑或持久化业务真相。
3. **无账号体系**：不引入 OAuth / 登录态，只做「地址 + 访问令牌」连接模型。
4. **必须容忍自签证书**：要能连自签 HTTPS，也要能连 `http://host:port`。
5. **面向中国大陆 A 股用户**：推送与分发受国内 Android 生态（无可靠 FCM、应用商店审核）约束。
6. **单人可维护**：技术栈的总维护面（依赖数、构建链、发布链）必须压得住。

---

## 3. 需求画像与工作量基线

iOS 客户端共 10,958 行 Swift，分布如下（实测）：

| 模块 | Swift 行数 | 说明 |
| --- | ---: | --- |
| Chat 对话 | 4,762 | 流式 SSE、思考时间线、工具卡片、Markdown、附件、会话分页 |
| Settings 设置 | 1,807 | LLM 服务、技能、费用、行情刷新、数据源凭证、通知偏好、主题 |
| Networking 网络层 | 2,595 | API 客户端、模型、SSE、鉴权存储、推送、主题、可达性 |
| Monitor 盯盘 | 660 | 启停、规则 CRUD、事件列表/详情、未读已读、反馈 |
| Watchlist 自选 | 483 | 搜索、增删、标的详情（走势/资讯/财报/研报） |
| Duty 定时任务 | 259 | 列表、启停、立即执行 |
| Strategy 策略 | 135 | 策略列表、回测 |
| Holdings 持仓 | 104 | 组合摘要、浮动盈亏 |
| Connect 连接 | 153 | 地址 + 令牌、健康探测 |
| App 壳 | ~195 | Tab 容器、可达性横幅 |

**结论**：这是一个「一个重对话页 + 一堆中等偏轻的设置/列表页」的客户端。真正的工程量集中在 Chat（流式渲染、Markdown、附件、分页、中断恢复）与 Settings（表单多、但逻辑浅）。这决定了选型的关键不是「哪个框架写列表快」，而是**长连接流式渲染 + 平台推送 + 自签 TLS 这三件事在目标栈上是否第一等公民**。

---

## 4. 客户端契约（Android 必须逐条对齐）

### 4.1 鉴权

- 所有 REST：请求头 `X-Workbench-Token: <token>`（也接受 `Authorization: Bearer <token>`）。
- 所有 SSE：额外允许 `?access_token=<token>`（`is_sse_path()` 白名单：`/api/copilot/**/stream/**`、`/api/monitor/stream`）。
- `/api/health` **免鉴权**，但返回体中 `agent_runtime` 字段是否存在用于判定令牌有效性（iOS 以此判定「令牌无效」）。
- 令牌错误 → `401 {"detail": "未授权：请填写访问令牌"}`。

### 4.2 SSE 流

| 流 | 端点 | 用途 |
| --- | --- | --- |
| 对话 | `GET /api/copilot/sessions/{session_id}/stream/{run_id}` | 逐 token 输出一次 agent run |
| 盯盘 | `GET /api/monitor/stream`（可选 `?once=true` 单次快照） | 监控状态变化推送（iOS 未用，走轮询） |
| 定时任务 | `GET /api/tasks/{task_id}/stream`（`backend/api/routes_tasks.py:49`） | 任务进度，终态为 `final` |

服务端行为（`backend/agent_runtime/stream_adapter.py`）：

- 连接建立即发 `: ok\n\n`（注释帧，避免空响应等待）。
- **每 15 秒**发命名心跳帧 `event: ping` 或 `event: progress`（`SSE_PING_INTERVAL_SECONDS = 15.0`）。这是为绕过 WebKit/CFNetwork 的 ~60s 空闲切断；**Android 端同样必须把空闲判定建立在「收到任意帧」之上**。
- 响应头含 `Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`。

### 4.3 事件类型与载荷（实测自 `ChatModels.swift:203-289`）

| `event.type` | 载荷字段 | 客户端行为 |
| --- | --- | --- |
| `reasoning` | `payload.text` | 追加到「思考」区（同段去重，不重复追加相同文本） |
| `tool_call` | `payload.tool` / `payload.name`、`payload.call_id` | 新增运行中工具卡片；**`write_todos` 被忽略** |
| `tool_result` | `payload.call_id`、结果预览 | 对应卡片置为完成；`call_id` 为空则丢弃 |
| `partial_answer` / `message` | `payload.text` / `payload.content` / `obj.text` | 追加到答案正文 |
| `final` | `payload.conclusion` / `text` / `content`；或 `payload.clarification` | 定稿；若带 `clarification` 则转为「追问卡片」态 |
| `clarification` | `question`、`request_id`、`options[]`、`input_mode` | 渲染人工输入卡片（选项 + 自由输入） |
| `skill_trace` | `payload.items[]` 或 `payload` 单条 | 技能执行轨迹 |
| `error` | `payload.message` / `payload.error` | 失败态；文案含「停止」时降级为软停止而非错误 |
| `title` | `payload.title` | 会话标题自动生成；**不持久化**，仅用于即时更新会话列表标题 |
| `ping` / `progress` | `status`、`phase`、`current_tool`、`alive` | 仅用于保活与「工作中/卡住」指示，不产生内容 |
| `final_answer` | 历史回放路径使用（`ChatModels.swift:473`） | 与 `final` 同义，仅出现在历史消息解析 |

解析上的三个坑（Android 必须复刻，否则会出现丢内容/重复内容）：

1. **类型来源双轨**：`event.type` 为空或 `message` 时，回退到 JSON body 里的 `type` 字段。
2. **载荷层级双轨**：真实字段可能在 `payload` 子对象里，也可能平铺在顶层。
3. **空闲看门狗 ≠ 服务端超时**：iOS 侧 120s 无任何帧才判超时并提示重连（`ChatStreamingService.swift:20`），而服务端心跳间隔 15s——阈值差留了 8 倍余量。

### 4.4 连接生命周期与断线重连（实测）

这是 Android 端最容易写错、也最值得一次做对的部分。iOS 现状（`ChatViewModel.swift` 1393 行 + `ChatStreamingService.swift`）：

| 机制 | 参数 | 作用 |
| --- | --- | --- |
| SSE 空闲看门狗 | 120 s 无任何帧才判超时 | 服务端 15 s 心跳，阈值留 8 倍余量 |
| run 状态轮询 | 5 s | 兼作 SSE 之外的存活兜底 |
| 「卡住」检测 | 90 s 无进展 | 重构输入框下方的 working/stuck 状态条 |
| 重连退避 | `0.4 · min(8, 2^(n-1))` s，最多 5 次 | 弱网抖动下的自动重挂 |
| 会话列表刷新 | 30 s | 仅前台 |
| 待恢复流持久化 | `stockagent.pendingStreams` | 记录 `{sessionId, runId, userText, updatedAt}`，冷启动后可恢复 |

**关键：iOS 没有任何后台模式**（无 `UIBackgroundModes`、无 BGTaskScheduler），全部定时器仅前台生效；App 回到前台时统一走 `handleAppBecameActive` 重新对齐状态。因此**「后台常驻盯盘」不是对齐项**——盯盘逻辑本来就在服务端跑，客户端只需要推送与前台刷新。这一点显著降低了 Android 的复杂度（见第 8 节）。

**断线重连的真实语义（已核对源码）**：`CopilotService.stream_run()` 把 agent 执行交给后台 producer 持有，`HTTP` 断开不取消 run；重开同一个 `run_id` 会**从头重放 `state.live_buffer`**，再接实时尾巴。全仓库无 `Last-Event-ID`、无事件 id、无游标去重。

> ⚠️ 后果：重连后 `partial_answer` 会被**重复追加**（iOS 目前就是盲追加，会出现可见的答案重复）。Android 必须自己去重，但重放帧里**没有稳定 id**可用（见第 9 节第 4 条的服务端建议）。

### 4.5 REST 端点清单（iOS 实际调用的 45 个）

| 域 | 端点 |
| --- | --- |
| 对话（12） | `GET/POST /api/copilot/sessions`；`PUT/DELETE /api/copilot/sessions/{id}`；`GET /api/copilot/sessions/{id}/messages`（`limit_turns`、`before` 游标分页）；`POST /api/copilot/sessions/{id}/messages`；`POST .../runs/{run_id}/cancel`；`GET .../runs/{run_id}/status`；`GET .../uploads`；`POST .../uploads`（multipart，字段名 **`files`**）；`DELETE .../uploads/{filename}` |
| 自选 / 标的（11） | `GET /api/watchlist`；`POST /api/watchlist/items`；`DELETE /api/watchlist/items/{symbol}`；`GET /api/stocks/search?q=`；`GET /api/stocks/{symbol}/context`；`.../history?days=`；`.../intel`；`.../financial`；`POST /api/stocks/{symbol}/research`；`GET /api/reports/{report_id}`；`GET /api/reports?page&page_size` |
| 持仓（1） | `GET /api/holdings` |
| 盯盘（9） | `GET /api/monitor/events?page&page_size`；`GET /api/monitor/status`；`POST /api/monitor/start`；`POST /api/monitor/pause`；`GET /api/monitor/rules`；`POST /api/monitor/rules`；`DELETE /api/monitor/rules/{id}`；`POST /api/monitor/evaluate-once`；`POST /api/monitor/feedback` |
| 策略 / 回测（4） | `GET /api/strategies`；`GET /api/strategies/{id}/backtests/latest`；`POST /api/strategies/{id}/backtest`；`GET /api/backtests/{run_id}` |
| 设置 / 运行时（11） | `GET /api/settings`；`PUT /api/settings/skills`；`PUT /api/settings/market-refresh`；`PUT /api/settings/investor-profile`；`PUT /api/settings/notification-prefs`；`PUT /api/settings/data-provider`；`GET /api/settings/llm/providers`；`PUT /api/settings/llm/default-model`；`POST /api/settings/llm/connect`；`DELETE /api/settings/llm/providers/{provider_id}`；`GET /api/runtime/cost-summary` |
| 定时任务（3） | `GET /api/scheduled-tasks`；`POST /api/scheduled-tasks/{id}/toggle`；`POST /api/scheduled-tasks/{id}/run-now` |
| ~~设备 / 推送~~ | 端点已随 iOS 客户端移除，当前无推送 API |
| 健康（1） | `GET /api/health` |

**字段风格**：后端为 Python/Pydantic，JSON 一律 `snake_case`（如 `run_id`、`current_tool`、`page_refresh_seconds`）。Android 侧必须显式配置命名策略，不要依赖「默认驼峰」。

### 4.6 Markdown 与附件

Web 端自研渲染器，支持块类型仅 6 种：`heading`、`hr`、`table`、`ol`、`ul`、`p`（外加代码围栏与行内样式）。流式策略（`frontend/src/lib/streamMarkdown.ts` + `StreamMarkdown.tsx`）：

- 把已闭合的块切出来做 **memo 渲染**，只重渲「生长中的尾巴」；
- 尾巴超阈值时**退化为纯文本**，避免每帧全量解析；
- 代码围栏未闭合时不得在围栏内切块。

iOS 端等价物是 `AnswerFormatter.swift`（356 行，自研切块）+ `MarkdownText.swift`（214 行）。**Android 不需要引入重量级 Markdown 库**，移植这套「稳定块 + 长尾降级」逻辑即可，工程量与风险都可控。

但要注意 iOS 自研渲染器还包含两处**中文/桌面对齐的预处理**，Android 若直接用通用 Markdown 库、不做同等归一化，输出会肉眼可见地不一致：

- 中文正文的「松换行」重写（避免中文段落被硬换行切断）；
- 软换行统一转硬换行；
- 中文有序列表分隔符（`1.` 与 `1、` 都要认）；
- 无序列表符号除 `- * +` 外还要认 `• · –`。

**附件上传的边界条件**（`routes_copilot.py:63-74,144-216`）：multipart 字段名 `files`（可重复）、单文件上限 50 MB、图片仅 `png/jpg/jpeg/webp`、二进制文本需 UTF-8、运行时不支持附件时返回 **409**（客户端应呈现「当前运行时不支持附件上传」而非当作致命错误），超限 413，类型不合法 415。响应体可能无法解码，iOS 的做法是回退到重新列表。

### 4.7 平台行为对照表（iOS → Android 机制映射）

行为必须对齐，机制必须换掉。具体库选型见第 7 节。

| 能力 | iOS 现值 | Android 对应机制 |
| --- | --- | --- |
| 令牌安全存储 | Keychain 通用密码，service `com.stockagent.app`，account `accessToken`，`AfterFirstUnlockThisDeviceOnly` | **DataStore + Android Keystore AES-GCM**（或 Tink）。⚠️ **不要用 `androidx.security:security-crypto`（EncryptedSharedPreferences）**：1.1.0 虽已发布，但全部 API 自 1.1.0-beta01（2025-06）起被标记废弃，官方改为推荐直接使用平台 API 与 Keystore。语义要对齐三点：解锁后可读、仅本机、**不进云备份**（排除 backup rules） |
| 非敏感配置 | UserDefaults（`remoteUrl`、`lastSuccessfulUrl`） | DataStore(Preferences) 或 SharedPreferences |
| 自签 TLS 放行 | `TrustingURLSessionDelegate` 无条件接受任意 server trust（安全性上是 iOS 现存的弱点） | **推荐：把你自己的自签 CA 作为 trust-anchor 打进 `res/raw`，用 network-security-config 声明**——既能连自签服务器，又不放弃证书校验。**不要**做成全局 trust-all。**REST 与 SSE 必须共用同一套信任配置**，否则会出现「能发消息但流连不上」 |
| 明文 HTTP 放行 | Info.plist ATS 例外，白名单 `example.com` | network-security-config 按域名 `cleartextTrafficPermitted`（比全局 `usesCleartextTraffic` 收敛） |
| 网络可达性 | `NWPathMonitor` → 全局橙色横幅 | `ConnectivityManager.registerDefaultNetworkCallback` → Compose 全局横幅 |
| 401 语义 | `reportUnauthorized()` → 「登录已失效，请重新连接服务器」，可关闭 | 同构：网络层统一拦截 401 并置全局状态。注意服务端**只有这一种 401**，不存在令牌刷新流程 |
| 通知权限 | `UNUserNotificationCenter.requestAuthorization` | Android 13+ 需运行时申请 `POST_NOTIFICATIONS`；12 及以下默认授予，需分支处理 |
| 通知点击深链 | `userInfo{kind, event_id, symbol, session_id, report_id, task_id}` → `NotificationCenter` 内部事件 → 切 Tab / 开详情 | PendingIntent 携带同一组 data 键；Activity 建议 `singleTask` + `onNewIntent`，并在冷启动路径上同样消费一次 |
| 前台通知展示 | `willPresent` → banner + sound + badge | 高重要性 NotificationChannel 产生 heads-up |
| 图片选择 | `PhotosPicker` | Photo Picker（Android 13+）/ `ACTION_OPEN_DOCUMENT`；**不要**申请 `READ_MEDIA_IMAGES`，Photo Picker 无需存储权限，对隐私合规更友好 |
| 文件选择 | `.fileImporter` | `ACTION_OPEN_DOCUMENT`（SAF），拿 `content://` URI 后直接以流式上传，不必落地临时文件 |
| 复制 / 分享 | `UIPasteboard` / `ShareLink` | `ClipboardManager` / `ACTION_SEND` |
| 主题持久化 | UserDefaults：`themeAccentHex`、`themeScheme` | DataStore（保持同名键便于两端对齐排查） |
| 聊天壁纸 | `Documents/chat-background.jpg`（≤2048 px），调暗 0.1–0.75 | 应用私有目录 `filesDir`，同样只存本机、不上传 |
| 相对时间 | `RelativeDateTimeFormatter`（zh_CN） | `DateUtils.getRelativeTimeSpanString` 的中文输出质量一般，建议手写 zh 文案以对齐 iOS 措辞 |
| 对话待恢复状态 | UserDefaults：`pendingStreams`（JSON） | DataStore 存同一份 JSON 结构即可，无需上 Room |
| 图表 | Swift Charts（30 日收盘折线 + 面积） | 见第 7 节图表选型 |
| 自动连接 | **无**：`isConnected` 仅存内存，冷启动永远回到连接页 | 对齐即可（不要自作主张做自动重连，否则会掩盖令牌失效问题） |

---

## 5. 候选方案对比

### 5.1 候选方案

| # | 方案 | 说明 |
| --- | --- | --- |
| A | **原生 Android**：Kotlin + Jetpack Compose | 第一方 UI／网络／后台能力；与 iOS 各自原生 |
| B | **React Native + Expo** | 复用团队既有 React/TS 技能；native module 桥接原生能力 |
| C | **Flutter** | 单一 Dart 代码库，未来可覆盖 iOS |
| D | **Kotlin Multiplatform（含 Compose Multiplatform 统一 UI）** | 与 iOS 共享网络层/模型层甚至 UI |
| E | **WebView / Capacitor 复活** | 复用现有 React Web 前端 |
| F | **uni-app / Taro** | 国内跨端生态，WebView/小程序式渲染 |

### 5.2 评价维度与权重（技术成熟度优先）

按用户要求，**以「技术成熟度」为首要权重**，不再把「原生形状」当作选型依据——聚合推送 SDK（个推等）对 RN/Flutter/原生都有客户端，自签 TLS 三种栈也都能做，「能不能做」的差异已被抹平，剩下的是「做得多成熟」。

| 维度 | 权重 | 理由 |
| --- | ---: | --- |
| 框架与生态成熟度（稳定性、活跃维护、长期支持） | ★★★ | 单人项目经不起框架本身翻车 |
| 团队技能契合与既有代码复用 | ★★★ | Web 端已有 TS 的流式 Markdown 分块、图表、会话逻辑，可被 RN 直接复用 |
| 关键能力的生态成熟度（SSE / 图表 / Markdown） | ★★★ | Chat 占工程量近一半 |
| 单人长期可维护（构建/发布/升级链） | ★★ | 1 人已维护 4 个端 |
| 平台运行时可靠性（自签 TLS、长连接、通知） | ★★ | 各栈都能做，但成熟度有差：原生 okhttp-sse 一等公民，RN 二线，Flutter 无一等公民 SSE |
| 分发与合规适配成本 | ★★ | 隐私弹窗、SDK 披露、权限收敛 |

> 与上一版的差异：删掉「自签 TLS ★★★」「厂商推送 ★★★」这两个驱动原生的维度——本轮判定它们**非原生独占**。

### 5.3 决策矩阵（技术成熟度权重）

依据 2026-10-16 核实的版本与生态状态（见 5.5）。

| 维度 | B RN/Expo | A 原生 | C Flutter | D KMP | E/F WebView·uni-app |
| --- | :--: | :--: | :--: | :--: | :--: |
| 框架生态成熟度 | 优 | 优 | 优 | 中 | — |
| 团队技能契合 / 代码复用 | **优**（复用 Web 的 TS 逻辑） | 低（第三遍重写同一套逻辑） | 低（第四门语言） | 中（仅复用 iOS 逻辑） | — |
| SSE / 图表 / Markdown 生态 | 良（均活跃） | 优（okhttp-sse 一等公民） | 中（SSE 无一等公民、md/chart 停更） | 良 | — |
| 单人长期可维护 | 良（EAS + OTA 更新） | 良 | 中 | 差 | — |
| 平台运行时（自签 TLS/长连接/通知） | 中（TLS 需原生配置） | 优 | 良 | 优 | — |
| 分发/合规适配 | 中 | 良 | 中 | 良 | — |
| **结论** | **✅ 主推** | 🥈 并列备选 | ❌ | ❌（现阶段） | ❌ 已否决 |

> RN 与原生都是成熟的一线选项，得分相近：RN 赢在「技能契合 + 代码复用」，原生赢在「平台运行时成熟度」。综合取 RN；若把「长连接平台可靠性」提到最高优先级，应回原生（见 6.3）。

### 5.4 四个容易误判的点

**1）「原生形状」不是选型依据。** 这是上一版的误判：聚合推送 SDK（个推等）对 RN/Flutter/原生都有客户端，自签 TLS 在三种栈里都能做（原生 network-security-config、Flutter `badCertificateCallback` 一行、RN 用 native config）。真正的差异是「各端做得有多成熟」，而不是「能不能做」。

**2）成熟度差异集中在 SSE 与 Markdown/图表生态。** 原生 `okhttp-sse` 是一等公民；RN 的 SSE（`react-native-sse` / fetch 流式）二线但可用、Markdown/图表库 2026 年仍活跃；Flutter **没有**一等公民 SSE（要手动解析 `text/event-stream`），且 `flutter_markdown` 最后发布 2025-05-06、`k_chart` 最后发布 2023-05-30——对「Chat 占一半工程量」的应用是硬伤，这是排除 Flutter 的实证依据。

**3）代码复用是 RN 真正的成熟度红利，不只是「同一门语言」。** Web 端 `streamMarkdown.ts`（稳定块分块 + 长尾降级）、`MarkdownRenderer.tsx`、`StockHistoryChart.tsx` 都是 TS，RN 可**直接复用逻辑、只换渲染层**。这套流式 Markdown 的中文归一化是最易错的部分，iOS 已经用 Swift 重写了一遍——原生/Flutter 会要求写第三遍。

**4）KMP 统一的代价被低估；WebView 已被否决。** KMP/CMP 已稳定（CMP 1.12.2），但采纳意味着重写已完成并工作的 iOS 应用，且帮不到 Web/TS/Tauri 那一侧。WebView/Capacitor 方案已被 `mobile/README.md` 明确废弃，不重开。

### 5.5 核实到的当前版本（2026-10-16）

| 组件 | 版本 | 来源 |
| --- | --- | --- |
| Kotlin | 2.4.21（稳定，2026-10-08；2.5.0 计划 2026-12） | [kotlinlang.org/docs/releases](https://kotlinlang.org/docs/releases.html) |
| Android Gradle Plugin | 9.4.1（9.5.0 仍为 alpha） | Google Maven 元数据 |
| Compose BOM | 2026.09.00 | Google Maven 元数据 |
| Compose Multiplatform | 1.12.2（2026-10-15） | [whats-new-compose-112](https://kotlinlang.org/docs/multiplatform/whats-new-compose-112.html) |
| KMP 平台支持 | Android Stable / iOS Stable | [supported-platforms](https://kotlinlang.org/docs/multiplatform/supported-platforms.html) |
| Flutter / Dart | 3.47.7 / 3.13.5（2026-10-08） | 官方发布记录 |
| React Native | 0.88.0（2026-10-12） | 官方发布记录 |
| Expo SDK | 57（RN 0.86，2026-06-30）；58 beta（RN 0.88 RC）自 2026-09-15 | 官方发布记录 |

> 版本号更新很快，落地前请以当日官方源复核；本表用于判断**代际**而非锁死具体补丁号。
>
> **已独立复核（2026-10-16 抓取官方页面）**：
> - Kotlin 2.4.21 / 2026-10-08，且 2.5.0 计划于 2026-12 —— 与官方发布页一致。附带信息：2.4 发布线（2.4.0 + 2.4.20）的安全支持窗口至 **2027-12-03**，对单人长期项目是加分项（[官方发布页](https://kotlinlang.org/docs/releases.html)）。
> - 小米应用商店政策原文确认：「**小米应用商店暂不接受个人开发者账号申请**」，可见账号类型仅企业 / 政府事业单位 / 其他组织三类（[开发者账号注册标准](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1731)，页面标注更新于 2024-09-24，抓取时仍为现行版本）。

---

## 6. 推荐方案

### 6.1 结论

**按技术成熟度权重：选择 React Native + Expo（development build / CNG，非 Expo Go）。**

原生 Kotlin + Compose 作为**并列备选**（当长连接平台可靠性被提到最高优先级时启用）。不用 Flutter、不复活 WebView、现阶段不做 KMP 统一。

### 6.2 理由（成熟度视角）

1. **团队技能契合是第一位的成熟度红利**：这个仓库的 Web 端就是 React 19 + TypeScript。RN 复用同一套语言与心智模型，学习成本近乎为零——这是原生（引入 Kotlin）和 Flutter（引入 Dart）都没有的。
2. **既有 TS 逻辑可直接复用**：流式 Markdown 分块（`streamMarkdown.ts`）、渲染器（`MarkdownRenderer.tsx`）、图表（`StockHistoryChart.tsx`）是易错的核心，RN 只需换渲染层，不必重写逻辑。
3. **生态成熟且活跃**：RN 0.88 已全面切 New Architecture；SSE/图表/Markdown 相关库 2026 年仍在维护（见 5.5/5.4）；Expo 的构建（EAS）与更新（expo-updates）对「自分发 APK」是现成加分项。
4. **跨端能力留有余地**：即便今天只做 Android，RN 代码结构天然可延伸到 iOS/桌面，未来若要收敛移动端，成本远低于「再从 Kotlin 翻到另一套」。
5. **Flutter 被排除是有实证依据的**：无一等公民 SSE、markdown/chart 依赖停更（见 5.4），对「Chat 占一半」的本应用是硬伤。

### 6.3 关键取舍：RN 的两个代价与原生备选的触发条件

RN 不是没有代价，这两处必须提前认知：

| 代价 | 说明 | 对策 |
| --- | --- | --- |
| 自签 TLS 要落原生配置 | RN 无内置 trust 配置，需 config plugin / `expo-build-properties` 声明 trust-anchor（iOS 还要 ATS 例外） | **一次性的 build 配置**，不是每处都要桥 |
| SSE 是二线实现 | `react-native-sse` 或 fetch 流式，成熟度低于 okhttp-sse；后台化、JS 线程保活需留意 | 采用 7.3 节的「应用级 store 持有流 + 按轮次重建」，规避已知坑 |

**触发回原生的条件**（满足任一即应重新选原生）：

| 触发条件 | 说明 |
| --- | --- |
| 实测 RN 的 SSE 在本后端上稳定度不达标（重连/后台频繁断） | 原生 okhttp-sse 是最后手段 |
| 需要深度集成多家厂商原生推送 SDK（不走聚合） | 原生桥接成本会快速累积 |
| 团队决定彻底放弃 Web/TS 技术栈 | RN 的复用红利消失 |
| 需要极致的离线/后台能力 | 原生对 WorkManager/FGS 的直接控制更强 |

### 6.4 什么情况下应该重新评估本决策

| 触发条件 | 应重新考虑 |
| --- | --- |
| 实测 SSE 在 RN 上不稳定 | 方案 A（原生） |
| 需要同时上 iOS（且要共享逻辑） | RN 本身可覆盖双端 |
| 决定放弃原生 iOS、只保留一套移动端代码 | RN（直接覆盖双端） |
| 团队扩员后新增人手只熟原生/Kotlin | 方案 A（原生） |

---

## 7. 技术栈明细（主推：React Native + Expo）

### 7.1 工作流与构建

| 项 | 选择 | 说明 |
| --- | --- | --- |
| 框架 | Expo SDK 57（RN 0.86）+ React 19 | New Architecture（SDK 58 / RN 0.88 仍为 beta） |
| 工作流 | **development build（CNG / prebuild），非 Expo Go** | 接个推原生 SDK、自签证书 trust、通知权限都需要原生层，Expo Go 装不下 |
| 构建 / 发布 | EAS Build + `expo-updates`（OTA 更新） | 正好解决 8.1 节「APK 无自动更新」的痛点 |
| 语言 | TypeScript | 与 Web 端一致 |
| 路由 | expo-router（文件路由 + 深链） | 5 个 Tab + 通知深链直达 |
| `minSdk` / `targetSdk` | 26 / 36 | 与原生方案同结论（见 11 节） |

### 7.2 依赖选型

| 关注点 | 选择 | 理由 / 次选 |
| --- | --- | --- |
| SSE 流式 | fetch 流式（New Arch 支持）或 `react-native-sse` | 流本身不限时 + 应用层 120s 空闲看门狗；复用 Web 端事件解析逻辑 |
| 状态管理 | 轻量全局 store（Zustand）或 React Query | 应用级 store 持有流，页面只订阅（见 7.3） |
| Markdown | **复用 Web 的 `splitStableBlocks` 分块逻辑**，渲染层用 RN 组件 | 逻辑零重写；`@ronradtke/react-native-markdown-display` 作现成兜底 |
| 图表（折线+面积） | **复用 Web 的 layout 逻辑 + `react-native-svg` 自绘** | 只换 SVG 渲染层；`react-native-gifted-charts` 作兜底 |
| 推送 | 个推 RN SDK（dev build 接入） | 接口抽象同第 8.3 节 |
| 通知 | `expo-notifications` | 权限、通道、点击深链 |
| 图片 | `expo-image` | 性能与缓存 |
| 文件 / 相册 | `expo-document-picker` / `expo-image-picker` | 无需存储权限 |
| 令牌存储 | `expo-secure-store`（Keychain / Keystore 封装） | 对齐 iOS 语义；**不用 EncryptedSharedPreferences** |
| 自签 TLS | config plugin / `expo-build-properties`：Android network-security-config + iOS ATS | 一次性 build 配置 |
| 测试 | Jest + `@testing-library/react-native` + MSW（mock SSE） | 专测「重放去重」 |

### 7.3 SSE 设计（RN 版，逻辑与原生版等价）

1. **流的归属跳出组件**：由应用级单例 store（如 Zustand）持有 SSE 连接与归约后的状态，React 组件只订阅——避免旋转/导航重建导致断流。
2. **无超时 + 应用层看门狗**：流本身不限时，应用层实现 120s 空闲看门狗，以「收到任意帧」续期（服务端 15s 心跳）。
3. **只在「用户停止」或「终态事件」时结束连接**。
4. **不做自动重连**，自己做退避 `0.4·min(8, 2^(n-1))` s、最多 5 次。
5. **重连按轮次重建，而非增量续写**（服务端从头重放，见 4.4/8.5）。
6. **网络恢复触发重挂**（`@react-native-community/netinfo` 或 `expo-network`）。
7. **不需要前台服务/长驻**：`targetSdk 36` 下 FGS 24h 上限 6 小时；盯盘 = 推送 + WorkManager（最小 15 分钟）。与 iOS 对齐，前台才有流。

> ⚠️ 同原生版结论：后端**不处理** `Last-Event-ID`（全仓库无此逻辑），不要照搬「持久化 lastEventId + 续传头」的做法——照搬会收到全量重放、更容易重复。只能走第 5 条「按轮次重建」。

### 7.4 复用 Web 逻辑的模块边界

把 Web 端这些**纯逻辑**抽成可被 RN 引用的共享代码（同仓库 package，或直接 import）：

```
frontend/src/lib/streamMarkdown.ts    ← 稳定块分块 + 长尾降级（RN 直接复用）
frontend/src/lib/sortStockSeries.ts   ← 图表数据整形
事件解析 / 状态归约                    ← 将 CopilotStreamParser 语义改写为 TS（与 iOS 第 4.3 节对齐）
```

渲染层（RN 的 `<Text>` / `react-native-svg`）留在 RN，**逻辑层共享**。这是原生方案无法提供的、真正的成本节省。

### 7.5 平台陷阱清单（RN 版）

| 陷阱 | 对策 |
| --- | --- |
| Expo Go 装不下原生模块 | 一律走 development build / CNG |
| 自签证书握手失败 | config plugin 声明 trust-anchor；**不要全局 trust-all** |
| 明文 HTTP 被拦 | Android network-security-config 按域名放行；iOS ATS 例外 |
| SSE 被 read timeout 掐断 | 流本身不限时 + 应用层看门狗 |
| Android 13+ 通知权限 | `expo-notifications` 运行时申请 `POST_NOTIFICATIONS` |
| 前台服务类型 / 6h 上限 | 不依赖长驻 FGS；盯盘走推送 + WorkManager |
| New Architecture 下第三方原生模块兼容 | 接个推/厂商 SDK 前先确认其对 RN 0.88 New Arch 的支持 |
| 长列表流式更新 | FlatList 稳定 key + 稳定块 memo、只重渲尾巴（同 Web `StreamMarkdown` 策略） |
| 中文排版 | 复用 Web 的中文归一化，别只换渲染器 |
| 首次启动 SDK 初始化 | 推送/统计 SDK 推迟到同意隐私政策之后（8.4 节） |

### 7.6 备选栈速览（原生 Kotlin + Compose，若回退）

保留上一版原生栈的关键结论，回退时直接用：Kotlin 2.4.21 / AGP 9.4.1 / Gradle 9.8.1 / Compose BOM 2026.09.00；OkHttp + `okhttp-sse` 5.5.0（SSE 一等公民）；kotlinx.serialization 1.11.0；Hilt 2.60.1；Coil 3.6.3；Vico 3.3.1（K 线）；DataStore + Keystore AES-GCM（**勿用已废弃的 security-crypto**）；WorkManager 2.12.0。


---

## 8. 关键风险与对策

按「会真正卡住项目」的程度排序。

### 8.1 分发是硬墙，不是技术问题（最高优先级）

**现实**：股票类 App 是国内应用商店的**受限品类**。中央网信办与证监会要求平台和应用商店把**核验证券资质作为上架前置条件——「未获相关资质的，不予合作、上架」**（[2022 年工作方案](http://www.chinadevelopment.com.cn/news/zj/2022/12/1815404.shtml)）。而**证券投资咨询牌照个人无法取得**（需公司主体、注册资本、持牌人员）。同时：

- **小米应用商店明确不接受个人开发者账号**（[开发者账号注册标准](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1731)）；
- **应用宝个人账号不能上架金融类目**（[账号说明](https://aiflutter.com/docs/zh/guide/yingyongbao-account.html)）；
- 主流商店普遍要求 **软著 + APP 备案**（小米明确两者皆需，[应用资质 FAQ](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=2251)）；
- **APP 备案是法定义务**：「未履行备案手续的，不得从事 APP 互联网信息服务」（[工信部通知](https://www.miit.gov.cn/zwgk/zcwj/wjfb/tz/art/2023/art_920db564162e4312916a01bed6540ad8.html)），个人可办，实际 15–20 个工作日；且备案域名还需 ICP 备案。

**对策**：把 Android 客户端定位为**自用 / 熟人分发的 APK**，走「自有服务器或 GitHub Releases 下载 + 应用内更新」路径。摩擦是真实的但可控——安装时需放开「未知来源」、手机管家会提示风险、**没有自动更新所以必须自己做应用内升级**。这条路对技术型 A 股用户完全可行，只是不能指望规模增长。

**不要把「上架」写进里程碑**：一旦涉及商店，软著（30–60 天）、APP 备案（15–20 工作日）、ICP 备案、主体注册、证券资质会串成一条数月且可能走不通的链路。若将来确要上架，先解决主体与资质，再谈技术。

### 8.2 后台与自启动合规（最容易踩的红线）

**事件**：2025 年工信部通报的侵权违规问题中，**「APP 频繁自启动和关联启动」是 Top-5 高频问题之一**（全年 8 批、315 款 App，[分析](https://www.sundiallawfirm.com/viewpoint/1484.html)）。而「推送 SDK + 后台常驻盯盘服务」恰好就是这个形状。

**好消息**：第 4.4 节已确认——**iOS 端根本没有后台模式**，所有定时器仅前台生效，盯盘逻辑本来就在服务端跑。所以**后台常驻不是功能对齐项**。

**对策**：
1. **默认不做后台常驻**，与 iOS 对齐（前台刷新 + 推送送达）。
2. 若确要提供，做成**显式 opt-in 开关**（如「后台常驻盯盘」），由用户主动开启，并提供等价的关闭路径；不要静默自启动、不要关联启动。
3. 优先用**推送**而非客户端轮询来实现「人不在 App 里也能收到告警」——服务端已经在跑监控。
4. **技术上也做不到「永久常驻」**：`targetSdk 36` 下，App 在后台时前台服务 24 小时内累计上限 6 小时（Android 15+ `Service.onTimeout`）。所以「后台盯盘」的正确定义是**定期检查（WorkManager，最小间隔 15 分钟）+ 推送送达**，而不是一个永不退出的服务（见 7.3 第 7 条）。

### 8.3 推送可达性与「消息分类」合规

**FCM 在国内不可用**：需要 GMS 且设备能连通 Google 服务，而国内华为/荣耀/小米/OPPO/vivo ROM 普遍不带 GMS；即便侧载 GMS，ROM 也会主动拦截（[uni-app FCM 文档](https://uniapp.dcloud.net.cn/uni-push/google-fcm.html)）。**结论：FCM 直接排除。**

**厂商推送有两道门**：
1. **资质门**：小米不接受个人开发者账号；华为/OPPO/vivo/荣耀需实名与逐项申请。华为推送「自分类权益」、OPPO「私信通道」都要**逐类申请并获批**（[华为权益申请](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/push-apply-right)、[厂商消息分类汇总](https://www.alibabacloud.com/help/zh/mobile-platform-as-a-service/latest/vendor-message-classification)）。
2. **分类门**：2026-08-01 起小米推送新分类把消息分为「私信」（不限量、可响铃震动）与「公信」（有日限额）。**行情/盯盘提醒属于可订阅的公信类**（如「主动设置的行情动态提醒」），要求 App 内提供**订阅/取消订阅入口、默认关闭、文案明确写「您订阅的…」**；「订阅行情资讯」这类宽泛描述会被驳回（[小米推送 2026 分类新规](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=2321)）。华为 `FINANCE`/`SUBSCRIPTION`、vivo `SUBSCRIPTION` 是同类通道，同样要求订阅式交互。

**聚合 SDK（省事但有坑）**：
- **极光 JPush 免费版有两个陷阱**：免费用户不能对普通推送使用厂商通道，且**单次请求中最多 30% 的厂商通道用户可走厂商通道**；付费约 **¥20,000/年**（[V2EX 讨论](https://global.v2ex.co/t/1211177)）。
- **个推免费版可用**：不限推送量，覆盖华为/荣耀/小米/OPPO/vivo/魅族，20 个 App；限制是**全量广播 20 条/天**，而单推 250 万/天、列表推 200 万/天（[个推消息推送](https://www.getui.com/notification-push)）。盯盘告警是**单推/定向推**，不受广播限额影响，因此可行。
- 腾讯 TPNS **已停售新用户**；友盟 U-Push 免费版据报无 JPush 那两个陷阱（待自行核实）。
- **关键误区**：聚合 SDK **不会替你申请厂商通道**。极光官方文档同样指向各厂商的参数申请流程（[极光厂商通道参数申请指南](https://docs.jiguang.cn/jpush/client/Android/android_3rd_param)）。聚合省的是**服务端 fan-out**，不是厂商侧手续。

**对策（建议）**：
- 客户端与后端**先定义一个推送抽象接口**（服务端见第 9 节；客户端需可延迟初始化，见 7.5），落地时优先接入**个推免费版**：服务端只做一次 REST 集成（约 1–2 天），避开 5 套厂商凭据 + 5 套分类审批的持续维护。
- 厂商通道参数**只申请实际用户所在的那 2–3 家**。
- **从第一天就按「订阅式提醒」设计 UX**：设置页里对每类盯盘提醒有明确的订阅开关（默认关）、可随时退订、文案写明「您订阅的…」。这不只是合规，也是拿到高优先级通道（能响铃震动）的前提。
- 服务端推送封装仍按第 9 节的方式对接 `CompositeAlertSink`，**厂商/聚合的差异只存在于一个 service 实现里**。

客户端侧同样保持一个最小接口，让「厂商 SDK / 聚合 SDK / 完全无推送」三者可互换：

```kotlin
interface PushProvider {
    suspend fun register(): ProviderToken?   // 返回 (provider, token)，上报后端
    val messages: Flow<PushMessage>          // 通知点击 / 数据消息 → 深链字段
}
```

落地策略：按**品牌 + GMS 可用性**在运行时选择 provider；后端只存 `(provider, token)` 二元组。这样将来从个推换成自接厂商 SDK，或临时降级为「无推送纯前台」，都不需要改动上层业务代码。

### 8.4 隐私合规的两个架构级约束

1. **首次启动必须「先同意、后初始化 SDK」**。商店与监管明确要求：启动 App 时用户先同意隐私协议，**才能初始化对应 SDK（含统计类）**（[V2EX 案例](https://global.v2ex.co/t/1211177)）。
   → **对策**：把推送/统计等 SDK 的初始化**推迟到同意之后**，这是架构约束而非文案工作。第 7 节的推送抽象接口应设计成「可延迟初始化」。
2. **SDK 信息公示要到位**。「SDK 信息公示不到位」是 2025 年工信部通报的高频问题之一：必须逐项列出第三方 SDK、运营方、收集的信息、并链接其隐私政策；「包括但不限于」这类模糊表述会被驳回（[同前分析](https://www.sundiallawfirm.com/viewpoint/1484.html)）。
   → **对策**：**每引入一个第三方 SDK（尤其是推送 SDK）都是一次合规成本**。这也是「先只接一个聚合 SDK，而不是 5 个厂商 SDK」的另一个理由。

3. 权限遵循**最小必要**：不在启动时一揽子申请，只在用户触发动作时申请；拒绝后不重复弹窗；拒绝不得导致基本功能不可用。图片选择建议用 **Photo Picker**，无需存储权限（见 4.7）。

> 补充：**AI 功能可能触发算法备案**。商店对「AI 生成合成类」App 要求互联网信息服务算法备案/生成式 AI 备案，小米与三星的资质政策中均有体现（[小米资质 FAQ](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=2251)、[三星 AI 生成合成类上架政策](https://support-cn.samsung.com/App/DeveloperChina/Notice/Detail?NoticeId=136)）。**未验证**：私有/熟人分发的工具是否可豁免——规则是按功能而非按规模写的。自分发阶段可暂不处理，但**若要上架，这是继证券资质之后的第二道关**。

### 8.5 流式渲染与断线重连的重复内容

`run_id` 重连会从头重放 `live_buffer`，且重放帧**没有稳定 id**（第 4.4 节）。iOS 目前是盲追加 `partial_answer`，重连会出现可见的答案重复。

**对策**：Android 侧做到「**以轮次为单位重建**」而非增量拼接——重连后丢弃当前轮的临时状态，从重放帧重新归约一次；同时按第 9 节第 4 条推动服务端在重放帧里带上 `message_id`，把近似去重升级为确定性去重。

### 8.6 图表与 Markdown 的「看起来对」风险

- **Markdown**：iOS 是自研渲染器并带**中文预处理**（中文松换行重写、软换行转硬换行、`1、` 有序列表、`• · –` 无序符号）。直接套通用库会在中文长文上肉眼可见地不一致。**对策**：把这套归一化规则一并移植，而不是只换渲染器。
- **图表**：需求只是「30 日收盘折线 + 面积」（对齐 iOS Swift Charts），**不需要 K 线蜡烛图**。不要为一个折线图引入重型图表库；如需 K 线（未来做行情页），再上支持蜡烛图的库（见 7.2）。

### 8.7 生态与技能风险

- **Flutter 侧关键依赖存在停更信号**（`flutter_markdown` 停更于 2025-05，`k_chart` 停更于 2023-05），这是排除 Flutter 的实证依据，已计入第 5 节。
- **RN 的 SSE 是二线实现**（成熟度低于原生 okhttp-sse），是本项目唯一需要实测验证的点。**对策**：M0 先做「连接后端 + 一条能流式吐字的消息」的最小闭环，尽早暴露 SSE 稳定性；若实测不达标，按 6.3 回退原生。


---

## 9. 服务端需要配合的改动

以下是 Android 端上线需要在后端做的改动。**第 1–4 条是必做**（均为小改，但缺一不可），第 5–7 条是可选增强或仅需知晓。

> ⚠️ **2026-10-23 更新**：iOS 客户端与整套 APNs 推送已移除
> （`routes_devices.py`、`apns_push.py`、`repo_devices.py`、`apns_device` 表、`CompositeAlertSink` 全部删除）。
> 因此下面第 1、2、6 条描述的"现状"已不存在 —— 推送不是"泛化"，而是**从零新建**：
> 直接建平台中立的 `push_device` 表 + `/api/devices/push` 端点 + 对应的 push service，
> 挂到 `bootstrap` 里替代原先的 `CompositeAlertSink`。IM 通道（`channel_notifier.push`）不受影响。

1. **设备注册端点泛化**。现在只有 `POST /api/devices/apns`，且请求体把 `platform` 默认写死为 `ios`、`bundle_id` 默认 `com.stockagent.app`（`backend/api/routes_devices.py:12-16`）。
   - 方案：新增 `POST /api/devices/push`（或 `/api/devices/android`），字段 `provider`(`fcm`/`getui`/`jpush`/厂商)、`device_token`/`registration_id`、`platform`、`app_id`。
   - 存储：`apns_device` 表**已有** `platform` / `bundle_id` 列（部分泛化，`backend/persistence/db.py:293-301`），但 `environment` 被硬约束在 `{sandbox, production}`，非该值时静默改写为 `sandbox`（`backend/persistence/repo_devices.py:21-23`）——Android token 会被强行塞成 `sandbox`，语义错误。建议改为通用 `push_device` 表（或保留表名但放宽 `environment`），主键 `device_token` 对 FCM/厂商 token 轮换是可接受的。
2. **推送服务实现**。对照 `backend/app_services/apns_push.py` 写一个同构的 Android 推送服务（同一 `push(title, text, **deep_link)` 签名、同一 `configured()` / `status()` 语义），然后挂到 `CompositeAlertSink`：
   `CompositeAlertSink(channel_notifier.push, apns_push_service.push, android_push_service.push)`（`backend/bootstrap.py:379`）。
   - 好处：盯盘告警与定时任务完成/失败的下发点**无需改动**，合成器已经在那儿了。推送载荷键 `{kind, symbol, event_id, session_id, report_id, task_id}` 本身就是平台中立的，只有传输层缺失。
   - 现状核对：仓库内**零** FCM/Firebase 代码；`apns_device.platform` 列被写入但**从未被读取或校验**，而 `APNsPushService._list_devices()` 会把表里**所有**行都当 APNs 设备发往 `api.push.apple.com`。
   - ⚠️ 因此**不能**把 Android token 塞进 `apns_device` 表：它会被拿去打 Apple 的网关。必须加传输类型判别列（如 `transport`），或另建表。
   - 迁移注意：项目**没有迁移框架**，schema 在连接时幂等创建（`backend/persistence/db.py`）。加列要自行处理既有数据库。
   - 推送载荷需保留现有深链字段：`kind`（`scheduled_task` / 告警）、`event_id`、`symbol`、`session_id`、`report_id`、`task_id`（见 `PushNotificationManager.swift:57-84`），Android 侧据此跳转。
3. **iOS 硬编码字段泛化**。以下字符串目前写死在 iOS 客户端，Android 端应使用 `android` 前缀/值，后端需接受任意值：
   - `client_message_id` 前缀 `ios-`（`APIClient.swift:198`）
   - `POST /api/monitor/evaluate-once` 的 `source: "ios_manual"`（`APIClient.swift:417`）
   - 推送注册体里的 `platform: "ios"`、`bundle_id`
4. **流断线续传：已确认支持重连重放，但缺一个稳定去重键**。
   - `CopilotService.stream_run()`（`backend/app_services/copilot_service.py:842-906`）的语义是：agent 执行由后台 producer 任务持有，**HTTP 断开不会取消 run**；重新用同一个 `run_id` 打开流即可「重放已持久化消息 + 接上实时尾巴」。
   - 但它**不是** `Last-Event-ID` 游标续传（全仓库无该头处理），重放是**从 run 开头**开始的。
   - 重放帧由 `_message_to_event()`（`copilot_service.py:1563`）构造，只带 `run_id` / `task_id` / `type` / `payload` / `created_at`，**不含 `message_id`**。而持久化表里是有稳定 `message_id` 的（`repo_copilot.py:538`，按 `created_at, message_id` 排序）。
   - 后果：Android 断线重连后无法可靠区分「重放帧」与「已渲染帧」，只能按 `created_at` + 内容比对做近似去重，容易重复渲染一段答案。
   - **建议（小改动、收益明确）**：在 `_message_to_event()` 的 payload 里带上 `message_id`。这样两端客户端都能做确定性去重，Android 的弱网恢复体验可以优于 iOS 现状。
5. **可选增强**：Android 端可直接消费 `GET /api/monitor/stream`（服务端推送式），替代轮询 `GET /api/monitor/events`，让盯盘页变成真实时。后端无需改动，属白捡的能力。注意它的事件类型是 `status` / `events` / `summary` / `ping`，与对话流不是同一套契约。
6. **可选：推送状态端点**。`GET /api/devices/apns/status` 是 APNs 专属（`routes_devices.py:40-45`）。iOS 设置页会显示推送状态，Android 若要对齐，需要加一个平台中立的 `/api/devices/status`。
7. **无需改动但需知晓**：盯盘事件的**已读状态完全保存在客户端本地**（`MonitorSeenStore`，上限 500 条 id），服务端没有未读 API。Android 从零开始即可，但两端未读状态天然不互通。

---

## 10. 里程碑与工作量

以「对齐 iOS 现有功能面」为目标，按可独立验收的纵向切片推进。人天为**单人开发**的粗估，含自测，不含商店审核等待期。

| 里程碑 | 内容 | 依赖 | 粗估 |
| --- | --- | --- | ---: |
| **M0 骨架与连接** | Expo dev build 工程（CNG）、连接页（地址 + 令牌）、健康探测与 `agent_runtime` 校验、令牌安全存储、自签 TLS 与 http 放行、错误文案与可达性横幅、**SSE 最小闭环（一条消息能流式吐字）** | — | 4–6 天 |
| **M1 对话** | 会话列表/新建/重命名/删除/搜索、游标分页加载历史、SSE 流式接收、10 类事件解析、稳定块 + 长尾降级的流式 Markdown、工具卡片与思考时间线、停止/重试、附件上传与列表删除、追问卡片（选项 + 自由输入） | M0 | 10–15 天 |
| **M2 自选 / 标的 / 持仓** | 自选增删、标的搜索、标的详情（走势图、资讯、财报、研报、「在对话中分析」跳转）、持仓组合摘要与浮动盈亏 | M0 | 6–8 天 |
| **M3 盯盘 / 定时任务 / 推送** | 盯盘启停、规则 CRUD、立即评估、事件列表与详情、未读已读、有用/无用反馈；定时任务列表、启停、立即执行；推送注册、通知权限、点击深链跳转；服务端推送通道打通 | M0、服务端改动 | 6–8 天 |
| **M4 设置全量** | 后端健康探测与切换、模型服务连接/断开/默认模型、AI 技能开关、用量费用、行情刷新频率、行情数据源启停与凭证、研究报告、策略回测、通知偏好、外观主题 | M0 | 6–9 天 |
| **M5 打磨与发布** | 主题与暗色适配、空态/错误态、图标与启动图、Release 签名与混淆、分发与合规材料 | 全部 | 5–10 天 |

**合计约 36–55 人天**（单人全职约 2–2.5 个月；业余节奏约 4–5 个月）。风险集中在 M1，建议 M1 先做一个「能流式吐出 Markdown 的最小闭环」，再补工具卡片、附件、追问等细节。

> 交叉校验：另有一次自下而上的独立估算（按模块逐屏折算 Kotlin 代码量）得出 **≈13,000–16,000 行 Kotlin、9–13 个工程师周**。两者量级一致，可据此判断本表未系统性低估——尤其 M1 的对话模块，其真实体量约占全部工程量的一半。

---

## 11. 待决策项

调研已经替你排除了一批选项，剩下的这几项需要你拍板（按影响排序）：

| # | 决策 | 调研给出的建议 | 影响 |
| --- | --- | --- | --- |
| 1 | **分发定位**：自用/熟人 APK，还是争取上架？ | **自用/熟人分发**（8.1 节：股票类受资质前置限制，个人无法取得咨询牌照；小米等不接受个人开发者） | 若接受，可整条省掉软著（30–60 天）、APP 备案（15–20 工作日）、ICP 备案、主体注册与资质链路；若不接受，先解决主体与资质再谈技术 |
| 2 | **是否引入第三方推送 SDK** | **是，个推免费版**（无 FCM 可用；5 家厂商 SDK 自接的持续维护成本对 1 人过高） | 引入一个 SDK 即带来隐私政策 SDK 公示与延迟初始化的合规工作（8.4 节）；纯自建则等于放弃「人不在 App 也能收到告警」 |
| 3 | **是否顺手改服务端**：给重放帧加 `message_id`（第 9 节第 4 条） | **做** | 成本极小，换来 Android 断线重连的确定性去重；不做则只能用近似去重 |
| 4 | **`minSdk` 下限** | 建议对齐 iOS「只要新系统」的思路，取较新下限以简化通知与前台服务模型 | 影响存量机型覆盖与 API 可用性 |
| 5 | **图表范围**：只要折线+面积（对齐 iOS），还是现在就做 K 线蜡烛图？ | 先对齐 iOS（折线+面积），**不必为折线引入重型库** | 直接决定第 7 节的图表库选择与工作量 |
| 6 | **是否提供「后台常驻盯盘」开关** | 先不做，与 iOS 对齐 | 做了会引入「频繁自启动」合规风险（8.2 节），且与 iOS 行为不一致 |
| 7 | 是否需要 Google Play 版本 | 不需要 | 16 KB 页大小要求仅 Play 且只影响含 native `.so` 的 App；纯 Kotlin 不受影响。targetSdk 仍建议取 36 |

> 说明：第 5.5 节的版本号请以落地当日官方源复核；本文件用于**定方向**，不用于锁版本。

