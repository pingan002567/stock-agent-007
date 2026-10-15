# IM 渠道集成规划

## 一、目标

将 DeerFlow 的 IM 渠道能力（飞书、企业微信、钉钉等）集成到 stock-agent 项目，实现：
- 通过 IM 发送股票查询指令
- 通过 IM 接收盯盘告警
- 通过 IM 进行 AI 对话
- 通过 IM 接收报告推送

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        IM 渠道层                                 │
├─────────────────────────────────────────────────────────────────┤
│  飞书    │  企业微信  │  钉钉   │  微信   │  Telegram │  Slack  │
└────┬───────────┬──────────┬──────────┬──────────┬───────────┘
     │           │          │          │          │
     ▼           ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Channel Gateway (新增)                        │
│  - 消息路由                                                     │
│  - 用户映射                                                     │
│  - 权限验证                                                     │
│  - 消息格式转换                                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CopilotService (现有)                        │
│  - 意图识别                                                     │
│  - 工具调用                                                     │
│  - AI 对话                                                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    业务服务层 (现有)                             │
│  - 股票查询  - 盯盘监控  - 报告生成  - 风险分析               │
└─────────────────────────────────────────────────────────────────┘
```

## 三、实施计划

### 阶段一：基础框架 (1-2天)

#### 1.1 创建渠道配置模块

```
backend/channels/
├── __init__.py
├── config.py              # 渠道配置
├── gateway.py             # 渠道网关
├── message_router.py      # 消息路由
├── user_mapper.py         # 用户映射
├── adapters/
│   ├── __init__.py
│   ├── base.py           # 基础适配器
│   ├── feishu.py         # 飞书适配器
│   ├── wecom.py          # 企业微信适配器
│   ├── dingtalk.py       # 钉钉适配器
│   └── wechat.py         # 微信适配器
```

#### 1.2 渠道配置文件

```yaml
# config.yaml
channels:
  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    webhook_url: /api/channels/feishu/webhook
    
  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET
    
  dingtalk:
    enabled: true
    client_id: $DINGTALK_CLIENT_ID
    client_secret: $DINGTALK_CLIENT_SECRET
```

### 阶段二：飞书集成 (2-3天)

#### 2.1 飞书应用配置

1. 在飞书开放平台创建应用
2. 启用机器人能力
3. 配置权限和事件订阅
4. 获取 App ID 和 App Secret

#### 2.2 飞书适配器实现

```python
# backend/channels/adapters/feishu.py
class FeishuAdapter:
    """飞书渠道适配器"""
    
    async def handle_message(self, event: dict):
        """处理飞书消息"""
        user_id = event["sender"]["sender_id"]["open_id"]
        message = event["message"]["content"]
        
        # 转换为内部消息格式
        internal_msg = self._convert_message(message)
        
        # 调用 CopilotService
        response = await self.copilot_service.process(
            user_id=user_id,
            message=internal_msg
        )
        
        # 发送回复
        await self._send_reply(user_id, response)
    
    async def send_notification(self, user_id: str, content: str):
        """发送通知消息"""
        # 调用飞书 API 发送消息
        pass
```

#### 2.3 API 路由

```python
# backend/api/routes_channels.py
@router.post("/api/channels/feishu/webhook")
async def feishu_webhook(request: Request):
    """飞书 webhook 回调"""
    payload = await request.json()
    return await feishu_adapter.handle_webhook(payload)

@router.post("/api/channels/feishu/event")
async def feishu_event(request: Request):
    """飞书事件回调"""
    payload = await request.json()
    return await feishu_adapter.handle_event(payload)
```

### 阶段三：企业微信集成 (2-3天)

#### 3.1 企业微信应用配置

1. 在企业微信管理后台创建应用
2. 配置可信域名
3. 获取 Bot ID 和 Bot Secret

#### 3.2 企业微信适配器实现

```python
# backend/channels/adapters/wecom.py
class WeComAdapter:
    """企业微信渠道适配器"""
    
    async def handle_message(self, message: dict):
        """处理企业微信消息"""
        pass
    
    async def send_notification(self, user_id: str, content: str):
        """发送通知消息"""
        pass
```

### 阶段四：钉钉集成 (2-3天)

#### 4.1 钉钉应用配置

1. 在钉钉开发者后台创建应用
2. 启用机器人能力
3. 配置消息接收模式（Stream 模式）

#### 4.2 钉钉适配器实现

```python
# backend/channels/adapters/dingtalk.py
class DingTalkAdapter:
    """钉钉渠道适配器"""
    
    async def handle_message(self, message: dict):
        """处理钉钉消息"""
        pass
    
    async def send_notification(self, user_id: str, content: str):
        """发送通知消息"""
        pass
```

### 阶段五：业务集成 (3-5天)

#### 5.1 盯盘告警推送

```python
# backend/app_services/monitor_service.py
class MonitorService:
    async def _send_alert(self, event: MonitorEvent):
        """发送盯盘告警到 IM 渠道"""
        if self.channel_gateway:
            await self.channel_gateway.broadcast(
                channel="feishu",
                message=f"盯盘告警: {event.title}"
            )
```

#### 5.2 报告推送

```python
# backend/app_services/report_service.py
class ReportService:
    async def _push_report(self, report: Report):
        """推送报告到 IM 渠道"""
        if self.channel_gateway:
            await self.channel_gateway.send_to_user(
                user_id=report.user_id,
                message=f"报告已生成: {report.title}"
            )
