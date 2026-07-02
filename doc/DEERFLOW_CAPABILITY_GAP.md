# DeerFlow 能力差距分析

> 调研日期：2026-07-01 · 对象：本项目对 DeerFlow(ByteDance deer-flow / 已装 harness)的集成与展示情况
>
> 方法：交叉比对三份盘点 —— ①已装 harness 包(`.venv/.../deerflow/`)全量能力矩阵；②本项目 `backend/agent_runtime/` 实际集成面；③deer-flow 完整产品仓库的产品级能力。下述「未展示」结论均经代码核实。

## 一句话结论

本项目把 DeerFlow 当作**纯流式对话引擎**使用：接入了「推理 / 工具调用 / 多轮会话 / 记忆 / 护栏」这条主链，但 DeerFlow 作为「产品化 Agent 框架」的大部分能力**要么没接线、要么接了但硬编码关闭、要么后端已产出却没在前端展示**。

## 已经用起来的能力(基线)

| 能力 | 状态 | 位置 |
|---|---|---|
| 流式推理(thinking / 思维链) | ✅ 默认开 | `deerflow_client.py` `thinking_enabled=True` |
| 工具调用 + 工具卡片 | ✅ | `tool_bridge.py`(47 工具)+ 前端 tool-card |
| 多轮会话(thread checkpointer) | ✅ | SqliteSaver |
| 自动标题 / 摘要压缩 / 循环检测 / 熔断 | ✅ | `deerflow_config.py` |
| 记忆(memory,写入侧) | ✅ 配置开 | `deerflow_config.py` memory 段 |
| 护栏 guardrails(拒绝 place_real_order 等) | ✅ | guardrails 拒绝列表 |
| 8 个投研 skill | ✅ | `skill_specs.py` / `skills/custom/` |
| Web 搜索(DuckDuckGo 兜底) | ⚠️ 已注册工具，但未进 skill allowed-tools、未在 UI 暴露 | `deerflow_config.py:99-125` |

---

## A. 完全没集成(harness 有，项目没接线)

| 能力 | DeerFlow 位置 | 对投研的价值 | 成本 |
|---|---|---|---|
| **文件上传 / RAG**(PDF/Excel/Word→MD) | ✅ 已接线（2026-07-02）：`POST /api/copilot/sessions/{id}/uploads` + 输入框附件按钮；沙箱只读文件工具(ls/glob/grep/read_file)已注册进 config，UploadsMiddleware 自动注入文件清单 | ⭐⭐⭐ 上传**研报/年报/招股书/财报 PDF** 让 AI 直接读 | 已完成 |
| **Sandbox 代码执行**(Python/pandas/matplotlib) | `deerflow.sandbox`(Local/Docker/K8s)+ `data-analysis`/`chart-visualization` skills | ⭐⭐⭐ 让 AI 跑真实数据做**自定义回测/画图/因子计算**，不再只调固定工具 | 中高 |
| **多模态 / 看图**(view_image) | ✅ 已接线（2026-07-02）：上传白名单加图片(png/jpg/webp)；模型 `supports_vision` 按模型名自动判定（`WORKBENCH_AI_VISION` 可覆盖），命中后 harness 自动挂 view_image 工具+中间件；顺带修了 config 模型名与 stream 不一致导致按模型能力判定失效的 bug | ⭐⭐ 上传 **K 线截图/研报图表** 做视觉分析 | 已完成 |
| **MCP 集成** | ✅ 已接线（2026-07-02）：`/api/runtime/mcp` GET/PUT + 设置页「MCP 服务器」区块（增删/启停/stdio+sse+http）；写入 `extensions_config.json`，harness 按 mtime 自动重载工具缓存，保存后下一轮对话生效。MCP 接入后可再开 tool_search 省 prompt | ⭐⭐ 无需写代码即可接 **Wind/Choice/内部数据源/外部工具** | 已完成 |
| **可观测 Tracing**(Langfuse/LangSmith) | ✅ 复核已内置（2026-07-02）：`client.stream` 自动注入 `build_tracing_callbacks()`，纯 env 驱动——`LANGFUSE_TRACING=1`+keys 或 `LANGSMITH_TRACING=1`+key 即生效，用法已写入 `.env.example` | ⭐⭐ 排查 agent 执行链、**token 成本分析** | 已完成 |
| **报告后处理**：语音播客(TTS)/ PPT 生成 | public skills `podcast-generation` / `ppt-generation` | ⭐⭐ **语音晨报 / 投研路演 PPT**，产品差异化 | 中 |
| **ask_clarification**(反问澄清) | ✅ 已接线（2026-07-02）：工具+中间件 harness 侧本就总是挂载；补齐我方缺口——copilot_service 捕获同名 tool_result 发专用 `clarification` SSE、final 空壳用问题文本兜底，前端渲染琥珀色问题卡（下一条消息即回答） | ⭐ 股票代码/意图歧义时 AI 主动反问 | 已完成 |

