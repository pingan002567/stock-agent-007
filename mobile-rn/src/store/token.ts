import * as SecureStore from 'expo-secure-store';

// 令牌与地址的持久化。expo-secure-store 在 Android 走 Keystore、iOS 走 Keychain，
// 语义对齐 iOS 端 AuthStore（解锁后可读、仅本机）。
// 注：技术选型文档 4.7/7.2 —— 不要用 androidx.security:security-crypto（已废弃）。

const URL_KEY = 'stockagent.remoteUrl';
const TOKEN_KEY = 'stockagent.accessToken';

export interface Profile {
  baseURL: string;
  token: string;
}

export async function saveProfile(baseURL: string, token: string): Promise<void> {
  await SecureStore.setItemAsync(URL_KEY, baseURL);
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function loadProfile(): Promise<Profile | null> {
  const baseURL = await SecureStore.getItemAsync(URL_KEY);
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  if (!baseURL && !token) return null;
  return { baseURL: baseURL ?? '', token: token ?? '' };
}

export async function clearProfile(): Promise<void> {
  await SecureStore.deleteItemAsync(URL_KEY);
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
