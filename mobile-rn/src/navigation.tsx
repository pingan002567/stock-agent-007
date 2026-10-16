import { DarkTheme, DefaultTheme, NavigationContainer, type NavigatorScreenParams, type Theme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Text, useColorScheme } from 'react-native';
import ChatScreen from './screens/ChatScreen';
import DataSourcesScreen from './screens/DataSourcesScreen';
import HoldingsScreen from './screens/HoldingsScreen';
import MonitorScreen from './screens/MonitorScreen';
import ReportDetailScreen from './screens/ReportDetailScreen';
import ReportsScreen from './screens/ReportsScreen';
import ScheduledTasksScreen from './screens/ScheduledTasksScreen';
import SettingsScreen from './screens/SettingsScreen';
import StockDetailScreen from './screens/StockDetailScreen';
import StrategyScreen from './screens/StrategyScreen';
import WatchlistScreen from './screens/WatchlistScreen';
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
  ReportDetail: { reportId: string };
  Reports: undefined;
  ScheduledTasks: undefined;
  Strategy: undefined;
  DataSources: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<TabParamList>();

function tabIcon(emoji: string) {
  return ({ color }: { color: string }) => <Text style={{ color, fontSize: 18 }}>{emoji}</Text>;
}

function MainTabs() {
  const accent = useTheme((s) => s.accentHex);
  return (
    <Tabs.Navigator screenOptions={{ headerShown: false, tabBarActiveTintColor: accent }}>
      <Tabs.Screen name="Chat" component={ChatScreen} options={{ title: '对话', tabBarIcon: tabIcon('💬') }} />
      <Tabs.Screen name="Watchlist" component={WatchlistScreen} options={{ title: '自选', tabBarIcon: tabIcon('⭐') }} />
      <Tabs.Screen name="Holdings" component={HoldingsScreen} options={{ title: '持仓', tabBarIcon: tabIcon('💼') }} />
      <Tabs.Screen name="Monitor" component={MonitorScreen} options={{ title: '盯盘', tabBarIcon: tabIcon('📡') }} />
      <Tabs.Screen name="Settings" component={SettingsScreen} options={{ title: '设置', tabBarIcon: tabIcon('⚙️') }} />
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
    <NavigationContainer theme={navTheme}>
      <Stack.Navigator>
        <Stack.Screen name="Main" component={MainTabs} options={{ headerShown: false }} />
        <Stack.Screen name="StockDetail" component={StockDetailScreen} options={{ title: '标的详情' }} />
        <Stack.Screen name="ReportDetail" component={ReportDetailScreen} options={{ title: '报告' }} />
        <Stack.Screen name="Reports" component={ReportsScreen} options={{ title: '研究报告' }} />
        <Stack.Screen name="ScheduledTasks" component={ScheduledTasksScreen} options={{ title: '定时任务' }} />
        <Stack.Screen name="Strategy" component={StrategyScreen} options={{ title: '策略回测' }} />
        <Stack.Screen name="DataSources" component={DataSourcesScreen} options={{ title: '行情数据源' }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
