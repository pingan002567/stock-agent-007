/** 客户端后端连接：本地 launchd / 远端 URL。
 *
 * 手机端：设置 window.__STOCKAGENT_FORCE_REMOTE__ = true，连接页只留远端，
 * 且不会自动探活——必须用户填写地址并点「连接」。
 * 远端需访问令牌；上线前收紧 CORS，不要裸放 8686。
 */

export const CONNECTION_STORAGE_KEY = "STOCKAGENT_CONNECTION";
export const DEFAULT_LOCAL_PORT = 8686;

export type ConnectionMode = "local" | "remote";

export type ConnectionProfile = {
  mode: ConnectionMode;
  remoteUrl?: string;
  localPort?: number;
  accessToken?: string;
};

export type HealthProbeResult =
  | { ok: true; data: Record<string, unknown> }
  | { ok: false; error: string };

export type ServiceDoctor = {
  ok?: boolean;
  backend_healthy?: boolean;
  service_installed?: boolean;
  data_dir?: string;
  frontend_dist_exists?: boolean;
  platform_ok?: boolean;
  venv_python_exists?: boolean;
  state_dir?: string;
  port?: number;
  error?: string;
};

declare global {
  interface Window {
    __STOCKAGENT_FORCE_REMOTE__?: boolean;
    Capacitor?: { isNativePlatform?: () => boolean; Plugins?: Record<string, { open?: (opts: { url: string }) => Promise<void> }> };
    __TAURI__?: {
      dialog?: { open?: (opts: Record<string, unknown>) => Promise<string | null> };
      core?: { invoke?: (cmd: string, payload?: Record<string, unknown>) => Promise<unknown> };
    };
  }
}

export function canStartLocalBackend(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(window.__TAURI__?.core?.invoke);
}

/** 无本机后端的壳（iOS/Android）只允许远端。浏览器与桌面可选手本地。 */
export function canUseLocalMode(): boolean {
  if (typeof window === "undefined") return true;
  return window.__STOCKAGENT_FORCE_REMOTE__ !== true;
}

export function isNativeMobile(): boolean {
  if (typeof window === "undefined") return false;
  if (window.__STOCKAGENT_FORCE_REMOTE__ === true) return true;
  if (window.Capacitor?.isNativePlatform?.()) return true;
  return window.location.protocol === "capacitor:" || window.location.protocol === "ionic:";
}

export function isMobileLayout(): boolean {
  if (typeof window === "undefined") return false;
  if (isNativeMobile()) return true;
  return window.matchMedia("(max-width: 720px)").matches;
}

export function normalizeRemoteUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) throw new Error("请填写远端地址");
  let parsed: URL;
  try {
    parsed = new URL(trimmed.includes("://") ? trimmed : `http://${trimmed}`);
  } catch {
    throw new Error("地址格式不正确");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("只支持 http 或 https 地址");
  }
  const path = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
  return `${parsed.origin}${path}`;
}

export function resolveApiBase(profile: ConnectionProfile): string {
  if (profile.mode === "local") {
    return `http://127.0.0.1:${profile.localPort || DEFAULT_LOCAL_PORT}`;
  }
  if (!profile.remoteUrl) throw new Error("未配置远端地址");
  return normalizeRemoteUrl(profile.remoteUrl);
}

function isProfile(value: unknown): value is ConnectionProfile {
  if (!value || typeof value !== "object") return false;
  const mode = (value as ConnectionProfile).mode;
  return mode === "local" || mode === "remote";
}

