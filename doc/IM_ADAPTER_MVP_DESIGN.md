# IM 适配层 MVP 设计（本项目）

> 目标：在本项目内落一个最小可用的 IM 适配层 —— **Telegram + Slack**（无公网）、`/connect` 绑定、盯盘告警推送。
> 借鉴 deer-flow `app/channels` 的设计，但**对接本项目的嵌入式 `CopilotService`**（非 LangGraph Gateway SDK）。

## 1. 架构

```
IM 平台 ─出站连接─▶ Channel 适配器(telegram/slack) ──publish_inbound──▶ MessageBus
                                                                          │ get_inbound
                                                          ChannelManager._dispatch_loop
                                                            │ 绑定校验 → 命令 or 对话
                                                            ▼ CopilotService.create_run + stream_run（进程内）
                                                          聚合 final.conclusion → OutboundMessage
                                                                          │ publish_outbound
                                          适配器 _on_outbound → send() ───┘ 回发平台

MonitorService(high/medium 事件) ─▶ alert_sink ─▶ ChannelNotifier.push(title,text)
                                                     └─▶ 给每个已绑定 chat 发 OutboundMessage
```

- **无公网**：Telegram 长轮询、Slack Socket Mode（出站）。
- **会话映射**：`session_id = im:{channel}:{chat_id}`，直接交给 `CopilotService`（thread=session 自带多轮记忆）。`/new` 旋转后缀。
- **绑定（单用户简化）**：不照搬多租户 owner，绑定只作**白名单门禁**——`/connect <code>` 把 `(channel, chat_id)` 加入允许列表；未绑定的 chat 被拒（`require_binding` 可关）。

## 2. 文件清单（`backend/channels/`）

| 文件 | 职责 |
|---|---|
| `message_bus.py` | `InboundMessage`/`OutboundMessage` + asyncio 队列发布订阅（精简自 deer-flow） |
| `base.py` | 抽象 `Channel`(start/stop/send) + `_on_outbound` + `_pending_connect_code` |
| `binding.py` | `BindingStore`：连接码生成/消费(128bit/10min/单次) + 白名单，落 `repo` config |
| `manager.py` | dispatch loop：绑定门禁 → 命令(`/connect /new /status /help`) or 对话(CopilotService 桥接) + 每会话锁 |
| `notifier.py` | `ChannelNotifier`：线程安全 `push(title,text)`，广播给所有已绑定 chat（盯盘告警用） |
| `service.py` | 生命周期 + 从 config 构造适配器；`start()` 捕获 event loop |
| `telegram.py` | python-telegram-bot 长轮询 |
| `slack.py` | slack-sdk Socket Mode |
| `backend/api/routes_channels.py` | 生成连接码 / 列绑定 / 删绑定 / 读写 config（无前端，先 API） |
| `tests/test_channels.py` | 核心用例：FakeChannel + stub copilot 跑通 inbound→对话→outbound、绑定门禁、连接码 |

## 3. 集成点（已核对）

- `CopilotService.create_run(CopilotRequest(message, session_id, authority_level)) -> CopilotRun`
- `CopilotService.stream_run(run_id, session_id=...) -> AsyncIterator[SSEEvent]`；最终答案在 `event.type in {final,final_answer}` 的 `payload.conclusion`。
- `app.py` lifespan：在 monitor 之后 `start`/`shutdown` 时 `stop`。
- `bootstrap.create_services`：构造 `ChannelService` 注入 `AppServices`；把 `channel_service.notifier.push` 设为 `monitor_service.alert_sink`。
- `MonitorService.evaluate_one_rule`：high/medium 事件已调 `dispatch_notification`，并行调 `alert_sink`（新增可选属性）。

## 4. 依赖

新增 optional extra `[channels]`：`python-telegram-bot>=21`、`slack-sdk>=3.33`。**未安装时服务优雅降级**（该适配器跳过，核心不受影响、测试用 FakeChannel 无需 SDK）。

## 5. 配置（落 repo config，键 `channels`）

```json
{ "enabled": true, "require_binding": true,
  "telegram": {"enabled": true, "bot_token": "..."},
  "slack":    {"enabled": false, "bot_token": "xoxb-...", "app_token": "xapp-..."} }
```
env 兜底：`TELEGRAM_BOT_TOKEN` / `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`。

## 6. MVP 范围

