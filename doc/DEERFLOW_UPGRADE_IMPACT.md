# DeerFlow 升级影响评估

> 调研时间锚点：locked `162fb21`（2026-05-27）→ 当前 main `9654ba2`（2026-06-28）
> 跨度：约 1 个月、238 commits（其中 **113 个动到 harness 包**），期间出了 `v2.0.0-rc0/rc1` 标签。
> 结论：**对本项目低风险**，本项目用到的公开接口全部稳定。

## 1. 本项目对 DeerFlow 的耦合面

得益于版权安全适配器（`DeerFlowClientAdapter`），耦合面很窄：

- import：仅 `deerflow.client.DeerFlowClient` + `deerflow.subagents.config.SubagentConfig`
- 间接耦合：`deerflow_config.py` 生成的 config dict（14 个 section）+ 类路径字符串 + 流式事件形态

## 2. 逐项核对（locked vs current main）

| 耦合点 | 结果 |
|---|---|
| `DeerFlowClient` 全部公开方法 | ✅ 完全一致（仅行号位移）|
| `DeerFlowClient.__init__` / `stream()` 签名 | ✅ 完全一致（含 `recursion_limit` 等 kwargs）|
| `SubagentConfig` 字段 | ✅ 完全一致（仅 docstring 改）|
| `deerflow.sandbox.local:LocalSandboxProvider` / `guardrails.builtin:AllowlistProvider` | ✅ 原路径仍在 |
| 社区工具 `ddg_search/serper/tavily` 路径 | ✅ 仍在（brave/searxng/browserless 等为新增）|
| 生成 config 的 14 个 section（models…guardrails）| ✅ 全部仍存在 |
| `AppConfig` 未知键 | ✅ `extra="allow"`，向前兼容 |
| harness 依赖下限（langchain1.2.15 / langgraph1.1.9 / pydantic2.12.5）| ✅ 未变 |

**净变化全是加法**：新搜索源（brave/searxng/browserless/fastcrw/groundroute）、`persistence/channel_connections`（IM 特性）、`tui/`、新 config 段（`token_budget / tool_output / suggestions / channel_connections / auth`，均带默认值可选）。`app_config.py` +174 行，确认无项目依赖的 section 被删/改名。

## 3. 残留风险（静态 diff 证明不了的）

1. **传递依赖漂移（主要风险）**：harness 用 `>=` 下限，`uv lock --upgrade` 会把 langchain/langgraph 重解析到更新补丁版。这俩迭代快、行为可能微变——但属任何 re-lock 的通病，非本次特有。
2. **内核行为变化（113 commits）**：中间件（loop detection / summarization / safety）、流式事件细节可能变。API 稳但运行时行为可能不同。`DeerFlowEventMapper` 防御式消费 dict，大概率无碍，但**必须真实模型多轮复验**（回放过滤 + 多轮记忆）。

## 4. 安全升级步骤

```bash
git checkout -b chore/bump-deerflow
uv lock --upgrade-package deerflow-harness     # 重解析到当前 main
uv sync --extra test
uv run --extra test pytest                     # 全量
uv run pytest -m deerflow                       # 嵌入式真实 smoke
python scripts/deerflow_smoke.py && python scripts/closed_loop_smoke.py
# 关键：direct 模式真实模型多轮对话，复验回放/记忆
```

## 实测结果（2026-06-28 在本机执行）

`uv lock --upgrade-package deerflow-harness` 成功把 harness `162fb21 (v0.1.0)` → `9654ba2 (v2.1.0)`，传递依赖变动：
`cryptography 46.0.7→49.0.0`、`starlette 1.0.0→1.3.1`、`langgraph-api 0.8.7→0.10.0`、`langgraph-runtime-inmem 0.28.1→0.30.0`、`grpcio 1.78→1.80`、`msal 1.36→1.37`（langchain/langgraph 核心未变）。

**但 `uv sync` 失败 —— 环境阻塞，非代码问题：**
- 新 harness v2.1.0 要求 `cryptography>=48.0.1`（为 channel_credentials 的 Fernet 加密）。
- `cryptography 49.0.0` 在本机**无可用 wheel**，只能从源码用 Rust+OpenSSL 编译。
- 本机是 **Apple Silicon 上跑的 x86_64(Intel) Python**（`platform.machine()=x86_64`），新版 cryptography 已不再发 Intel-macOS wheel；x86_64 源码编译又缺 x86_64 OpenSSL（补了 `rustup target add x86_64-apple-darwin` 仍卡在 `openssl-sys` 找不到 OpenSSL）。

### 解决：迁移到原生 arm64（已完成）

根因是**本机工具链全是 Intel/Rosetta**（uv/brew/python 均 x86_64），新 cryptography 不再发 Intel-macOS wheel。又因 `wanhui.zhang` **无 sudo 权限**，arm64 Homebrew 装不了，最终走"**独立 arm64 uv**"路径（无需 sudo）：

```bash
# 1) 装 arm64 uv 到 ~/.local/bin（无 sudo），自动加入 PATH 最前
curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$HOME/.local/bin" sh
# 2) arm64 uv 装 arm64 Python 3.12
uv python install 3.12
# 3) 升级锁定 + 用 arm64 重建 venv + 安装
uv lock --upgrade-package deerflow-harness
uv venv --clear --python cpython-3.12.13-macos-aarch64-none
uv sync --extra test
```

**结果（验证通过）：**
- venv = arm64，`cryptography 49.0.0` 走 wheel **零编译**，`deerflow v2.1.0`（含 `channel_connections`）。
- 默认 `uv` 已是 arm64（`~/.local/bin/uv` 在 PATH 最前），`dev.sh`/`start.sh` 的 `uv run` 自动用 arm64，无需改 PATH。
- 导入全过；`test_copilot_*`(24) + `test_deerflow_adapter`(13) 通过；`test_services`(52 passed，仅 8 个 akshare 未装的旧失败，与升级无关) —— **零新增回归**。

**遗留：**
- starlette 1.0.0→1.3.1 引入 deprecation 警告（`Using httpx with starlette.testclient is deprecated; install httpx2`），仅告警。
- **需重启后端**（当前进程仍是旧 x86_64 + 旧代码）；重启后即原生 arm64 + 新 harness。
- **建议重启后用真实模型跑一轮多轮对话**，复验回放过滤/多轮记忆（113 个 harness commit 改了内核行为，API 稳但运行时行为需实测）。
- `rustup target add x86_64-apple-darwin` 是早先尝试 x86_64 编译时加的，现已不需要，可 `rustup target remove x86_64-apple-darwin` 撤销。

## 5. 顺带建议

- pyproject 现 pin `rev=main`（不可复现，每次 re-lock 跳最新）。已有 `v2.0.0-rc0/rc1` 标签，建议**改 pin 到具体 tag/commit**，使构建可复现、升级可控。
- 升级会顺带把 `channel_connections` 持久化 + config 带进来，为将来 IM 渠道铺路（适配器层仍需自建，见 [[DEERFLOW_IM_CHANNELS]]）。
