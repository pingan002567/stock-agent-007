# Stock Agent — 原生 iOS（SwiftUI）

纯 SwiftUI 客户端，**不是** Capacitor / WKWebView。连接你自己部署的 HTTPS 后端。

## 要求

- Mac + Xcode 16+
- Apple 账号（Personal Team 可真机调试；TestFlight 需付费 Developer Program）
- 远端已开 HTTPS + `WORKBENCH_ACCESS_TOKEN`

## 打开工程

```bash
cd mobile-native
open StockAgent.xcodeproj
```

Xcode 里选 Team 签名 → 真机或模拟器 → Run。

Bundle ID：`com.stockagent.app`

## 使用

1. 启动后进入 **连接后端**（不会自动连接）
2. 填地址（例：`https://47.103.58.33:8686`）和访问令牌
3. 点 **连接**
4. 底栏：对话 / 自选 / 持仓 / 盯盘 / 设置

自签证书：App 内 `URLSession` 对 server trust 放行（个人实机）。有正式证书后可收紧 [`TrustingURLSessionDelegate`](StockAgent/Networking/APIClient.swift)。

设置 → **切换后端** 会回到连接页；凭据仍保留在输入框，需再点连接。

## 第一期范围

- 主动连接 + 健康检查（需 `agent_runtime`）
- 会话列表、流式对话（SSE）
- 自选 / 持仓 / 盯盘列表
- 设置与切换后端

未包含：附件上传、研究/策略/回测全页、推送。

## 命令行编译（可选）

```bash
cd mobile-native
xcodebuild -scheme StockAgent -destination 'generic/platform=iOS' -configuration Debug CODE_SIGNING_ALLOWED=NO build
```
