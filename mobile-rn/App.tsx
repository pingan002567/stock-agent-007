import { useEffect } from 'react';
import { AppState, Platform, useColorScheme } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import NetInfo from '@react-native-community/netinfo';
import * as Notifications from 'expo-notifications';
import * as NavigationBar from 'expo-navigation-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { setAuthFailureHandler } from './src/api/client';
import { ConnectivityBanner } from './src/components/ConnectivityBanner';
import ConnectScreen from './src/screens/ConnectScreen';
import { RootNavigator, routeFromNotification } from './src/navigation';
import { configureNotificationHandler, ensureAndroidChannel } from './src/lib/notify';
import { runPushCheckOnce } from './src/lib/pushTask';
import { ensureToolLabels } from './src/lib/toolLabels';
import { fetchSettings } from './src/api/client';
import { usePush } from './src/store/push';
import { useAppearance } from './src/store/appearance';
import { useChat } from './src/store/chat';
import { useConnection } from './src/store/connection';
import { useMonitorUnread } from './src/store/monitorUnread';
import { useTheme } from './src/store/theme';

export default function App() {
  const status = useConnection((s) => s.status);
  const hydrate = useConnection((s) => s.hydrate);
  const hydrateTheme = useTheme((s) => s.hydrate);
  const hydrateAppearance = useAppearance((s) => s.hydrate);
  const hydrateUnread = useMonitorUnread((s) => s.hydrate);
  const hydratePush = usePush((s) => s.hydrate);
  const scheme = useTheme((s) => s.scheme);
  const systemScheme = useColorScheme();
  const dark = scheme === 'dark' || (scheme === 'system' && systemScheme === 'dark');

  useEffect(() => {
    hydrate();
    hydrateTheme();
    hydrateAppearance();
    hydrateUnread();
    hydratePush();
  }, [hydrate, hydrateTheme, hydrateAppearance, hydrateUnread, hydratePush]);

  // 工具中文名：后端是唯一真源，连上后拉一次（失败则用本地静态表兜底）
  useEffect(() => {
    if (status !== 'connected') return;
    const { baseURL, token } = useConnection.getState();
    if (!baseURL) return;
    void ensureToolLabels(baseURL, token ?? '', fetchSettings);
  }, [status]);

  // 通知：前台展示策略 + 渠道 + 点击跳转（含冷启动）
  useEffect(() => {
    configureNotificationHandler();
    void ensureAndroidChannel();
    void Notifications.getLastNotificationResponseAsync().then((resp) => {
      const route = resp?.notification.request.content.data?.route;
      if (typeof route === 'string') routeFromNotification(route);
    });
    const sub = Notifications.addNotificationResponseReceivedListener((resp) => {
      const route = resp.notification.request.content.data?.route;
      if (typeof route === 'string') routeFromNotification(route);
    });
    return () => sub.remove();
  }, []);

  // 前台轮询：App 可见时每 60s 检查一次（与后台任务共用去重集合）
  useEffect(() => {
    const timer = setInterval(() => {
      if (usePush.getState().enabled && useConnection.getState().status === 'connected') {
        void runPushCheckOnce();
      }
    }, 60_000);
    return () => clearInterval(timer);
  }, []);

  // 底部系统栏（Android 导航栏）：edge-to-edge 下背景透明，
  // 只需保证系统图标与 App 明暗对比一致，否则浅色背景下会看不清
  useEffect(() => {
    if (Platform.OS !== 'android') return;
    try {
      // SDK 57 的 API：'light' = 浅色图标（配深色背景），'dark' = 深色图标（配浅色背景）
      // edge-to-edge 下导航栏背景透明，由底部 Tab 栏的底色透出，只需同步图标明暗
      NavigationBar.setStyle(dark ? 'light' : 'dark');
    } catch {
      /* 部分 ROM 不支持，忽略 */
    }
  }, [dark]);

  // 401/403 → 暴露「令牌失效」到横幅
  useEffect(() => {
    setAuthFailureHandler(() => useConnection.getState().markAuthFailed());
    return () => setAuthFailureHandler(null);
  }, []);

  // 前台恢复：App 回到前台时重挂断线遗留的流（对齐 iOS scenePhase 处理）
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active' && useConnection.getState().status === 'connected') {
        void useChat.getState().recoverOnForeground();
      }
    });
    return () => sub.remove();
  }, []);

  // 网络恢复：重新探测健康 + 重挂遗留的流
  useEffect(() => {
    let wasOffline = false;
    const unsub = NetInfo.addEventListener((state) => {
      const offline = state.isConnected === false;
      if (wasOffline && !offline && useConnection.getState().status === 'connected') {
        void useConnection.getState().reprobeHealth();
        void useChat.getState().recoverOnForeground();
      }
      wasOffline = offline;
    });
    return () => unsub();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
      <StatusBar style="auto" />
      <ConnectivityBanner />
      {status === 'connected' ? <RootNavigator /> : <ConnectScreen />}
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
