import { useEffect, useRef, useState } from "react";
import {
  BUBBLE_STATES,
  PET_ANCHOR_KEY,
  PET_STATE_KEY,
  PET_SIZE,
  type PetPayload,
  type PetState,
} from "@/lib/petBridge";
import idleImg from "@/assets/pet/idle.png";
import workingImg from "@/assets/pet/working.png";
import doneImg from "@/assets/pet/done.png";
import alertImg from "@/assets/pet/alert.png";
import errorImg from "@/assets/pet/error.png";

/** 5 个姿态：AI 生成的客服柴犬（与 App 图标同一角色），已去背景 */
const PET_IMG: Record<PetState, string> = {
  idle: idleImg,
  working: workingImg,
  done: doneImg,
  alert: alertImg,
  error: errorImg,
};

type TauriGlobal = {
  core?: { invoke?: <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
};

const BUBBLE_MS = 8000;

/** 读主窗口发布的桌宠状态 */
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

/** 桌宠窗口（label = "pet"）。
 *
 *  - 状态从 localStorage 读（主窗口写、storage 事件送达）
 *  - 单击：把主窗口叫到前台；拖动：系统原生拖动，松手存位置
 *  - 气泡只在 alert / done / error 弹，并临时把窗口撑大再缩回
 */
export function PetWindow() {
  // 初值直接从 localStorage 读（lazy initializer，避免在 effect 里同步 setState）
  const initial = readPayload();
  const [state, setState] = useState<PetState>(initial?.state ?? "idle");
  const [badge, setBadge] = useState(initial?.badge ?? 0);
  const [bubble, setBubble] = useState<{ title: string; body?: string } | null>(
    initial && BUBBLE_STATES.includes(initial.state) && initial.title
      ? { title: initial.title, body: initial.body }
      : null,
  );
  const invoke = (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__?.core?.invoke;

  // 跨窗口 storage 事件（初值已在 useState 里读好）
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
      if (BUBBLE_STATES.includes(p.state) && p.title) {
        setBubble({ title: p.title, body: p.body });
      } else {
        setBubble(null);
      }
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === PET_STATE_KEY) apply(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // 气泡 8s 自动收
  useEffect(() => {
    if (!bubble) return;
    const t = window.setTimeout(() => setBubble(null), BUBBLE_MS);
    return () => window.clearTimeout(t);
  }, [bubble]);

  // 锚点：窗口右下角（物理像素）。窗口大小随气泡变，但锚点不动 ——
  // 位置一律由「锚点 - 当前尺寸」推出来，避免和别的改位置操作抢。
  const anchorRef = useRef<{ x: number; y: number } | null>(null);
  const scaleRef = useRef(1);

  useEffect(() => {
    if (!invoke) return;
    void (async () => {
      try {
        const [px, py, pw, ph, sf] = await invoke<[number, number, number, number, number]>("pet_metrics");
        scaleRef.current = sf;
        if (!anchorRef.current) {
          let saved: { x: number; y: number } | null = null;
          try {
            saved = JSON.parse(localStorage.getItem(PET_ANCHOR_KEY) ?? "null") as { x: number; y: number } | null;
          } catch {
            /* 脏数据忽略 */
          }
          anchorRef.current = saved ?? { x: px + pw, y: py + ph };
        }
        const size = bubble ? PET_SIZE.bubble : PET_SIZE.base;
        const w = Math.round(size.w * sf);
        const h = Math.round(size.h * sf);
        await invoke("pet_set_frame", {
          x: anchorRef.current.x - w,
          y: anchorRef.current.y - h,
          width: size.w,
          height: size.h,
        });
      } catch {
        /* 忽略：拿不到度量就保持原样 */
      }
    })();
  }, [bubble, invoke]);

  // 交互：按下 → 看有没有真的移动 → 移动了才启动原生拖拽；没移动就是单击
  // （之前是按下就无条件 pet_start_drag，macOS 上原生拖拽会把这次点击吃掉，
  //   而且一旦 pet_position 取不到就永远不响应点击 —— 两个原因叠加就是"点了没反应"）
  const dragRef = useRef<{ x: number; y: number; active: boolean; dragging: boolean }>({
    x: 0,
    y: 0,
    active: false,
    dragging: false,
  });

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    void invoke?.("pet_debug", { msg: `pointerdown ${Math.round(e.screenX)},${Math.round(e.screenY)}` })?.catch(() => {});
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
    void invoke?.("pet_debug", { msg: `pointerup click=${wasClick} dragging=${st.dragging}` })?.catch(() => {});
    if (wasClick) {
      void invoke?.("pet_focus_main")?.catch(() => {});
      return;
    }
    // 拖动结束：以当前窗口右下角刷新锚点，下次启动按它复位
    void (async () => {
      try {
        const [px, py, pw, ph, sf] = await invoke!("pet_metrics");
        scaleRef.current = sf;
        const anchor = { x: px + pw, y: py + ph };
        anchorRef.current = anchor;
        localStorage.setItem(PET_ANCHOR_KEY, JSON.stringify(anchor));
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
      <div className="pet-body">
        <img className={`pet-img pet-${state}`} src={PET_IMG[state]} alt="" draggable={false} />
        {badge > 0 && <span className="pet-badge">{badge > 9 ? "9+" : badge}</span>}
      </div>
    </div>
  );
}
