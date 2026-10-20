import { useEffect, useRef, useState } from "react";
import {
  BUBBLE_STATES,
  PET_ANCHOR_KEY,
  PET_STATE_KEY,
  PET_SIZE,
  type PetPayload,
  type PetState,
} from "@/lib/petBridge";
import done1 from "@/assets/pet/done-1.webp";
import done2 from "@/assets/pet/done-2.webp";
import done3 from "@/assets/pet/done-3.webp";
import alert1 from "@/assets/pet/alert-1.webp";
import alert2 from "@/assets/pet/alert-2.webp";
import error1 from "@/assets/pet/error-1.webp";
import error2 from "@/assets/pet/error-2.webp";

type TauriGlobal = {
  core?: { invoke?: <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
};

/** 主窗口 → 桌宠的度量：[x, y, w, h, scale, workX, workY, workW, workH]（物理像素） */
type Metrics = [number, number, number, number, number, number, number, number, number];

const BUBBLE_MS = 8000;
/** 一次性动作（眨眼/歪头）时长 */
const ONESHOT_MS = 620;

/** done / alert / error 用静态关键帧交叉淡入（与 idle/run 同一套画风） */
const STATIC_FRAMES: Record<"done" | "alert" | "error", string[]> = {
  done: [done1, done2, done3],
  alert: [alert1, alert2],
  error: [error1, error2],
};
const STATIC_MS = { done: 700, alert: 900, error: 1400 } as const;

function readPayload(): PetPayload | null {
  try {
    const raw = localStorage.getItem(PET_STATE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as PetPayload;
    return p?.state ? p : null;
  } catch {
    return null;
  }
}

/** 静态帧：叠在一起靠透明度交叉淡入 */
function PetStills({ frames, ms }: { frames: string[]; ms: number }) {
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (frames.length < 2) return;
    const t = window.setInterval(() => setIdx((i) => (i + 1) % frames.length), ms);
    return () => window.clearInterval(t);
  }, [frames.length, ms]);
  return (
    <>
      {frames.map((src, i) => (
        <span
          key={src}
          className={`pet-frame${i === idx ? " on" : ""}`}
          style={{ backgroundImage: `url(${src})` }}
        />
      ))}
    </>
  );
}

/** 桌宠本体：idle/working 是 sprite sheet 真循环（含偶尔的眨眼/歪头），
 *  done/alert/error 是静态关键帧交叉淡入。 */
function PetSprite({
  state,
  oneshot,
  tick,
}: {
  state: PetState;
  oneshot: "blink" | "tilt" | null;
  tick: number;
}) {
  if (state === "idle") {
    return (
      <>
        <span className="pet-sprite pet-breathe" />
        {oneshot && <span key={`${oneshot}-${tick}`} className={`pet-sprite pet-oneshot pet-${oneshot}`} />}
      </>
    );
  }
  if (state === "working") return <span className="pet-sprite pet-run" />;
  return <PetStills frames={STATIC_FRAMES[state]} ms={STATIC_MS[state]} />;
}

/** 桌宠窗口（label = "pet"）。
 *
 *  - 状态从 localStorage 读（主窗口写、storage 事件送达）
 *  - 单击：叫出主窗口 + 弹一下；拖动：系统原生拖拽，松手存位置
 *  - 气泡只在 alert / done / error 弹，弹出时窗口临时撑大（锚定右下角）
 */
