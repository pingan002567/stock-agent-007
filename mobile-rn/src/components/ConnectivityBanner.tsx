import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useNetInfo } from '@react-native-community/netinfo';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useConnection } from '../store/connection';
import { useThemedStyles } from '../lib/tokens';

/** 网络/鉴权横幅（对齐 iOS App/ConnectivityBanner.swift + NetworkReachability） */
export function ConnectivityBanner() {
  const styles = useThemedStyles(baseStyles);
  const net = useNetInfo();
  const insets = useSafeAreaInsets();
  const authFailed = useConnection((s) => s.authFailed);

  const offline = net.isConnected === false;
  if (!offline && !authFailed) return null;

  return (
    <View style={[styles.banner, { paddingTop: insets.top + 6 }, authFailed && !offline && styles.auth]}>
      <Text style={styles.text}>
        {offline ? '📵 网络不可用，恢复后会自动重连' : '🔒 访问令牌无效或已过期，请重新连接'}
      </Text>
      {authFailed && !offline ? (
        <Pressable onPress={() => useConnection.getState().clearAuthFailure()} hitSlop={8}>
          <Text style={styles.dismiss}>知道了</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const baseStyles = StyleSheet.create({
  banner: {
    backgroundColor: '#FF9500',
    paddingHorizontal: 12,
    paddingBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  auth: { backgroundColor: '#FF3B30' },
  text: { color: '#fff', fontSize: 13, fontWeight: '600', textAlign: 'center', flexShrink: 1 },
  dismiss: { color: '#fff', fontSize: 13, fontWeight: '700', textDecorationLine: 'underline' },
});
