import {
  createNavigationContainerRef,
  DarkTheme,
  DefaultTheme,
  NavigationContainer,
  type NavigatorScreenParams,
  type Theme,
} from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StyleSheet, useColorScheme } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import ChatScreen from './screens/ChatScreen';
import DataSourcesScreen from './screens/DataSourcesScreen';
import HoldingsScreen from './screens/HoldingsScreen';
import ModelServiceScreen from './screens/ModelServiceScreen';
import MonitorEventDetailScreen from './screens/MonitorEventDetailScreen';
import MonitorScreen from './screens/MonitorScreen';
import ReportDetailScreen from './screens/ReportDetailScreen';
import ReportsScreen from './screens/ReportsScreen';
import RuntimeScreen from './screens/RuntimeScreen';
import ScheduledTasksScreen from './screens/ScheduledTasksScreen';
import SettingsScreen from './screens/SettingsScreen';
import StockDetailScreen from './screens/StockDetailScreen';
import StrategyScreen from './screens/StrategyScreen';
import TurnDetailScreen from './screens/TurnDetailScreen';
import WatchlistScreen from './screens/WatchlistScreen';
import { useMonitorUnread } from './store/monitorUnread';
import { useTheme } from './store/theme';

export type TabParamList = {
  Chat: undefined;
  Watchlist: undefined;
  Holdings: undefined;
  Monitor: undefined;
  Settings: undefined;
};

export type RootStackParamList = {
  Main: NavigatorScreenParams<TabParamList> | undefined;
  StockDetail: { symbol: string; name?: string };
  TurnDetail: { turnId: string };
  MonitorEventDetail: { eventId: string };
  ReportDetail: { reportId: string };
  Reports: undefined;
  ScheduledTasks: undefined;
  Strategy: undefined;
  DataSources: undefined;
  Runtime: undefined;
  ModelService: undefined;
};

export const navigationRef = createNavigationContainerRef<RootStackParamList>();

let pendingRoute: string | null = null;

/** 通知点击 → 跳转。导航未就绪时先挂起，onReady 时再补跳。 */
export function routeFromNotification(url: string): void {
  if (!openAppRoute(url)) pendingRoute = url;
}

export function flushPendingRoute(): void {
  const r = pendingRoute;
  pendingRoute = null;
  if (r) openAppRoute(r);
}

