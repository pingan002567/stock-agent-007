import { useEffect } from "react";

/** 图片预览浮层：点背景或按 Esc 关闭。 */
export function ImageLightbox({
  src,
  name,
  onClose,
}: {
  src: string;
  name: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="img-lightbox" role="dialog" aria-label={`预览 ${name}`} onClick={onClose}>
      <div className="img-lightbox-body" onClick={(e) => e.stopPropagation()}>
        <img src={src} alt={name} />
        <div className="img-lightbox-meta">
          <span>{name}</span>
          <button type="button" className="img-lightbox-close" onClick={onClose} aria-label="关闭预览">
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}
