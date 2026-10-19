import { useEffect, useState } from "react";
import {
  BUBBLE_STATES,
  PET_POS_KEY,
  PET_SIZE,
  PET_STATE_KEY,
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

  // 有气泡时把窗口撑大（锚定右下角），收起时缩回本体大小
  useEffect(() => {
    if (!invoke) return;
    const s = bubble ? PET_SIZE.bubble : PET_SIZE.base;
    void invoke("pet_resize", { width: s.w, height: s.h }).catch(() => {});
  }, [bubble, invoke]);

  // 恢复上次位置
  useEffect(() => {
    if (!invoke) return;
    const saved = localStorage.getItem(PET_POS_KEY);
    if (!saved) return;
    try {
      const p = JSON.parse(saved) as { x?: number; y?: number };
      if (typeof p.x === "number" && typeof p.y === "number") {
        void invoke("pet_set_position", { x: p.x, y: p.y }).catch(() => {});
      }
    } catch {
      /* 脏数据忽略 */
    }
  }, [invoke]);

  // 按下：先试拖动；松手后若窗口没动过，就当成单击
  const onPointerDown = async () => {
    if (!invoke) return;
    const before = await invoke<[number, number]>("pet_position").catch(() => null);
    await invoke("pet_start_drag").catch(() => {});
    const after = await invoke<[number, number]>("pet_position").catch(() => null);
    if (!after) return;
    const moved = before ? Math.abs(after[0] - before[0]) + Math.abs(after[1] - before[1]) > 3 : true;
    if (moved) {
      try {
        localStorage.setItem(PET_POS_KEY, JSON.stringify({ x: after[0], y: after[1] }));
      } catch {
        /* ignore */
      }
    } else {
      void invoke("pet_focus_main").catch(() => {});
    }
  };

  return (
    <div className="pet-window" onPointerDown={onPointerDown} title="点我叫出主窗口 · 拖我可以挪位置">
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
