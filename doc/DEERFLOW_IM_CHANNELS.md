# DeerFlow IM 渠道实现分析

> 调研对象：`bytedance/deer-flow` @ `9654ba2c13e97aadd14af5af2bb662fd885fae2a`（2026-06-28）
> 结论先行：deer-flow **主仓**有一套生产级、覆盖 7 个平台、**全程无需公网入口**的 IM 渠道系统（约 9.5k LOC，位于 `backend/app/channels/`），外加完整的多用户绑定 + 凭证加密体系。本项目当前安装的 `deerflow-harness` 旧版**不含**该特性，且适配器层属于 Gateway 应用、不随 harness 包安装。

## 1. 它在哪、本项目为什么没看到

| 位置 | 内容 | 本项目状态 |
|---|---|---|
| `backend/app/channels/*`（Gateway 应用层） | 7 个适配器 + MessageBus + ChannelManager | ❌ 不随 `harness` 包安装 |
| `backend/packages/harness/deerflow/persistence/channel_connections/` | 绑定/会话/凭证持久化 | ❌ 安装的 harness 旧版**缺失** |
| `backend/packages/harness/deerflow/config/channel_connections_config.py` | `channel_connections.*` 配置 | ❌ 安装的 harness 旧版**缺失** |

> 即：安装的 `deerflow-harness`（pin `@main` 的旧快照）早于该特性；适配器代码在 Gateway app 里，根本不在 harness 包内。

## 2. 总体架构

```
IM 平台 ──(出站长连接/轮询)──▶ Channel 适配器(7)
                                   │ publish_inbound
                                   ▼
                         MessageBus (asyncio 队列 + 发布订阅)
                                   │ get_inbound
                                   ▼
        ChannelManager._dispatch_loop ──▶ LangGraph SDK client.runs.stream()
        (semaphore=5, 去重, 每会话锁)        (跑 Gateway 上的 agent)
                                   │ publish_outbound
                                   ▼
                  Channel._on_outbound → send() → 回发平台
```

- **`base.py::Channel`** 抽象基类：子类只实现 `start/stop/send`；基类给 `_send_with_retry`(指数退避)、`_pending_connect_code`(绑定码先于黑白名单)、`_on_outbound`(只处理发给自己的消息)、`receive_file`(可选下载附件到沙箱)。
- **`message_bus.py`**：`InboundMessage`/`OutboundMessage` + 一个 `asyncio.Queue`，解耦适配器与调度器。
- **`manager.py`(1648 LOC)**：核心调度器。消费入站 → 去重(10min/4096 LRU) → 每会话创建锁(防同聊天并发建多 thread) → IM 会话↔thread 映射 → 调 LangGraph `runs.stream/wait` → 流式事件聚合成出站(1s 或 60 字符节流) → clarification 挂起态。**注意它通过 LangGraph SDK 连 Gateway**，不是嵌入式 client。
- **`service.py`**：生命周期 + 从 `config.yaml channels.*` 反射构造适配器 + 运行时配置合并。

## 3. 七个适配器：传输方式（全部无公网入口）

核心结论——**没有任何一个用公网 webhook/回调**，全是出站连接：

| 平台 | SDK | 入站传输 | 凭证 | 流式 |
|---|---|---|---|---|
| Telegram | python-telegram-bot | **长轮询** getUpdates(独立线程+loop) | `bot_token` | 编辑消息 in-place |
| Slack | slack-sdk | **Socket Mode** WebSocket | `bot_token`(xoxb)+`app_token`(xapp) | emoji 反应态 |
| Discord | discord.py | **Gateway** WebSocket | `bot_token` | 否(2000字分片) |
| 飞书/Lark | lark-oapi | **长连接** ws.Client | `app_id`+`app_secret` | 交互卡片更新 |
| 钉钉 | dingtalk-stream | **Stream** WebSocket | `client_id`+`client_secret` | AI 卡片流式 |
| 企业微信 | wecom-aibot-python-sdk | **WebSocket** WSClient | `bot_id`+`bot_secret` | reply_stream |
| 微信 | 无(裸 httpx) | **长轮询** + **扫码登录** | `bot_token` 或 QR | 否 |

实现细节：
- **飞书**绕坑：lark-oapi import 时缓存 event loop，与 uvloop 冲突 → 专门起线程 `new_event_loop()` 并 patch `lark_oapi.ws.client.loop` 再 start。
- **钉钉**用 AI 卡片做流式，按 P2P/群聊双路由(群→`groupMessages/send`，P2P→`oToMessages/batchSend`)，access_token 自动刷新(300s 余量)。
- **微信**(1444 行)最复杂：无 SDK，自实现**扫码登录**(QR 打到 stderr→轮询 `get_qrcode_status` 到 confirmed→拿 bot_token)，token 落 `wechat-auth.json`(0600)；附件 **AES-128-ECB** 解密 CDN 下载。
- 多数适配器用 `asyncio.run_coroutine_threadsafe()` 把 SDK 线程收到的消息搬回主 loop。

## 4. 用户绑定系统（无 OAuth 回调）

