# Stock Agent — 原生 iOS（SwiftUI）

纯 SwiftUI 客户端，**不是** Capacitor / WKWebView。连接你自己部署的 HTTPS 后端。

## 要求

- Mac + Xcode 16+
- Apple 账号（Personal Team 可真机调试；**远程推送需付费 Developer Program**）
- 远端已开 **HTTPS** + 环境变量 `WORKBENCH_ACCESS_TOKEN`

## 打开工程

```bash
cd mobile-native
open StockAgent.xcodeproj
```

Xcode 里选 Team 签名 → 真机或模拟器 → Run。

Bundle ID：`com.stockagent.app`

## 对接当前 ECS 部署

| 项 | 值 |
| --- | --- |
| 推荐地址 | `https://47.103.58.33`（443）或 `https://47.103.58.33:8686` |
| 协议 | HTTPS（nginx 自签证书，客户端已放行 server trust） |
| 鉴权 | Header `X-Workbench-Token`；SSE 可用 `?access_token=` |

访问令牌在服务器 `/opt/stock-agent/.env` 的 `WORKBENCH_ACCESS_TOKEN`（勿提交到 Git）。

## 使用

1. 启动后进入 **连接后端**（空地址会预填推荐 URL）
2. 填地址 + 访问令牌 → **连接**（需 health 含 `agent_runtime`）
3. 底栏：对话 / 自选 / 持仓 / 盯盘 / 设置  
   - 对话：停止 / 重试、附件上传、长回复折叠进详情、会话搜索/重命名、回答复制与分享  
   - 自选：搜索添加、左滑删除、点进标的详情（走势 / 资讯 / 财报 / 深研报告）  
   - 持仓：组合摘要，点持仓进同一套标的详情  
   - 盯盘：启停、立即评估、事件详情、跳转标的、规则启停/删除/新建涨跌幅规则、有用/无用反馈  
   - 设置：健康探测、运行状态、模型服务（连接/断开/默认模型）、AI 技能、用量费用、刷新频率、行情数据源启停与 API 凭证、研究报告、策略回测、外观主题、推送状态、交易约束  

标的详情里可点 **在对话中分析**（预填问题并切到对话 Tab）。
设置 → **切换后端** 会回到连接页。

## APNs 推送（可选）

当前 `StockAgent.entitlements` 含 `aps-environment=development`（Debug 真机）。正式发布需在 Xcode Signing 切到 production，并配置服务端证书。

要启用推送：
1. Apple Developer → Identifiers → `com.stockagent.app` → 勾选 **Push Notifications**
2. Xcode → Signing & Capabilities 确认 **Push Notifications** 已启用
3. App 连接成功后会请求通知权限并上报 device token 到 `POST /api/devices/apns`
4. 服务器配置 `APNS_KEY_ID` / `APNS_TEAM_ID` / `APNS_KEY_PATH`（`.p8`）后才会真正下发
5. 推送场景：
   - 盯盘 `high`/`medium` → IM + APNs（`kind=monitor`）
   - 定时任务**失败** → 始终推送（`kind=scheduled_task`）
   - 定时任务**成功** → 默认推送，可在设置关闭「定时任务完成通知」（`duty_completion_push`）
6. 点开定时任务通知会进入对应对话会话；无 session 时打开研究报告

## 命令行编译

```bash
cd mobile-native
xcodebuild -scheme StockAgent -destination 'generic/platform=iOS' -configuration Debug CODE_SIGNING_ALLOWED=NO build
```
