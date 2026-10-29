import { useEffect, useState } from "react";
import { uploadObjectUrl } from "@/lib/uploadThumbs";

/** 把一个会话附件换成可直接放进 <img> 的 blob URL。
 *
 *  失败返回 null（调用方回退成普通芯片）。不在这里撤销 URL —— 缓存在
 *  `lib/uploadThumbs` 里按 LRU 管理，避免重挂时把别人正在用的 URL 撤掉。
 */
export function useUploadThumb(sessionId: string | null | undefined, filename: string, enabled = true) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !sessionId) return undefined;
    let alive = true;
    void (async () => {
      const next = await uploadObjectUrl(sessionId, filename);
      if (alive) setUrl(next);
    })();
    return () => {
      alive = false;
    };
  }, [sessionId, filename, enabled]);

  return url;
}