**连接码流程：**
1. 浏览器点"连接 Slack" → `POST /api/channels/slack/connect` → 生成 **128-bit 随机码**(`secrets.token_urlsafe(16)`)，存 `channel_oauth_states`，**10 分钟过期、单次使用**，每用户每平台最多 5 个待用码。
2. UI 提示 `Send /connect <code> to the bot`（Telegram 用深链 `t.me/<bot>?start=<code>`）。
3. 机器人收到 `/connect <code>` → `consume_oauth_state()`（SHA256 哈希 + 条件 UPDATE 翻 `consumed_at`，保证只有一个并发消费者成功）→ 拿 owner_user_id。
4. `upsert_connection()` 建绑定。

**关键安全设计：**
- **绑定码先于 `allowed_users` 黑白名单消费**：新用户(机器人没见过)也能完成首次绑定。
- **DB 层强制"一个外部身份至多一个活跃 owner"**：`channel_connections` 部分唯一索引 `UNIQUE(provider, external_account_id, workspace_id) WHERE status != 'revoked'`；抢绑时先 revoke 旧 owner 再插新行，配 3 次 `IntegrityError` 重试——竞态在 DB 层消灭，"最后绑定者赢"。
- **凭证加密**：`channel_credentials` 用 **Fernet**(AES-128-CBC+HMAC)，key 由 `CHANNEL_CREDENTIALS_KEY` 派生，带 `fernet:v1:` 版本前缀；解不开当"不可用"而非用损坏密钥。
- 4 张表：`channel_connections`(绑定) / `channel_oauth_states`(连接码) / `channel_conversations`(IM 会话↔thread 映射，按 connection 隔离) / `channel_credentials`(加密 token)。

**运行时配置**：bot 密钥可来自 `config.yaml channels.*` 或浏览器设置页(落 `runtime-config.json` 0600 明文，仅本地可信场景)；改密钥 API 需 admin，响应里密码字段打码。

## 5. 与本项目的关系（落地判断）

1. **安装的 harness 太旧**：没有 `channel_connections` 持久化与 config，要用得先升级 `deerflow-harness`。
2. **适配器层不随包安装**：`backend/app/channels/*` 属 deer-flow 的 Gateway 应用，需 vendoring 或重写。
3. **架构差异关键**：deer-flow 的 ChannelManager 通过 **LangGraph SDK 连 Gateway** 跑 agent；本项目走**嵌入式 `DeerFlowClient`** + 自己的 `CopilotService`。**不能直接搬**，但**可照搬设计**：`MessageBus` + 适配器(start/stop/send) + 每会话锁 + 绑定码，把 manager 里 `client.runs.stream` 换成 `CopilotService.stream`。
4. 可直接借鉴的高质量点：附件下载到沙箱、流式编辑消息、Fernet 凭证加密、连接码 DB 竞态处理、绑定码先于黑白名单。

## 6. 建议落地路径（若要做）

- 在 `backend/` 新建 `channels/` 子层：`base.py`(start/stop/send) + `message_bus.py` + `manager.py`(把 agent 调用换成 `CopilotService.stream`，thread_id=该 IM 会话)。
- 起步两三家**无公网**平台：**Telegram(最简单/长轮询)** + **钉钉 Stream / Slack Socket Mode**(国内外各一)。
- 复用一个出站 `Notifier` 做盯盘告警 + 报告推送（扩展现有 `monitor_notifier.py`）。
- 绑定/多用户对单用户本地应用可简化：固定映射到本地默认用户即可，不必照搬整套 `channel_connections`。

## 7. 能力面（用户侧能做什么）

DeerFlow 的 IM 不是告警推送，而是把整个 agent 运行时**双向**接到 IM：

| 能力 | 说明 |
|---|---|
| 双向对话 | IM 里直接和 agent 聊；每个 IM 会话映射一个 thread（多轮记忆） |
| 流式回复 | Telegram 编辑消息、飞书/钉钉 AI 卡片、企微 reply_stream、Slack emoji 态 |
| 文件收发 | 收：飞书/企微/微信下载附件→沙箱→喂模型；发：agent 产物上传回 IM |
| 命令集 | `/bootstrap /new /status /models /memory /help` + `/<skill> <task>` |
| 澄清回合 | agent 调 `ask_clarification` → IM 标记"等待澄清"，用户回答续同一 thread |
| 多用户绑定 | 浏览器生成连接码 → IM 里 `/connect <code>` 绑定身份 |

**命令集**（`manager.py::_handle_command`）：`/bootstrap`(启用 agent 自配置)、`/new`(新 thread)、`/status`(当前 thread)、`/models`、`/memory`、`/help`、`/<skill> <task>`(激活技能一回合)；`/connect <code>`（Telegram `/start <code>`）在适配器层先于黑白名单消费。

**开启方式**：Gateway lifespan 启动时若 `channels.*` 有配置则 `start_channel_service()`；前端设置页填密钥、点连接→开深链/显示 `/connect <code>`→每 2s 轮询 `/connections` 直到 connected（600s 窗口）。

**能力边界**：纯出站无公网回调；流式非全平台（Discord/微信整条发）；多用户绑定对单用户偏重；微信附件 AES-128-ECB（弱）；运行时凭证 `runtime-config.json`(0600 明文)。
