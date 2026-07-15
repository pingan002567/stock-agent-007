# 桌面化方案与 TeamClaw 调研沉淀

**Status:** 已定方案（方案 C），阶段 0 验证通过（2026-07-15）
**参考项目:** [TeamClaw](https://github.com/different-ai-studio/teamclaw)（Tauri 2 桌面 AI agent 工作台，v2 amuxd 架构分支）

---

## 1. 决策记录

### 1.1 评估过的方案

| 方案 | 形态 | 结论 |
|---|---|---|
| A. Tauri 直接 spawn Python | 壳内 sidecar，关窗即杀后端 | 盯盘/告警随 GUI 死，弃 |
| B. TeamClaw 三层 | Tauri + 常驻 Rust daemon + Python | Rust daemon 在本项目无全职工作（agent runtime 已内嵌 Python），退化为纯保姆进程，而保姆 OS 自带；仅当未来出现"运行时下载托管 / 远程 agent 工位 / 外部 agent 子进程编排"需求时再考虑 |
| **C. Python 注册系统服务 + Tauri 纯客户端** ✅ | launchd user service（`RunAtLoad`+`KeepAlive`）承载后端，Tauri 壳只是连 `127.0.0.1:6666` 的客户端 | **已选定**。TeamClaw 的客户端/服务分离形状，减去没活干的中间层 |

**不引入 MQTT/EMQX/Supabase/protobuf**：那套是 TeamClaw 为多人 agent network 设计的；单用户本地工具用现有 REST+SSE 直连即是其规划中的"本地短路"终态。手机端继续走企微 channel（对话+告警），等价于 TeamClaw 的"不带 daemon 的被动客户端"。

### 1.2 Python 后端弊端评估（接受并对冲）

实测数据：`.venv` 1.0GB、裸 import 1.3s、空闲 RSS ~51MB（负载后 300-600MB）。

| 弊端 | 对冲手段 |
|---|---|
| 打包体积（portable runtime 400-600MB） | 接受；壳更新与 runtime 更新分离，runtime 不常动 |
| 冷启动秒级 | 闪屏探活 + launchd 常驻（成本只付一次） |
| PyInstaller 对 deerflow/langchain/akshare 脆弱 | **不用 PyInstaller**，用 python-build-standalone portable Python + venv 整体打包 |
| GIL / CPU 密集卡事件循环 | 回测类任务线程池/子进程隔离 |
| 源码明文 | 自用/开源，不处理 |

**换语言不可行**：akshare 是 Python 独占（A股/港股数据无 Rust/Go/Node 等价物），DeerFlow/LangChain 是 Python 原生 agent 生态，pandas/pymupdf 同理。后端价值锁死在 Python 生态。

---

## 2. 方案 C 架构

```
StockAgent.app (Tauri 2, 纯客户端)
   │  ① 安装时：注册 launchd user service + 数据目录选择
   │  ② 运行时：webview → http://127.0.0.1:6666（业务面零改动）
   ▼
launchd (macOS) ── KeepAlive/RunAtLoad ──► Python 后端 (FastAPI+DeerFlow)
                                              │ SQLite / 盯盘调度 / 企微 channel
                                              ▼
                                     ~/Library/Application Support/StockAgent/
```

### 关键工程点（改造清单）

1. **cwd 陷阱（必改）**：`db.py:407`、`app.py:136` 均为 cwd 相对路径（`data/workbench.sqlite3`、`frontend/dist`）。需支持 `WORKBENCH_DATA_DIR` 环境变量，经 launchd plist `EnvironmentVariables` 下发。
2. **动态端口**：6666 被占则应用打不开；端口由壳/服务分配后注入。
3. **密钥入库**：`.env` 的 `OPENAI_API_KEY` 迁到设置页（`repo_config` 机制现成），首启引导填写。
4. **集成形态**：webview 直接加载后端 URL（后端已托管 `frontend/dist`），同源无 CORS，SSE 行为与浏览器一致，前端零改动。方案对比时已否决"Tauri 托管前端 + 跨源 fetch"。
5. **关窗即隐藏 + 托盘**：`CloseRequested → prevent_close + hide`，托盘 Show/Quit。

### 阶段规划

| 阶段 | 内容 | 量级 | 状态 |
|---|---|---|---|
| 0 | Tauri 壳 + 探活闪屏直连现有后端，全功能验证 | 0.5-1 天 | ✅ 完成（`desktop/`，闪屏 no-cors 探测 `/api/health` 后跳转） |
| 1 | launchd 服务注册、数据目录环境变量改造、动态端口、托盘、首启引导（见 §3.2） | 2-3 天 + 1 周 | 未开始 |
| 2 | portable Python runtime 打包 + 蓝绿更新 | ~1 周（风险集中在 akshare/deerflow 真机回归） | 未开始 |
| 3 | 签名/公证、Tauri updater；Windows（Task Scheduler/NSSM）最后 | 3-5 天 | 未开始 |

---

## 3. TeamClaw 调研沉淀

> TeamClaw v2 架构总览见其 `docs/architecture/v2.md`：客户端（Tauri/iOS/Android/扩展）+ amux daemon（ACP 管理 opencode/claude/codex 子进程）+ EMQX(MQTT 实时总线) + Supabase(权威状态)。人与 agent 在协议层等价（同一 session topic 上的 actor）；流式显示来自 MQTT delta 累积、完成态来自 Supabase，两者不混用；presence 用 MQTT retained+LWT；断线恢复靠 `last_processed_message_id` cursor。桌面 bundle 经 `tauri.conf.json externalBin` 打入 amuxd/introspect sidecar，daemon 注册为 launchd/systemd companion service 与 GUI 解耦。

### 3.1 安装引导（阶段 1 直接参照）

TeamClaw 首启为**闸门式串行流程**（`AuthGate.tsx`）：依赖检测 → 登录 → team → daemon 绑定 → workspace。本项目简化为：

```
闪屏 → [闸门1] 环境检测(doctor) → [闸门2] 数据目录选择(仅首次) → [闸门3] 服务注册+启动 → 主界面
```

四个整体平移的设计：

1. **doctor 单点判定**：前端不自己探测，全部委托一个 doctor 命令输出 JSON（runtime 装没装/服务注册没/端口/目录可写），UI 只渲染 checklist；必装项自动安装并 padding ~2.5s loading 防"闪一下"。（参照 `apps/desktop/src/commands/setup.rs` + `stores/setup.ts` + `SetupWizard.tsx`；冷启动用 localStorage 缓存"上次全满足"跳过冷 probe）
2. **先放二进制、后注册服务**：安装阶段只 copy 文件，launchd 注册推迟到配置（数据目录）完成后——避免装出没配置好的空服务。（参照 `setup.rs::install_amuxd` 与 `daemon-onboarding.ts::onboard` 的顺序）
3. **工作目录职责分离**：
   - 选择：`@tauri-apps/plugin-dialog` `open({directory:true})`，默认 `~/Library/Application Support/StockAgent`（约定优于配置）；
   - 校验：在服务端做，拒绝危险路径（文件系统根、服务状态目录内部——TeamClaw 拒 `~/.amuxd/*` 防软链循环，见 `workspace_path.rs`）；
   - 存储：**数据目录必须存壳/服务层**（launchd plist env），不能存前端 localStorage（后端启动前就要知道）；
   - **数据目录可选、服务状态目录固定**（TeamClaw `~/.amuxd` 硬编码不可选）——全可选只放大支持成本。
4. **多层自愈，UI 只在自愈失败时打断**：探活失败 → `launchctl kickstart -k`（原地重启，顺带拾取升级后二进制，刻意避开 bootout+bootstrap 竞态）→ 轮询 12×500ms → 仍失败才出修复向导（Retry/强制重置）。launchd plist 要点：`RunAtLoad`+`KeepAlive`、stdout/err 重定向到日志文件（`apps/daemon/src/service/mod.rs`）。
5. 卸载/重置：TeamClaw 分散在三处无统一入口——本项目应做统一的「重置/卸载」命令（bootout + 删 plist + 可选删数据目录）。

### 3.2 前端工程模式

**流式渲染三板斧**（对现有浏览器版即有收益，可独立于桌面化实施）：

1. rAF 批处理：SSE delta 攒 buffer，单个 `requestAnimationFrame` 每帧 flush 一次（`lib/stream-delta-buffer.ts`）；
2. 稳定段落 memo：按 `\n\n`（校验 code fence 闭合）切已完成段落为 memoized 块，只重解析增长中的尾部（`StreamMarkdown.tsx` 的 `splitStableBlocks`）；
3. 流式期跳过重高亮：代码块流式期只渲染纯 `<pre>`，闭合后才语法高亮；打字机按积压自适应速度（`useStreamRevealText.ts`）。

**桌面化专属**（随阶段 1/3）：

| 模式 | 参照 |
|---|---|
| 自绘标题栏：`titleBarStyle: Overlay` + `data-tauri-drag-region` + 68px 红绿灯 spacer | `tauri.conf.json`、`traffic-lights.tsx`、`window_chrome.rs`（cocoa 重定位红绿灯） |
| 窗口几何持久化 + 多显示器可见性校验 | `window_chrome.rs` |
| webview 崩溃自愈：定期 probe，失联 `request_restart()` | `webview_recovery.rs` |
| 更新器：启动 3s 后+每 4h 静默检查，后台下载完只弹一次"重启"，状态机 idle/checking/available/downloading/ready/error | `stores/updater.ts`、`UpdateDialog.tsx` |
| 双运行时同构：`isTauri()` 探测，桌面能力优雅降级，同一 SPA 跑浏览器与桌面 | `lib/platform.ts` |
| 主题防闪烁：模块加载时（非 React 挂载后）立即 applyTheme(localStorage) | `GeneralSection.tsx` |
| 错误边界分区：聊天面板单独包 ErrorBoundary | `components/ErrorBoundary.tsx` |

**不跟**：70+ Zustand store 碎片化（他们自己出现"孤儿 event-bus"演进债）、i18n 构建期裁剪（本项目纯中文）。

### 3.3 UI 设计

TeamClaw 有成文设计规范（其 `AGENTS.md §1`「Editorial Calm」）。最值得抄的是**规范本身**——供人和 AI 共读的设计契约。建议将以下纪律写入本项目 CLAUDE.md：

- **强调色预算**：品牌色一屏最多 2 处 + 位置白名单；想用在 success/focus/link/hover 上一律改用 ink/muted/border。本项目更严：**红/绿保留给涨跌语义**，蓝只做交互；
- **mono 纪律**：时间戳、工具参数、模型名、版本号、键盘 pill 一律 mono；本项目追加：行情数字/价格列用 `font-variant-numeric: tabular-nums`；
- **字号阶梯**绑定用途（15/13.5/13/12.5/12/11.5/11/10.5px 各有明确场景）；
- **表面语义化命名**：background→paper(卡片)→panel(侧栏)→selected(选中行) 四层 + border/border-soft 双级线条（现 `index.css` 是位置命名 bg-secondary/tertiary）；
- 圆角带语义：面板 14 / 气泡大边 16+说话侧小角 6（不对称指向发言者）/ 按钮 7-8 / chip 3-4。

交互模式（截图 `teamclaw/images/*.png`）：空会话居中标题+**建议 chips**（映射 skill：「分析持仓风险」「生成晨报」「回测策略」）；**模型 pill 嵌在输入框内**（点击切换）；设置页「网关卡片行」= 图标+名称+状态 pill+展开+文档链+开关+Start（精确匹配本项目 MCP/IM 通道/数据源列表）；设置页底部版本号+Check for updates。

### 3.4 UI 布局

**产品方向（2026-07-15 决定）：本项目转型为「聊天会话中心」**——聊天是主交互面，会话列表升为一等公民，业务页面（行情/盯盘/回测/持仓）逐步转为聊天工具卡的展开详情 + 右侧上下文面板。后端无需改动（copilot_service 的 skill/intent + 工具体系本来就是 agent-first），这是纯前端信息架构重构。TeamClaw 布局由此从"部分参考"变为**整体模板**。

现状：`index.css:233` 三栏 grid `72px 2fr 1fr`（rail/页面/Copilot 伴随面板）。

目标形态（对照 TeamClaw 四栏）：

```
72px rail │ 会话列表列(CSS 变量宽) │ 聊天主区(stacked/split 双模式) │ 右侧详情面板(可折叠)
```

- **rail**：保留，高频面板（盯盘/持仓/设置）仍可直达——聊天中心不等于删掉页面，是主次反转；
- **会话列表列**：新增（参照 `SidebarSecondColumn`），顶部仅 4 个 icon 按钮（折叠/搜索/历史/新建），空态 icon+两行灰字；
- **聊天主区**：CopilotPanel 从伴随面板提升为主区；**split 双模式**（参照 `MainContent` stacked/split + `useResizablePanels`）——左侧嵌报告/回测/行情详情（360-900px 可拖）+ 右聊天并排，AI 引用内容对话的核心场景；
- **右侧详情面板**：工具卡点开的上下文详情（行情图/盯盘规则/回测曲线），`w-72→w-0` 宽度/opacity 过渡折叠**不卸载**（SSE 流式进行中不能断渲染）；
- 面板宽度一律**像素 CSS 变量 + 自制 ResizeHandle**（~60 行，document 级 mousemove，min/max 钳制，持久化），不用弹性比例（聊天列有最佳阅读宽度 360-560px）；
- **断点降级**（`useLayoutBreakpoint` narrow/medium/wide）：窗口变窄时右栏→会话列→rail 依次收起，桌面窗口比浏览器标签更常被缩小；
- （随桌面化）顶栏 `data-tauri-drag-region` + rail 顶部红绿灯 68px spacer——overlay 标题栏不加没法拖窗口；
- 多 tab 系统（`tabs.ts`）：转型后「多股票对比会话」场景可回头参考，暂缓。

**迁移路径（建议分三步，每步可独立交付）**：
1. 四栏骨架：会话列表列 + 聊天提升主区，业务页面暂保持 rail 直达全屏形态；
2. 工具卡 → 右栏详情联动（点行情/回测卡在右栏展开）；
3. split 模式 + 页面内容组件化嵌入（报告/回测视图可作为 split 左侧嵌件）。

---

## 4. 落地优先级汇总（独立于桌面化阶段的前端改进）

| 优先级 | 项 | 触发时机 |
|---|---|---|
| P0 | 流式渲染三板斧；**聊天中心迁移第 1 步（四栏骨架：会话列表列 + 聊天主区）**；设计纪律写入 CLAUDE.md；空态建议 chips；设置页卡片行 | 随时（浏览器版即受益） |
| P1 | 迁移第 2 步（工具卡→右栏详情联动）；断点降级；顶栏拖拽区/红绿灯 spacer；表面语义化；tabular-nums；输入框模型 pill；关窗隐藏+托盘 | 桌面化阶段 1 前后 |
| P2 | 迁移第 3 步（split 模式 + 页面组件化嵌入）；浅色纸感主题（可选跟随系统）；macOS 系统强调色注入 focus ring | 聊天中心骨架稳定后 |

## 5. 参考

- TeamClaw 仓库：`https://github.com/different-ai-studio/teamclaw`（调研时为 `v2/amuxd-architecture` 分支；本地克隆在 session scratchpad，属临时目录，失效后按上述文件路径重新浅克隆即可）
- 其关键文档：`docs/architecture/v2.md`（架构入口图）、`AGENTS.md §1`（设计规范）、`docs/specs/2026-06-02-unified-install-onboarding-design.md`（安装引导设计）
- 本项目阶段 0 产物：`desktop/`（Tauri 2 工程，模板 Rust 零修改；`desktop/ui/index.html` 为探活闪屏）
