import { useEffect, useMemo, useRef, useState } from "react";

export type SessionModelOption = { value: string; label: string };

export function SessionModelPicker({
  value,
  options,
  disabled,
  onChange,
}: {
  value: string | null;
  options: SessionModelOption[];
  disabled?: boolean;
  onChange: (value: string) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const label = useMemo(() => {
    const hit = options.find((item) => item.value === value);
    if (hit) return hit.label;
    if (value && value.includes("/")) {
      const [, modelId] = value.split("/", 2);
      return modelId || value;
    }
    return value || "AI 模型";
  }, [options, value]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (options.length === 0) {
    return (
      <span className="model-pill" title="请先在设置里连接提供商">
        未配置模型
      </span>
    );
  }

  return (
    <div className="session-model-picker" ref={rootRef}>
      <button
        type="button"
        className="model-pill model-pill-btn"
        title="切换本会话使用的模型"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
        <span className="model-pill-caret">▾</span>
      </button>
      {open && (
        <div className="session-model-menu" role="listbox">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="option"
              aria-selected={opt.value === value}
              className={`session-model-option${opt.value === value ? " on" : ""}`}
              onClick={() => {
                setOpen(false);
                void onChange(opt.value);
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
