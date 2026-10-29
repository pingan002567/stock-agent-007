import { useCallback, useState } from "react";
import { UploadThumb } from "@/components/features/UploadThumb";
import { ImageLightbox, type LightboxImage } from "@/components/features/ImageLightbox";
import { isImageUploadFilename } from "@/lib/sessionUploads";

export interface AttachmentFile {
  filename: string;
  markdown_file?: string | null;
}

/** 附件行：图片渲染缩略图 + 多图预览（← → 切换、1/N 计数），非图片保持文件名芯片。 */
export function AttachmentChips({
  sessionId,
  files,
  onRemove,
  className,
}: {
  sessionId: string | null | undefined;
  files: AttachmentFile[];
  /** 给了才显示删除按钮（输入区需要，历史消息不需要） */
  onRemove?: (filename: string) => void;
  className?: string;
}) {
  /** filename → blob URL（缩略图就绪后登记，用于多图预览） */
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [openAt, setOpenAt] = useState<string | null>(null);

  const register = useCallback((filename: string, url: string) => {
    setUrls((prev) => (prev[filename] === url ? prev : { ...prev, [filename]: url }));
  }, []);

  // 预览顺序 = 附件里的图片顺序（只含有 URL 的）
  const previewable: LightboxImage[] = files
    .filter((f) => isImageUploadFilename(f.filename) && urls[f.filename])
    .map((f) => ({ src: urls[f.filename], name: f.filename }));
  const openIndex = openAt ? previewable.findIndex((img) => img.name === openAt) : -1;

  return (
    <>
      <div className={`upload-chips${className ? ` ${className}` : ""}`}>
        {files.map((f) => {
          if (isImageUploadFilename(f.filename)) {
            return (
              <UploadThumb
                key={f.filename}
                sessionId={sessionId}
                filename={f.filename}
                title={f.markdown_file ? `已转 Markdown：${f.markdown_file}` : f.filename}
                onReady={register}
                onOpen={setOpenAt}
                onRemove={onRemove ? () => onRemove(f.filename) : undefined}
              />
            );
          }
          return (
            <span
              key={f.filename}
              className="upload-chip"
              title={f.markdown_file ? `已转 Markdown：${f.markdown_file}` : f.filename}
            >
              <span className="upload-chip-name">{f.filename}</span>
              {f.markdown_file ? <span className="upload-chip-ok">✓</span> : null}
              {onRemove && (
                <button
                  type="button"
                  className="upload-chip-del"
                  aria-label={`移除 ${f.filename}`}
                  onClick={() => onRemove(f.filename)}
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
      </div>
      {openIndex >= 0 && (
        <ImageLightbox
          images={previewable}
          index={openIndex}
          onIndexChange={(next) => setOpenAt(previewable[next]?.name ?? null)}
          onClose={() => setOpenAt(null)}
        />
      )}
    </>
  );
}