- ✅ Telegram + Slack + **企业微信** 双向对话（接 CopilotService）
- ✅ `/connect <code>` 绑定门禁 + `/new /status /help`
- ✅ 盯盘 high/medium 告警推送到已绑定 chat
- ✅ 连接码生成 API + 绑定管理 API
- ✅ 核心单测（FakeChannel）
- ✅ 前端「IM 渠道」设置页（provider 配置 + 绑定列表 + 连接弹窗轮询）
- ⬜（暂不做）流式编辑消息（先整条发）、文件收发、钉钉/飞书/微信（base 已可扩展）

### 企业微信适配器要点
- SDK `wecom-aibot-python-sdk`（`from aibot import WSClient`）；凭证 `bot_id`+`bot_secret`；WebSocket 出站，无公网。
- 与 Telegram/Slack 不同：回复绑定到**入站 frame**——收到消息即 `reply_stream(frame, stream_id, "处理中…", False)` 保活，agent 出结果后 `reply_stream(..., True)` 收口；按 `reply_to=msgid` 存取 frame。
- 告警（无 frame）走 `send_message(chatid, {...})` 主动推送。

## 7. 交互原型

回复文案与 `manager.py` 实现一致。①IM 端已可用；②前端设置页为待实现蓝图。

### ① IM 端

**绑定流程（无公网 / 连接码）**
```
〔网页端 · IM 渠道〕 点「连接 Telegram」
  ┌───────────────────────────────────────┐
  │  连接码   Xk9_pL2mQ7v8…                 │
  │  有效期   ⏱ 09:58 倒计时（10 分钟）     │
  │  下一步   在 Bot 里发送                 │
  │           /connect Xk9_pL2mQ7v8…        │
  │           或〔在 Telegram 打开〕(深链)   │
  │  状态     ⏳ 等待绑定…                   │
  └───────────────────────────────────────┘
〔Telegram · 你的 Bot〕
  你 ▸  /connect Xk9_pL2mQ7v8…       (深链则自动发 /start <code>)
  🤖 ▸  ✅ 绑定成功！现在可以直接对话了。发送 /help 查看命令。
```

**对话**
```
  你 ▸  分析一下贵州茅台
  🤖 ▸  贵州茅台（600519）当前判断：观察仓
        评分 72/100 · 风险中 · 置信度 中
        • 白酒龙头，行业地位稳固
        • 估值偏高，短期需等回调
        建议：观察为主。
        —— 仅供研究，不构成投资建议
        （走 CopilotService，多轮记忆按本会话延续）
```

**命令**
```
  你 ▸ /help     🤖 ▸ 可用命令：/connect <code> /new /status /help …
  你 ▸ /new      🤖 ▸ 🆕 已开启新对话。
  你 ▸ /status   🤖 ▸ 绑定：已绑定 / 会话：im:telegram:12345:1
```

**盯盘告警（后台主动推送到已绑定 chat）**
```
  🤖 ▸ 🔴 盯盘告警 · 贵州茅台 跌破20日均线
       price < MA20
  🤖 ▸ 🟠 盯盘告警 · 腾讯控股 成交量异常放大 3.2x
```

**边界态**
```
  陌生人 ▸ 你好  → 🤖 本会话未绑定。请在网页端「IM 渠道」生成连接码…
  你（连发） → 🤖 ⏳ 上一条还在处理中，请稍候。
```

### ② 前端「IM 渠道」设置页（待实现蓝图）
```
┌─ IM 渠道 ─────────────────────────────────────────────┐
│ 在 IM 里直接与投研助手对话，并接收盯盘告警。全程无需公网。 │
│ ┌─ Telegram ─────────────────── ● 已配置 · 运行中 ──┐ │
│ │ Bot Token  ********                     〔编辑〕   │ │
│ │ 要求绑定   〔✓〕   〔 连接 〕 〔 测试连通 〕        │ │
│ └────────────────────────────────────────────────────┘ │
│ ┌─ Slack ────────────────────────── ○ 未配置 ──────┐ │
│ │ Bot Token 〔xoxb-…〕  App Token 〔xapp-…〕 〔保存〕 │ │
│ └────────────────────────────────────────────────────┘ │
│ ＋ 钉钉 / 飞书 / 企微（后续）                            │
│ 已绑定会话                                             │
│ ┌────────────────────────────────────────────────────┐ │
│ │ telegram · chat 12345 · u1   绑定于 06-29  〔解绑〕 │ │
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
〔连接弹窗〕连接码 + 倒计时 + /connect 提示 + 深链；每 2s 轮询 /bindings 直到 connected。
```

**对应 API（已实现）**：`POST /connect-code`、`GET /bindings`、`DELETE /bindings/{ch}/{id}`、`GET|POST /config`(密钥打码)、`GET /status`（均挂 `/api/channels`）。
