import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';

export const NOTIFY_CHANNEL_ID = 'stockagent-alerts';

/** 前台收到通知时的展示策略（SDK 57 用 shouldShowBanner / shouldShowList） */
export function configureNotificationHandler() {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

/** Android 8+ 需要先建渠道，否则通知不显示 */
export async function ensureAndroidChannel() {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync(NOTIFY_CHANNEL_ID, {
    name: '盯盘提醒',
    importance: Notifications.AndroidImportance.DEFAULT,
    vibrationPattern: [0, 200, 100, 200],
  });
}

export async function getPermissionGranted(): Promise<boolean> {
  try {
    const cur = await Notifications.getPermissionsAsync();
    return !!cur.granted;
  } catch {
    return false;
  }
}

export async function ensurePermission(): Promise<boolean> {
  try {
    const cur = await Notifications.getPermissionsAsync();
    if (cur.granted) return true;
    if (cur.canAskAgain === false) return false;
    const req = await Notifications.requestPermissionsAsync();
    return !!req.granted;
  } catch {
    return false;
  }
}

/** 发本地通知（不依赖任何第三方推送服务） */
export async function showLocal(
  title: string,
  body: string,
  data?: Record<string, unknown>
): Promise<void> {
  await ensureAndroidChannel();
  await Notifications.scheduleNotificationAsync({
    content: {
      title,
      body,
      data: data ?? {},
      ...(Platform.OS === 'android' ? { channelId: NOTIFY_CHANNEL_ID } : null),
    },
    trigger: null,
  });
}

/** 测试通知 */
export async function sendTestNotification(): Promise<boolean> {
  const ok = await ensurePermission();
  if (!ok) return false;
  await showLocal('Stock Agent 测试通知', '推送通道已就绪，点这条通知会跳到盯盘页。', {
    route: 'stockagent://monitor',
  });
  return true;
}