export function PetWindow() {
  const initial = readPayload();
  const [state, setState] = useState<PetState>(initial?.state ?? "idle");
  const [badge, setBadge] = useState(initial?.badge ?? 0);
  const [bubble, setBubble] = useState<{ title: string; body?: string } | null>(
    initial && BUBBLE_STATES.includes(initial.state) && initial.title
      ? { title: initial.title, body: initial.body }
      : null,
  );
  const [bounce, setBounce] = useState(false);
  const [oneshot, setOneshot] = useState<"blink" | "tilt" | null>(null);
  const [oneshotTick, setOneshotTick] = useState(0);

  const invoke = (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__?.core?.invoke;

  /** 窗口几何缓存（物理像素）。改尺寸时用它算新位置 —— 不去读 outer_size，
   *  那个值是异步生效的，跟上一次 set_size 抢起来会把窗口推到屏幕中间。 */
  const frameRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const scaleRef = useRef(1);
  const dragRef = useRef({ x: 0, y: 0, active: false, dragging: false });

  // 跨窗口状态同步（初值已在 useState 里读好）
  useEffect(() => {
    const apply = (raw: string | null) => {
      if (!raw) return;
      let p: PetPayload;
      try {
        p = JSON.parse(raw) as PetPayload;
      } catch {
        return;
      }
      if (!p?.state) return;
      setState(p.state);
      setBadge(p.badge ?? 0);
      if (BUBBLE_STATES.includes(p.state) && p.title) setBubble({ title: p.title, body: p.body });
      else setBubble(null);
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === PET_STATE_KEY) apply(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // 尺寸：随气泡切换。位置按「右下角不动」推出来。
  useEffect(() => {
    if (!invoke) return;
    void (async () => {
      try {
        const [px, py, pw, ph, sf, wx, wy, ww, wh] = await invoke<Metrics>("pet_metrics");
        scaleRef.current = sf;

        if (!frameRef.current) {
          let saved: { x: number; y: number } | null = null;
          try {
            saved = JSON.parse(localStorage.getItem(PET_ANCHOR_KEY) ?? "null") as { x: number; y: number } | null;
          } catch {
            /* 脏数据忽略 */
          }
          const sane =
            saved && ww > 0 && saved.x >= wx && saved.y >= wy && saved.x < wx + ww && saved.y < wy + wh;
          if (saved && !sane) localStorage.removeItem(PET_ANCHOR_KEY);
          frameRef.current = {
            x: sane ? (saved as { x: number; y: number }).x : px,
            y: sane ? (saved as { x: number; y: number }).y : py,
            w: pw,
            h: ph,
          };
        }

        const cur = frameRef.current;
        const size = bubble ? PET_SIZE.bubble : PET_SIZE.base;
        const nw = Math.round(size.w * sf);
        const nh = Math.round(size.h * sf);
        const nx = cur.x + cur.w - nw;
        const ny = cur.y + cur.h - nh;
        await invoke("pet_set_frame", { x: nx, y: ny, width: size.w, height: size.h });
        frameRef.current = { x: nx, y: ny, w: nw, h: nh };
      } catch {
        /* 拿不到度量就保持原样 */
      }
    })();
  }, [bubble, invoke]);

  // 气泡 8s 自动收
  useEffect(() => {
    if (!bubble) return;
    const t = window.setTimeout(() => setBubble(null), BUBBLE_MS);
    return () => window.clearTimeout(t);
  }, [bubble]);

  // idle 时每 4.5~9s 插一次眨眼 / 歪头（一次性动作，播完回基础循环）
  useEffect(() => {
    if (state !== "idle") return;
    let hide = 0;
    const loop = window.setInterval(
      () => {
        setOneshot(Math.random() < 0.65 ? "blink" : "tilt");
        setOneshotTick((v) => v + 1);
        hide = window.setTimeout(() => setOneshot(null), ONESHOT_MS);
      },
      4500 + Math.random() * 4500,
    );
    return () => {
      window.clearInterval(loop);
      window.clearTimeout(hide);
    };
  }, [state]);

  // 交互：按下 → 看有没有真的移动 → 移动了才启动原生拖拽；没移动就是单击
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragRef.current = { x: e.screenX, y: e.screenY, active: true, dragging: false };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const st = dragRef.current;
    if (!st.active || st.dragging) return;
    if (Math.abs(e.screenX - st.x) + Math.abs(e.screenY - st.y) < 5) return;
    st.dragging = true;
    void invoke?.("pet_start_drag")?.catch(() => {});
  };

  const onPointerUp = () => {
    const st = dragRef.current;
    const wasClick = st.active && !st.dragging;
    st.active = false;
    st.dragging = false;

    if (wasClick) {
      void invoke?.("pet_focus_main")?.catch(() => {});
      setBounce(true);
      window.setTimeout(() => setBounce(false), 420);
      return;
    }

    // 拖动结束：以当前几何为准刷新缓存 + 存位置
    void (async () => {
      try {
        const [px, py, pw, ph, sf] = await invoke!<Metrics>("pet_metrics");
        scaleRef.current = sf;
        frameRef.current = { x: px, y: py, w: pw, h: ph };
        localStorage.setItem(PET_ANCHOR_KEY, JSON.stringify({ x: px, y: py }));
      } catch {
        /* ignore */
      }
    })();
  };

  const onPointerCancel = () => {
    dragRef.current.active = false;
    dragRef.current.dragging = false;
  };

  return (
    <div
      className="pet-window"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      title="点我叫出主窗口 · 拖我可以挪位置"
    >
      {bubble && (
        <div className="pet-bubble">
          <div className="pet-bubble-title">{bubble.title}</div>
          {bubble.body && <div className="pet-bubble-body">{bubble.body}</div>}
        </div>
      )}
      <div className={`pet-body${bounce ? " pet-bounce" : ""}`}>
        <span className={`pet-stage pet-${state}`}>
          <PetSprite state={state} oneshot={oneshot} tick={oneshotTick} />
        </span>
        {badge > 0 && <span className="pet-badge">{badge > 9 ? "9+" : badge}</span>}
      </div>
    </div>
  );
}
