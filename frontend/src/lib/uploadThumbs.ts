/** 会话附件的缩略图/预览：用鉴权头取字节 → blob URL → <img>。
 *
 *  为什么不用 `<img src="/api/...?access_token=...">`：那个 query token 只对 SSE
 *  路径开放，硬开等于把令牌写进 URL/浏览器历史。所以 fetch + blob。
 *
 *  **缓存策略：LRU，不在组件卸载时 revoke。**
 *  早先按引用计数"最后一个卸载就撤销"，在 StrictMode / 快速重挂下会撤销掉
 *  另一个实例正在用的 URL，`<img>` 就渲染成破图。改成保留最近 N 张、只在被
 *  挤出缓存时撤销 —— 生命周期可预测，也不会泄漏。
 */
import { apiUrl } from "@/api/client";
import { authHeaders } from "@/lib/connection";

const MAX_CACHED = 24;
const cache = new Map<string, string>(); // 插入顺序即 LRU 顺序
const inflight = new Map<string, Promise<string | null>>();

function keyOf(sessionId: string, filename: string): string {
  return `${sessionId}\u0000${filename}`;
}

/** 附件直链（fetch 用；不含 token） */
export function uploadApiUrl(sessionId: string, filename: string): string {
  return apiUrl(
    `/api/copilot/sessions/${encodeURIComponent(sessionId)}/uploads/${encodeURIComponent(filename)}`,
  );
}

/** 附件文件的公开形态（用于分享/下载链接展示；调用方自己决定要不要带 token） */
export function uploadFilePath(sessionId: string, filename: string): string {
  return uploadApiUrl(sessionId, filename);
}

async function download(sessionId: string, filename: string): Promise<string | null> {
  const res = await fetch(uploadApiUrl(sessionId, filename), { headers: authHeaders() });
  if (!res.ok) return null;
  const blob = await res.blob();
  // 服务端偶尔会返回 HTML/JSON（网关页、错误页）：不是图片就别当图用
  if (!blob.type.startsWith("image/")) return null;
  return URL.createObjectURL(blob);
}

function remember(key: string, url: string): void {
  const existing = cache.get(key);
  if (existing) {
    URL.revokeObjectURL(existing);
    cache.delete(key);
  }
  cache.set(key, url);
  while (cache.size > MAX_CACHED) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    const stale = cache.get(oldest);
    cache.delete(oldest);
    if (stale) URL.revokeObjectURL(stale);
  }
}

/** 取附件的 blob URL（带 LRU 缓存 + 并发去重）。失败返回 null，调用方回退芯片。 */
export async function uploadObjectUrl(sessionId: string, filename: string): Promise<string | null> {
  const key = keyOf(sessionId, filename);
  const hit = cache.get(key);
  if (hit) {
    // 命中即刷新 LRU 位置
    cache.delete(key);
    cache.set(key, hit);
    return hit;
  }
  const pending = inflight.get(key);
  if (pending) return pending;
  const task = download(sessionId, filename)
    .then((url) => {
      if (url) remember(key, url);
      return url;
    })
    .catch(() => null)
    .finally(() => inflight.delete(key));
  inflight.set(key, task);
  return task;
}

/** 清空缓存（登出/换后端时用；测试里也用） */
export function clearUploadThumbCache(): void {
  for (const url of cache.values()) URL.revokeObjectURL(url);
  cache.clear();
  inflight.clear();
}
