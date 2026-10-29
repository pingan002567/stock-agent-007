import { useCallback, useEffect } from "react";

export interface LightboxImage {
  src: string;
  name: string;
}

/** 图片预览浮层：支持多图 ← → 切换、计数，Esc / 点背景 / ✕ 关闭。 */
export function ImageLightbox({
  images,
  index,
  onIndexChange,
  onClose,
}: {
  images: LightboxImage[];
  index: number;
  onIndexChange: (next: number) => void;
  onClose: () => void;
}) {
  const total = images.length;
  const current = Math.max(0, Math.min(index, total - 1));

  const step = useCallback(
    (delta: number) => {
      if (total <= 1) return;
      const next = (current + delta + total) % total;
      onIndexChange(next);
    },
    [current, onIndexChange, total],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, step]);

  if (total === 0) return null;
  const image = images[current];

  return (
    <div className="img-lightbox" role="dialog" aria-label={`预览 ${image.name}`} onClick={onClose}>
      {total > 1 && (
        <button
          type="button"
          className="img-lightbox-nav prev"
          aria-label="上一张"
          onClick={(e) => {
            e.stopPropagation();
            step(-1);
          }}
        >
          ‹
        </button>
      )}
      <div className="img-lightbox-body" onClick={(e) => e.stopPropagation()}>
        <img src={image.src} alt={image.name} />
        <div className="img-lightbox-meta">
          <span className="img-lightbox-name">{image.name}</span>
          {total > 1 && (
            <span className="img-lightbox-count">
              {current + 1} / {total}
            </span>
          )}
          <button type="button" className="img-lightbox-close" onClick={onClose} aria-label="关闭预览">
            ✕
          </button>
        </div>
      </div>
      {total > 1 && (
        <button
          type="button"
          className="img-lightbox-nav next"
          aria-label="下一张"
          onClick={(e) => {
            e.stopPropagation();
            step(1);
          }}
        >
          ›
        </button>
      )}
    </div>
  );
}
