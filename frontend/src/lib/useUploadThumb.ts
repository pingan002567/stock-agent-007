import { useEffect, useState } from "react";
import { releaseUploadObjectUrl, uploadObjectUrl } from "@/lib/uploadThumbs";

/** 把一个会话附件换成可直接放进 <img> 的 blob URL。
 *
 *  失败返回 null（调用方回退成普通芯片），卸载时释放引用避免泄漏。
 */
export function useUploadThumb(sessionId: string | null | undefined, filename: string, enabled = true) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !sessionId) return undefined;
    let alive = true;
    let acquired = false;
    void (async () => {
      const next = await uploadObjectUrl(sessionId, filename);
      if (!alive) {
        if (next) releaseUploadObjectUrl(sessionId, filename);
        return;
      }
      if (next) acquired = true;
      setUrl(next);
    })();
    return () => {
      alive = false;
      if (acquired) releaseUploadObjectUrl(sessionId, filename);
    };
  }, [sessionId, filename, enabled]);

  return url;
}
