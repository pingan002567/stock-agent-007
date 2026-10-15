# Stock Agent — Android（React Native + Expo）

M0 骨架：连接后端 + 健康探测 + 一条消息的流式输出（SSE 最小闭环）。

技术选型见仓库根 `doc/ANDROID_CLIENT_TECH_SELECTION.md`。

## 安装与运行

```bash
cd mobile-rn
npm install
npx expo install expo-secure-store
npm install zustand

npm run android      # 需要 Android 模拟器 / 真机（development build）
# 或
npx expo prebuild -p android   # 生成 android/ 原生工程后，用 Android Studio 打开
```

> 本工程需要 **development build**（非 Expo Go）：接个推原生 SDK、自签证书信任、
> 通知权限都依赖原生层，Expo Go 装不下。

## 连接后端

启动后进入「连接后端」，填地址 + 访问令牌（`WORKBENCH_ACCESS_TOKEN`），连接成功后
health 校验含 `agent_runtime` 即进入对话页。地址需自行填写（不在代码里预置服务器地址）。

## 网络与自签证书

由 `plugins/with-network-security.js` 注入 Android 的 `network_security_config`：

- 放行明文 `http://`（`cleartextTrafficPermitted=true`）；
- 信任「系统 + 用户」CA。

自签 HTTPS 二选一：

1. 把服务器 CA 安装为设备「用户 CA」（已受信任）；
2. 把 CA 打进 `res/raw` 并在 xml 里加 `<certificates src="@raw/ca"/>`（更严谨，发布前应这样做）。

⚠️ 不要在生产 release 里保留全局 trust-all。iOS 侧当前用 `NSAllowsArbitraryLoads`
（对齐 iOS 原生端的宽容行为），上架前应收敛为按域名 ATS 例外。

## 结构

```
App.tsx                        连接门（连接页 / 对话页）
src/api/client.ts              REST（X-Workbench-Token 头）
src/api/sse.ts                 SSE 流式解析
src/api/parse.ts               事件归约（partial/final）
src/store/token.ts             expo-secure-store 令牌持久化
src/store/connection.ts        zustand 连接状态
src/screens/ConnectScreen.tsx  连接页
src/screens/ChatScreen.tsx     对话页（M0 最小闭环）
plugins/with-network-security.js
```
