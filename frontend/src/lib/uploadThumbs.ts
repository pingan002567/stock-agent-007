/** 会话附件的缩略图/预览：用 Bearer 取字节 → blob URL → <img>。
 *
 *  为什么不用 `<img src="/api/...">` 直接指过去：接口鉴权是 Authorization 头，
 *  `<img>` 带不上；把 token 拼进 URL 又会被历史/日志记录。所以 fetch + blob。
 *
 *  同一张图多次渲染（输入区芯片 + 消息里的附件）共用缓存，避免重复下载。
 */
import { apiUrl } from "@/api/client";
import { authHeaders } from "@/lib/connection";

export interface UploadBlobEntry {
  url: string;
  /** 引用计数：两个组件都用同一张图时，别一个卸载就把 URL 撤销了 */
  refs: number;
}

const cache = new Map<string, UploadBlobEntry>();
const inflight = new Map<string, Promise<string | null>>();

function keyOf(sessionId: string, filename: string): string {
  return `${sessionId}\u0000${filename}`;
}

async function download(sessionId: string, filename: string): Promise<string | null> {
  const url = apiUrl(
    `/api/copilot/sessions/${encodeURIComponent(sessionId)}/uploads/${encodeURIComponent(filename)}`,
  );
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) return null;
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/** 取附件的 blob URL（带缓存与并发去重）。失败返回 null，调用方回退到普通芯片。 */
export async function uploadObjectUrl(sessionId: string, filename: string): Promise<string | null> {
  const key = keyOf(sessionId, filename);
  const hit = cache.get(key);
  if (hit) {
    hit.refs += 1;
    return hit.url;
  }
  const pending = inflight.get(key);
  if (pending) return pending;
  const task = download(sessionId, filename)
    .then((url) => {
      if (url) cache.set(key, { url, refs: 1 });
      return url;
    })
    .catch(() => null)
    .finally(() => inflight.delete(key));
  inflight.set(key, task);
  return task;
}

/** 释放一次引用；归零才真正 revoke，避免另一个组件还在显示时被撤销 */
export function releaseUploadObjectUrl(sessionId: string, filename: string): void {
  const key = keyOf(sessionId, filename);
  const hit = cache.get(key);
  if (!hit) return;
  hit.refs -= 1;
  if (hit.refs <= 0) {
    URL.revokeObjectURL(hit.url);
    cache.delete(key);
  }
}
