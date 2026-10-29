import { useState } from "react";
import { useUploadThumb } from "@/lib/useUploadThumb";
import { ImageLightbox } from "@/components/features/ImageLightbox";

/** 图片附件缩略图：点击放大预览（对齐 DeepSeek 的观感）。
 *
 *  取不到图（接口 404 / 非图片）时返回 null，调用方回退成文件名芯片。
 */
export function UploadThumb({
  sessionId,
  filename,
  size = 44,
  onRemove,
  removeLabel,
  title,
}: {
  sessionId: string | null | undefined;
  filename: string;
  size?: number;
  /** 给了才渲染删除按钮（输入区需要，历史消息不需要） */
  onRemove?: () => void;
  removeLabel?: string;
  title?: string;
}) {
  const url = useUploadThumb(sessionId, filename);
  const [open, setOpen] = useState(false);

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

  return (
    <>
      <span className="upload-thumb" title={title ?? filename}>
        <button type="button" className="upload-thumb-btn" onClick={() => setOpen(true)} aria-label={`预览 ${filename}`}>
          <img src={url} alt={filename} style={{ width: size, height: size }} />
        </button>
        {onRemove && (
          <button
            type="button"
            className="upload-thumb-del"
            aria-label={removeLabel ?? `移除 ${filename}`}
            onClick={onRemove}
          >
            ×
          </button>
        )}
      </span>
      {open && <ImageLightbox src={url} name={filename} onClose={() => setOpen(false)} />}
    </>
  );
}