export function openAppRoute(url: string): boolean {
  if (!navigationRef.isReady()) return false;
  const [seg, id] = url.replace(/^stockagent:\/\//, '').replace(/^\//, '').split('/');
  try {
    switch (seg) {
      case 'event':
        if (id) { navigationRef.navigate('MonitorEventDetail', { eventId: id }); return true; }
        break;
      case 'stock':
        if (id) { navigationRef.navigate('StockDetail', { symbol: id }); return true; }
        break;
      case 'report':
        if (id) { navigationRef.navigate('ReportDetail', { reportId: id }); return true; }
        break;
      case 'turn':
        if (id) { navigationRef.navigate('TurnDetail', { turnId: id }); return true; }
        break;
      case 'monitor': navigationRef.navigate('Main', { screen: 'Monitor' }); return true;
      case 'chat': navigationRef.navigate('Main', { screen: 'Chat' }); return true;
      case 'watchlist': navigationRef.navigate('Main', { screen: 'Watchlist' }); return true;
      case 'holdings': navigationRef.navigate('Main', { screen: 'Holdings' }); return true;
      case 'settings': navigationRef.navigate('Main', { screen: 'Settings' }); return true;
      case 'reports': navigationRef.navigate('Reports'); return true;
      case 'strategy': navigationRef.navigate('Strategy'); return true;
      case 'tasks': navigationRef.navigate('ScheduledTasks'); return true;
    }
  } catch {
    /* 忽略非法路径 */
  }
  return false;
}

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<TabParamList>();

/**
 * 深链配置：scheme 已在 app.json 声明为 stockagent。
 * 支持 stockagent://stock/600519、stockagent://event/<id>、stockagent://report/<id> 等，
 * 也是将来推送点击后跳转的基础（推送通道定了以后直接复用）。
 */
const linking = {
  prefixes: ['stockagent://'],
  config: {
    screens: {
      Main: {
        screens: {
          Chat: 'chat',
          Watchlist: 'watchlist',
          Holdings: 'holdings',
          Monitor: 'monitor',
          Settings: 'settings',
        },
      },
      StockDetail: 'stock/:symbol',
      TurnDetail: 'turn/:turnId',
      MonitorEventDetail: 'event/:eventId',
      ReportDetail: 'report/:reportId',
      Reports: 'reports',
      ScheduledTasks: 'tasks',
      Strategy: 'strategy',
      DataSources: 'datasources',
      Runtime: 'runtime',
      ModelService: 'models',
    },
  },
};

type IoniconName = keyof typeof Ionicons.glyphMap;

/** 选中=实心 / 未选中=描边，贴近 iOS Tab 规范；线条颜色跟随主题色 */
function tabIcon(active: IoniconName, inactive: IoniconName) {
  return ({ color, focused, size }: { color: string; focused: boolean; size: number }) => (
    <Ionicons name={focused ? active : inactive} size={size ?? 23} color={color} />
  );
}

const tabBarStyle = { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#e5e5ea' } as const;

function MainTabs() {
  const accent = useTheme((s) => s.accentHex);
  const unread = useMonitorUnread((s) => s.unreadCount);
  return (
    <Tabs.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: accent,
        tabBarInactiveTintColor: '#8E8E93',
        tabBarLabelStyle: { fontSize: 11, fontWeight: '500' },
        tabBarStyle: tabBarStyle,
        tabBarItemStyle: { paddingTop: 4 },
      }}
    >
      <Tabs.Screen name="Chat" component={ChatScreen} options={{ title: '对话', tabBarIcon: tabIcon('chatbubbles', 'chatbubbles-outline') }} />
      <Tabs.Screen name="Watchlist" component={WatchlistScreen} options={{ title: '自选', tabBarIcon: tabIcon('star', 'star-outline') }} />
      <Tabs.Screen name="Holdings" component={HoldingsScreen} options={{ title: '持仓', tabBarIcon: tabIcon('briefcase', 'briefcase-outline') }} />
      <Tabs.Screen
        name="Monitor"
        component={MonitorScreen}
        options={{
          title: '盯盘',
          tabBarIcon: tabIcon('radio', 'radio-outline'),
          // 空字符串 = 小红点（对齐 iOS .badge(Text(verbatim: ""))）
          tabBarBadge: unread > 0 ? '' : undefined,
          tabBarBadgeStyle: { backgroundColor: '#FF3B30', minWidth: 10, maxHeight: 10 },
        }}
      />
      <Tabs.Screen name="Settings" component={SettingsScreen} options={{ title: '设置', tabBarIcon: tabIcon('settings', 'settings-outline') }} />
    </Tabs.Navigator>
  );
}

export function RootNavigator() {
  const accent = useTheme((s) => s.accentHex);
  const scheme = useTheme((s) => s.scheme);
  const system = useColorScheme();
  const dark = scheme === 'dark' || (scheme === 'system' && system === 'dark');
  const base = dark ? DarkTheme : DefaultTheme;
  const navTheme: Theme = { ...base, colors: { ...base.colors, primary: accent } };

  return (
    <NavigationContainer ref={navigationRef} theme={navTheme} linking={linking as never} onReady={flushPendingRoute}>
      <Stack.Navigator>
        <Stack.Screen name="Main" component={MainTabs} options={{ headerShown: false }} />
        <Stack.Screen name="StockDetail" component={StockDetailScreen} options={{ title: '标的详情' }} />
        <Stack.Screen name="TurnDetail" component={TurnDetailScreen} options={{ title: '回答详情' }} />
        <Stack.Screen name="MonitorEventDetail" component={MonitorEventDetailScreen} options={{ title: '事件详情' }} />
        <Stack.Screen name="ReportDetail" component={ReportDetailScreen} options={{ title: '报告' }} />
        <Stack.Screen name="Reports" component={ReportsScreen} options={{ title: '研究报告' }} />
        <Stack.Screen name="ScheduledTasks" component={ScheduledTasksScreen} options={{ title: '定时任务' }} />
        <Stack.Screen name="Strategy" component={StrategyScreen} options={{ title: '策略回测' }} />
        <Stack.Screen name="DataSources" component={DataSourcesScreen} options={{ title: '行情数据源' }} />
        <Stack.Screen name="Runtime" component={RuntimeScreen} options={{ title: '运行状态' }} />
        <Stack.Screen name="ModelService" component={ModelServiceScreen} options={{ title: '模型服务' }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