```

#### 5.3 股票查询

```python
# 通过 IM 查询股票示例
# 用户发送: "查一下比亚迪"
# AI 回复: "比亚迪 (002594) 当前价格 285.50，涨幅 +1.25%"
```

### 阶段六：前端配置页面 (1-2天)

#### 6.1 渠道配置页面

```tsx
// frontend/src/pages/Channels.tsx
export default function Channels() {
  return (
    <PageContainer>
      <div className="page-stack">
        <h1>IM 渠道配置</h1>
        
        {/* 飞书配置 */}
        <ChannelCard 
          name="飞书"
          icon="🐦"
          enabled={true}
          onToggle={() => {}}
        />
        
        {/* 企业微信配置 */}
        <ChannelCard 
          name="企业微信"
          icon="💼"
          enabled={false}
          onToggle={() => {}}
        />
        
        {/* 钉钉配置 */}
        <ChannelCard 
          name="钉钉"
          icon="🔔"
          enabled={false}
          onToggle={() => {}}
        />
      </div>
    </PageContainer>
  );
}
```

## 四、数据模型

### 4.1 渠道配置表

```sql
CREATE TABLE channel_config (
    channel_id TEXT PRIMARY KEY,
    channel_type TEXT NOT NULL,  -- feishu, wecom, dingtalk
    enabled BOOLEAN DEFAULT FALSE,
    config JSON NOT NULL,        -- 渠道特定配置
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 4.2 用户映射表

```sql
CREATE TABLE channel_user_mapping (
    mapping_id TEXT PRIMARY KEY,
    channel_type TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,  -- IM 用户 ID
    internal_user_id TEXT NOT NULL, -- 内部用户 ID
    created_at TIMESTAMP
);
```

### 4.3 消息记录表

```sql
CREATE TABLE channel_messages (
    message_id TEXT PRIMARY KEY,
    channel_type TEXT NOT NULL,
    direction TEXT NOT NULL,      -- inbound, outbound
    channel_user_id TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMP
);
```

## 五、配置示例

### 5.1 .env 文件

```env
# 飞书
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret

# 企业微信
WECOM_BOT_ID=your_bot_id
WECOM_BOT_SECRET=your_bot_secret

# 钉钉
DINGTALK_CLIENT_ID=your_client_id
DINGTALK_CLIENT_SECRET=your_client_secret
```

### 5.2 config.yaml

```yaml
channels:
  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    
  wecom:
    enabled: false
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET
    
  dingtalk:
    enabled: false
    client_id: $DINGTALK_CLIENT_ID
    client_secret: $DINGTALK_CLIENT_SECRET
```

## 六、使用场景

### 6.1 股票查询

```
用户: 查一下比亚迪
AI: 比亚迪 (002594)
    当前价格: ¥285.50
    涨跌幅: +1.25%
    市值: 8,500亿
    行业: 新能源汽车
```

### 6.2 盯盘告警

```
系统: ⚠️ 盯盘告警
      比亚迪 (002594) 触发单日跌幅超过 3%
      当前跌幅: -3.25%
      建议关注风险
```

### 6.3 报告推送

```
系统: 📊 报告已生成
      比亚迪深研报告已生成
      点击查看详情: http://localhost:5173/reports/xxx
```

### 6.4 风险提醒

```
系统: ⚠️ 风险提醒
      您的持仓中比亚迪权重达到 18%，超过单票上限 15%
      建议适当减仓
```

## 七、依赖项

### 7.1 Python 依赖

```toml
# pyproject.toml
[project.optional-dependencies]
channels = [
    "lark-oapi>=1.0.0",      # 飞书 SDK
    "wecom-aibot-python-sdk", # 企业微信 SDK
    "alibabacloud-dingtalk",  # 钉钉 SDK
]
```

### 7.2 安装命令

```bash
uv pip install -e ".[channels]"
```

## 八、测试计划

### 8.1 单元测试

- 渠道适配器测试
- 消息路由测试
- 用户映射测试

### 8.2 集成测试

- 飞书消息收发测试
- 企业微信消息收发测试
- 钉钉消息收发测试

### 8.3 端到端测试

- 完整业务流程测试
- 多渠道并发测试

## 九、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| IM API 限制 | 消息发送失败 | 实现重试机制和降级策略 |
| 用户隐私 | 数据泄露 | 加密存储用户映射 |
| 消息延迟 | 用户体验差 | 异步处理，设置超时 |
| 费用超支 | 成本增加 | 设置消息配额和预算告警 |

## 十、时间估算

| 阶段 | 任务 | 时间 |
|------|------|------|
| 1 | 基础框架 | 1-2天 |
| 2 | 飞书集成 | 2-3天 |
| 3 | 企业微信集成 | 2-3天 |
| 4 | 钉钉集成 | 2-3天 |
| 5 | 业务集成 | 3-5天 |
| 6 | 前端配置页面 | 1-2天 |
| **总计** | | **11-18天** |

## 十一、优先级建议

### P0 (必须)
- 飞书集成（国内最常用）

### P1 (重要)
- 企业微信集成（企业用户）
- 盯盘告警推送

### P2 (可选)
- 钉钉集成
- 微信集成
- 报告推送

### P3 (未来)
- Telegram
- Slack