## B. 已集成但硬编码关闭 / 休眠

| 能力 | 现状 | 说明 | 成本 |
|---|---|---|---|
| **子代理 subagent** | `deerflow_client.py` 硬编码 `False`；**但 8 个 subagent 配置已生成**(`deerflow_config.py::_build_subagent_configs`) | 开一个开关就能让 researcher/valuation/catalyst **并行**跑，现在串行。价值高、改动极小 | ⭐ 低 |
| **plan_mode(TodoMiddleware)** | 硬编码 `False` | 复杂多步研究的**计划审核 human-in-the-loop** | 中 |
| **web 搜索** | ✅ 复核已接线（2026-07-02）：主代理经 `get_available_tools(groups=None)` 不过滤拿到 `web_search`；全部 subagent 经 `skill_specs.extra_tools` 默认带上。DDG 无 key 兜底，配 `TAVILY_API_KEY` 自动升级并追加 `web_fetch` | 让研究突破 akshare，接**实时新闻/全网** | 已完成 |
| **tool_search** | ⚠️ 复核不适用（2026-07-02）：harness 的 tool_search **只延迟 MCP 工具**（`ToolSearchConfig` docstring），config 注册的 54 个本地工具不受影响——当前未接 MCP，开了无收益。待 MCP 集成后再开 | 47 个工具时用延迟工具搜索省 prompt | 暂不适用 |
| **记忆管理 UI** | ✅ 已接线（2026-07-02）：`/api/runtime/memory*` 路由 + 设置页 AI Tab「AI 记忆」区块（查看/添加/编辑/删除/清空；stub 模式自动隐藏） | 让用户看到 AI 记住了什么、纠偏 | 已完成 |

## C. 后端已产出、前端没友好展示 ⚠️(最划算)

这一档后端**都已经算出来并发到 SSE 了**，但前端 `CopilotStreamingMessage.tsx` 只渲染「推理阶段指示 + 工具卡片 + 最终答案」，以下字段全被丢弃：

| 字段 | 后端来源 | 现状 |
|---|---|---|
| **confidence 信心度** | `_map_final` final payload | 未渲染 |
| **counter_reasons 反方观点** | `result_normalizer` + final payload | 未渲染 ❗(已给 skill 加反方纪律，前端却不显示) |
| **token 用量 / 成本** | `copilot_cost.py` 估算 + usage | 未渲染 |
| **skill_trace 技能链路** | 事件已发，`copilot.ts` 常量已定义 | 未渲染 ❗(researcher→valuation→catalyst→risk→report 整条多智能体流水线对用户不可见) |
| **evidence_refs 引用来源** | `tool_result` / `tool_evidence_refs` | 未渲染(citation-discipline 白做) |
| **思维链** | reasoning 事件 | 只显示**最后 300 字符**，无完整可展开链 |

此外前端**没有会话历史/回放浏览器**，也**没有技能管理 UI**(只能改 `extensions_config.json` 或 Settings 的 raw JSON)。

---

## 建议优先级

### 第一梯队(低成本高回报，先做 C + B)
1. **展示 skill_trace + confidence + counter_reasons + 引用** —— 纯前端活，后端数据现成。让用户看到「多智能体在协作 + AI 的信心 + 反方 + 出处」，是投研可信度的核心，且立刻兑现前几轮对 skill 的所有升级。
2. **打开 subagent 并行** —— 一个开关，让研究类意图的多个 skill 并行，提速明显。
3. **接 web 搜索进 skill allowed-tools + Settings 配 key** —— 低成本扩大信息面。

### 第二梯队(新能力，按投研价值)
4. **文件上传 / RAG** —— 上传研报/财报 PDF 给 AI 读，投研最大缺口。
5. **Sandbox + data-analysis skill** —— AI 跑 Python 做自定义分析/画图。
6. **记忆管理 UI**、**Tracing**、**语音/PPT 报告**。

---

## 关键代码引用

| 主题 | 文件 |
|---|---|
| DeerFlow 适配器(能力开关) | `backend/agent_runtime/deerflow_client.py` |
| DeerFlow 配置生成(web 搜索 / subagent / tool_search) | `backend/agent_runtime/deerflow_config.py` |
| 工具桥接 / 注册 | `backend/agent_runtime/tool_bridge.py`、`tools.py` |
| skill 单一真相源 | `backend/agent_runtime/skill_specs.py` |
| 结果规整(confidence / counter_reasons) | `backend/agent_runtime/result_normalizer.py` |
| 成本估算 | `backend/app_services/copilot_cost.py` |
| 前端 SSE 事件常量 | `frontend/src/api/copilot.ts` |
| 前端流式渲染(展示缺口所在) | `frontend/src/components/features/CopilotStreamingMessage.tsx`、`CopilotPanel.tsx` |
| 已装 harness 全量能力 | `.venv/lib/python3.12/site-packages/deerflow/`(agents/subagents/guardrails/sandbox/mcp/uploads/tracing/memory/…) |
