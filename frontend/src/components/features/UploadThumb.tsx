import { useState } from "react";
import { useUploadThumb } from "@/lib/useUploadThumb";

/** 图片附件缩略图（不含预览浮层：多图切换由 AttachmentChips 统一管理）。 */
export function UploadThumb({
  sessionId,
  filename,
  size = 44,
  onReady,
  onOpen,
  onRemove,
  removeLabel,
  title,
}: {
  sessionId: string | null | undefined;
  filename: string;
  size?: number;
  /** 缩略图 URL 就绪时回调（父组件用它凑多图列表） */
  onReady?: (filename: string, url: string) => void;
  onOpen?: (filename: string) => void;
  onRemove?: () => void;
  removeLabel?: string;
  title?: string;
}) {
  const url = useUploadThumb(sessionId, filename);
  const [broken, setBroken] = useState(false);

  if (!url) {
    return (
      <span className="upload-chip">
        <span className="upload-chip-name">{filename}</span>
        {onRemove && (
          <button type="button" className="upload-chip-del" aria-label={removeLabel ?? `移除 ${filename}`} onClick={onRemove}>
            ×
          </button>
        )}
      </span>
    );
  }

  // 拿到了 URL 但解码失败（坏 blob / 被撤销）→ 也回退成芯片，别显示破图
  if (broken) {
    return (
      <span className="upload-chip">
        <span className="upload-chip-name">{filename}</span>
        {onRemove && (
          <button type="button" className="upload-chip-del" aria-label={removeLabel ?? `移除 ${filename}`} onClick={onRemove}>
            ×
          </button>
        )}
      </span>
    );
  }

  onReady?.(filename, url);

  return (
    <span className="upload-thumb" title={title ?? filename}>
      <button
        type="button"
        className="upload-thumb-btn"
        onClick={() => onOpen?.(filename)}
        aria-label={`预览 ${filename}`}
      >
        <img src={url} alt={filename} style={{ width: size, height: size }} onError={() => setBroken(true)} />
      </button>
      {onRemove && (
        <button
          type="button"
          className="upload-thumb-del"
          aria-label={removeLabel ?? `移除 ${filename}`}
          onClick={onRemove}
        >
          <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden>
            <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </span>
  );
}
