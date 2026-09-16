import { useEffect, useRef, useState } from "react";

type Props = {
  content: string;
  /** 流式进行中（尾段）：限高滚动，不折叠 */
  streaming?: boolean;
  /** 非流式时默认是否展开 */
  defaultOpen?: boolean;
};

/** 思考块：流式限高；结束后折叠，避免长推理顶掉正文。 */
export function ThinkingBlock({ content, streaming = false, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const scrollRef = useRef<HTMLDivElement>(null);
  const compact = content.replace(/\n{2,}/g, "\n").trim();

  useEffect(() => {
    if (!streaming) setOpen(defaultOpen);
  }, [streaming, defaultOpen]);

  useEffect(() => {
    if (streaming && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [streaming, compact]);

  if (!compact) return null;

  if (streaming) {
    return (
      <div className="thinking-block streaming">
        <div className="thinking-block-head">
          <span className="thinking-block-pulse" aria-hidden />
          <span>思考过程</span>
        </div>
        <div className="thinking-block-body" ref={scrollRef}>
          <pre>{compact}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className={`thinking-block${open ? " open" : ""}`}>
      <button
        type="button"
        className="thinking-block-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="thinking-block-chevron" aria-hidden>{open ? "▾" : "▸"}</span>
        <span>思考过程</span>
        {!open ? (
          <span className="thinking-block-peek">{compact.split("\n")[0]}</span>
        ) : null}
      </button>
      {open ? (
        <div className="thinking-block-body">
          <pre>{compact}</pre>
        </div>
      ) : null}
    </div>
  );
}