export function loadConnection(): ConnectionProfile | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CONNECTION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isProfile(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveConnection(profile: ConnectionProfile): void {
  if (typeof window === "undefined") return;
  const token = profile.accessToken?.trim() || undefined;
  const stored: ConnectionProfile =
    profile.mode === "local"
      ? {
          mode: "local",
          localPort: profile.localPort || DEFAULT_LOCAL_PORT,
          remoteUrl: profile.remoteUrl,
          accessToken: token,
        }
      : {
          mode: "remote",
          remoteUrl: normalizeRemoteUrl(profile.remoteUrl || ""),
          localPort: profile.localPort,
          accessToken: token,
        };
  window.localStorage.setItem(CONNECTION_STORAGE_KEY, JSON.stringify(stored));
  if (profile.mode === "local" && stored.localPort) {
    window.localStorage.setItem("sa.lastGoodPort", String(stored.localPort));
  }
}

export function clearConnection(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(CONNECTION_STORAGE_KEY);
}

export function formatConnectionLabel(profile: ConnectionProfile): string {
  if (profile.mode === "local") {
    return `本地 · ${profile.localPort || DEFAULT_LOCAL_PORT}`;
  }
  try {
    const base = resolveApiBase(profile);
    const url = new URL(base);
    const host = url.port ? `${url.hostname}:${url.port}` : url.hostname;
    return `远端 · ${host}`;
  } catch {
    return "远端";
  }
}

export function isRemoteMode(profile: ConnectionProfile | null = loadConnection()): boolean {
  return profile?.mode === "remote";
}

/** 桌面可恢复上次连接；手机 / Capacitor 必须用户点一次「连接」。 */
export function shouldAutoConnect(): boolean {
  return canUseLocalMode();
}

export function remoteUrlHint(profile: ConnectionProfile | null = loadConnection()): string {
  if (profile?.remoteUrl) return profile.remoteUrl;
  if (!canUseLocalMode()) return "";
  const env = (import.meta.env.VITE_API_BASE as string | undefined)?.trim();
  if (env) return env.replace(/\/$/, "");
  return "https://47.103.58.33:8686";
}

export function authHeaders(profile: ConnectionProfile | null = loadConnection()): Record<string, string> {
  const token = profile?.accessToken?.trim();
  return token ? { "X-Workbench-Token": token } : {};
}

export function withAccessToken(url: string, profile: ConnectionProfile | null = loadConnection()): string {
  const token = profile?.accessToken?.trim();
  if (!token) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}access_token=${encodeURIComponent(token)}`;
}

export async function probeHealth(
  base: string,
  timeoutMs = 8000,
  token?: string,
): Promise<HealthProbeResult> {
  let normalized: string;
  try {
    normalized = normalizeRemoteUrl(base);
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "地址无效" };
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const headers: Record<string, string> = {};
  const access = token?.trim() || "";
  if (access) headers["X-Workbench-Token"] = access;
  try {
    const res = await fetch(`${normalized}/api/health`, {
      cache: "no-store",
      signal: ctrl.signal,
      headers,
    });
    if (!res.ok) {
      if (res.status === 401) return { ok: false, error: "访问令牌无效" };
      return { ok: false, error: `健康检查失败（HTTP ${res.status}）` };
    }
    const data = (await res.json()) as Record<string, unknown>;
    if (data.status !== "ok") {
      return { ok: false, error: "后端已响应，但健康状态不是 ok" };
    }
    if (!data.agent_runtime) {
      return { ok: false, error: access ? "访问令牌无效" : "需要访问令牌" };
    }
    return { ok: true, data };
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return { ok: false, error: "连接超时，请确认地址与网络" };
    }
    const msg = err instanceof Error ? err.message : String(err);
    if (/certificate|SSL|TLS|secure connection|NSURLError/i.test(msg)) {
      return { ok: false, error: "证书不被信任：请用最新 iOS 壳（已放行自签），或在系统里信任该证书" };
    }
    return { ok: false, error: "无法连上后端，请确认服务已启动、地址正确，且手机能访问该主机" };
  } finally {
    clearTimeout(timer);
  }
}

export async function invokeServiceCli<T = Record<string, unknown>>(args: string[]): Promise<T> {
  const invoke = typeof window === "undefined" ? undefined : window.__TAURI__?.core?.invoke;
  if (!invoke) throw new Error("当前环境不能管理本机后端");
  return invoke("service_cli", { args }) as Promise<T>;
}
