import { useEffect, useRef, useState } from "react";
import {
  BUBBLE_STATES,
  PET_ANCHOR_KEY,
  PET_ENABLED_KEY,
  PET_QUIET_KEY,
  PET_SIZE_KEY,
  PET_SIZES,
  PET_STATE_KEY,
  type PetPayload,
  type PetState,
} from "@/lib/petBridge";
import breatheSrc from "@/assets/pet/loop-idle-breathe.webp";
import walkSrc from "@/assets/pet/loop-walk.webp";
import runSrc from "@/assets/pet/loop-run.webp";
import tailSrc from "@/assets/pet/loop-tail.webp";
import alert1 from "@/assets/pet/alert-1.webp";
import alert2 from "@/assets/pet/alert-2.webp";
import error1 from "@/assets/pet/error-1.webp";
import error2 from "@/assets/pet/error-2.webp";
import clap1 from "@/assets/pet/clap-1.webp";
import clap2 from "@/assets/pet/clap-2.webp";
import phone1 from "@/assets/pet/phone-1.webp";
import stretch1 from "@/assets/pet/stretch-1.webp";
import tilt1 from "@/assets/pet/tilt-1.webp";
import yawn1 from "@/assets/pet/yawn-1.webp";
import sleep1 from "@/assets/pet/sleep-1.webp";

type TauriGlobal = {
  core?: { invoke?: <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
};

/** 主窗口 → 桌宠的度量：[x, y, w, h, scale, workX, workY, workW, workH]（物理像素） */
type Metrics = [number, number, number, number, number, number, number, number, number];

/** 一段可播放的内容：sprite sheet（逐帧，可循环）或静态帧序列（交叉淡入） */
type Clip =
  | { kind: "sprite"; src: string; frames: number; ms: number }
  | { kind: "stills"; frames: string[]; ms: number };

const BUBBLE_MS = 8000;
/** 空闲多久打哈欠准备睡 */
const SLEEP_AFTER_MS = 3 * 60 * 1000;
/** 舞台基准边长（sprite 的 px 尺寸按这个来，靠 transform 缩放到档位） */
const STAGE = 132;

const LOOPS = {
  // idle 用待机循环的 8 帧（呼吸下沉→回正→半闭眼→全闭眼→睁眼→歪头）
  // 用满素材帧数（补间也上）：待机 9、走路 12、跑步 13、摇尾 12。
  // 每帧时长：待机 267ms（呼吸慢动作）、走路 65ms、跑步 54ms、摇尾 68ms。
  breathe: { kind: "sprite", src: breatheSrc, frames: 9, ms: 2400 } as Clip,
  walk: { kind: "sprite", src: walkSrc, frames: 12, ms: 780 } as Clip,
  run: { kind: "sprite", src: runSrc, frames: 13, ms: 700 } as Clip,
  tail: { kind: "sprite", src: tailSrc, frames: 12, ms: 820 } as Clip,
};

/** 各状态的基础循环 */
const BASE: Record<PetState, Clip> = {
  idle: LOOPS.breathe,
  working: LOOPS.run,
  done: LOOPS.tail,
  alert: { kind: "stills", frames: [alert1, alert2], ms: 900 },
  error: { kind: "stills", frames: [error1, error2], ms: 1400 },
};

/** 一次性小动作：播完回基础循环 */
const ONESHOTS: Record<string, { clip: Clip; hold: number }> = {
  clap: { clip: { kind: "stills", frames: [clap1, clap2], ms: 380 }, hold: 1000 },
  phone: { clip: { kind: "stills", frames: [phone1], ms: 0 }, hold: 1800 },
  stretch: { clip: { kind: "stills", frames: [stretch1], ms: 0 }, hold: 1600 },
  tilt: { clip: { kind: "stills", frames: [tilt1], ms: 0 }, hold: 1400 },
  yawn: { clip: { kind: "stills", frames: [yawn1], ms: 0 }, hold: 1600 },
};

const SLEEP_CLIP: Clip = { kind: "stills", frames: [sleep1], ms: 0 };

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

function readNumber(key: string, fallback: number): number {
  const raw = localStorage.getItem(key);
  const n = raw == null ? NaN : Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

/** 播放一段 Clip：sprite 用 CSS steps()，stills 用透明度交叉淡入 */
function ClipView({ clip, once, playKey }: { clip: Clip; once: boolean; playKey: number }) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (clip.kind !== "stills" || clip.frames.length < 2 || clip.ms <= 0) return;
    const t = window.setInterval(() => setIdx((i) => (i + 1) % clip.frames.length), clip.ms);
    return () => window.clearInterval(t);
  }, [clip]);

  if (clip.kind === "sprite") {
    return (
      <span
        key={`${clip.src}-${playKey}`}
        className="pet-sprite"
        style={{
          backgroundImage: `url(${clip.src})`,
          backgroundSize: `${STAGE * clip.frames}px ${STAGE}px`,
          animation: `pet-strip-${clip.frames} ${clip.ms}ms steps(${clip.frames}) ${once ? 1 : "infinite"}`,
        }}
      />
    );
  }
  return (
    <>
      {clip.frames.map((src, i) => (
        <span
          key={src}
          className={`pet-frame${i === idx ? " on" : ""}`}
          style={{ backgroundImage: `url(${src})` }}
        />
      ))}
    </>
  );
}

/** 桌宠窗口（label = "pet"）。
 *
 *  三层播放：基础循环（按状态） / 一次性动作（点击、闲时随机） / 睡眠。
 *  状态从 localStorage 读（主窗口写、storage 事件送达）。
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
  const [quiet, setQuiet] = useState(() => readNumber(PET_QUIET_KEY, 0) === 1);
  const [sizeIdx, setSizeIdx] = useState(() => Math.min(2, Math.max(0, readNumber(PET_SIZE_KEY, 1))));
  const [oneshot, setOneshot] = useState<{ key: string; hold: number } | null>(null);
  const [playKey, setPlayKey] = useState(0);
  const [bounce, setBounce] = useState(false);
  const [sleeping, setSleeping] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [menu, setMenu] = useState(false);
  /** 首次出现时给一次引导（只显示一次） */
  const [guide, setGuide] = useState(() => localStorage.getItem("pet.guide") !== "1");

  const invoke = (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__?.core?.invoke;

  const frameRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const scaleRef = useRef(1);
  const dragRef = useRef({ x: 0, y: 0, active: false, dragging: false });
  const lastActiveRef = useRef(0);
  const lastRawRef = useRef<string | null>(null);

  const size = PET_SIZES[sizeIdx];
  const scale = size.base.w / STAGE;

  /** 播一次小动作 */
  const play = (key: string) => {
    const def = ONESHOTS[key];
    if (!def) return;
    setSleeping(false);
    setOneshot({ key, hold: def.hold });
    setPlayKey((v) => v + 1);
    window.setTimeout(() => setOneshot((cur) => (cur?.key === key ? null : cur)), def.hold);
  };

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
      lastActiveRef.current = Date.now();
      setSleeping(false);
      if (p.state !== "working") setOneshot(null);
      if (BUBBLE_STATES.includes(p.state) && p.title && !quiet) {
        setBubble({ title: p.title, body: p.body });
      } else if (!BUBBLE_STATES.includes(p.state)) {
        setBubble(null);
      }
    };
    lastRawRef.current = localStorage.getItem(PET_STATE_KEY);
    let seen = lastRawRef.current;
    const onStorage = (e: StorageEvent) => {
      if (e.key === PET_STATE_KEY) apply(e.newValue);
      if (e.key === PET_QUIET_KEY) setQuiet(readNumber(PET_QUIET_KEY, 0) === 1);
      if (e.key === PET_SIZE_KEY) setSizeIdx(Math.min(2, Math.max(0, readNumber(PET_SIZE_KEY, 1))));
    };
    // 兜底轮询：storage 事件偶尔会漏（窗口休眠/重载），2s 对一次就够
    const poll = window.setInterval(() => {
      const raw = localStorage.getItem(PET_STATE_KEY);
      if (raw && raw !== seen) {
        seen = raw;
        apply(raw);
      }
    }, 2000);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.clearInterval(poll);
    };
  }, [quiet]);

  // 空闲时预热其余素材：避免第一次切到某状态时闪一下空窗
  useEffect(() => {
    const srcs = [
      breatheSrc, walkSrc, runSrc, tailSrc,
      alert1, alert2, error1, error2,
      clap1, clap2, phone1, stretch1, tilt1, yawn1, sleep1,
    ];
    const preload = () => srcs.forEach((src) => { const img = new Image(); img.src = src; });
    const t = window.setTimeout(preload, 2500);
    return () => window.clearTimeout(t);
  }, []);

  // 尺寸：随气泡/档位切换。位置按「右下角不动」由缓存推出。
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
        // 气泡撑到气泡尺寸；右键菜单再高一档（菜单放右上、柴犬留右下，互不遮挡）
        const target = menu ? { w: size.bubble.w, h: 300 } : bubble || guide ? size.bubble : size.base;
        const nw = Math.round(target.w * sf);
        const nh = Math.round(target.h * sf);
        const nx = cur.x + cur.w - nw;
        const ny = cur.y + cur.h - nh;
        await invoke("pet_set_frame", { x: nx, y: ny, width: target.w, height: target.h });
        frameRef.current = { x: nx, y: ny, w: nw, h: nh };
      } catch {
        /* 拿不到度量就保持原样 */
      }
    })();
  }, [bubble, guide, menu, invoke, size]);

  // 引导气泡：10s 后自动收，并记下已看过
  useEffect(() => {
    if (!guide) return;
    const t = window.setTimeout(() => {
      setGuide(false);
      localStorage.setItem("pet.guide", "1");
    }, 10000);
    return () => window.clearTimeout(t);
  }, [guide]);

  // 记录"最后一次活动"的起点
  useEffect(() => {
    lastActiveRef.current = Date.now();
  }, []);

  // 气泡 8s 自动收
  useEffect(() => {
    if (!bubble) return;
    const t = window.setTimeout(() => setBubble(null), BUBBLE_MS);
    return () => window.clearTimeout(t);
  }, [bubble]);

  // 闲时随机小动作；空闲够久就打哈欠然后睡
  useEffect(() => {
    if (state !== "idle" || menu) return;
    const loop = window.setInterval(
      () => {
        if (Date.now() - lastActiveRef.current > SLEEP_AFTER_MS) {
          setSleeping(true);
          return;
        }
        const pool = ["phone", "stretch", "tilt", "yawn", "clap"];
        play(pool[Math.floor(Math.random() * pool.length)]);
      },
      18000 + Math.random() * 17000,
    );
    return () => window.clearInterval(loop);
  }, [state, menu]);

  // 交互：按下 → 看有没有真的移动 → 移动了才启动原生拖拽；没移动就是单击
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragRef.current = { x: e.screenX, y: e.screenY, active: true, dragging: false };
    lastActiveRef.current = Date.now();
    setSleeping(false);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const st = dragRef.current;
    if (!st.active || st.dragging) return;
    if (Math.abs(e.screenX - st.x) + Math.abs(e.screenY - st.y) < 5) return;
    st.dragging = true;
    setDragging(true);
    setOneshot(null);
    void invoke?.("pet_start_drag")?.catch(() => {});
  };

  const onPointerUp = () => {
    const st = dragRef.current;
    const wasClick = st.active && !st.dragging;
    st.active = false;
    st.dragging = false;
    setDragging(false);

    if (wasClick) {
      void invoke?.("pet_focus_main")?.catch(() => {});
      setBounce(true);
      window.setTimeout(() => setBounce(false), 420);
      play("clap");
      return;
    }

    void (async () => {
      try {
        const [px, py, pw, ph] = await invoke!<Metrics>("pet_metrics");
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
    setDragging(false);
  };

  /** clip 身份：变化时让舞台重挂，触发淡入（侧面/正面切换不至于硬跳） */
  const clipKey = dragging ? "walk" : oneshot ? oneshot.key : sleeping ? "sleep" : state;

  const clip: Clip = dragging
    ? LOOPS.walk
    : oneshot
      ? ONESHOTS[oneshot.key].clip
      : sleeping
        ? SLEEP_CLIP
        : BASE[state];

  return (
    <div
      className="pet-window"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onContextMenu={(e) => {
        e.preventDefault();
        setMenu((v) => !v);
      }}
      title="单击叫我出来 · 拖动挪位置 · 右键设置"
    >
      {(guide || bubble) && (
        <div className="pet-bubble">
          <div className="pet-bubble-title">{guide ? "👋 我在这儿" : bubble?.title}</div>
          <div className="pet-bubble-body">
            {guide ? "点我叫出主应用 · 拖动挪位置 · 右键设置" : bubble?.body}
          </div>
        </div>
      )}

      <div
        className={`pet-body${bounce ? " pet-bounce" : ""}`}
        style={{ width: size.base.w, height: size.base.h }}
      >
        <span
          key={clipKey}
          className={`pet-stage pet-${state}`}
          style={{ transform: `scale(${scale})` }}
        >
          <ClipView clip={clip} once={Boolean(oneshot) || dragging} playKey={playKey} />
        </span>
        {badge > 0 && <span className="pet-badge">{badge > 9 ? "9+" : badge}</span>}
      </div>

      {menu && (
        <div className="pet-menu" onPointerDown={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="pet-menu-item"
            onClick={() => {
              const next = !quiet;
              setQuiet(next);
              localStorage.setItem(PET_QUIET_KEY, next ? "1" : "0");
              if (next) setBubble(null);
              setMenu(false);
            }}
          >
            {quiet ? "取消安静模式" : "安静模式（只出角标）"}
          </button>
          <button
            type="button"
            className="pet-menu-item"
            onClick={() => {
              const next = (sizeIdx + 1) % 3;
              setSizeIdx(next);
              localStorage.setItem(PET_SIZE_KEY, String(next));
              setMenu(false);
            }}
          >
            大小：{["小", "中", "大"][sizeIdx]}（点击切换）
          </button>
          <button
            type="button"
            className="pet-menu-item"
            onClick={() => {
              localStorage.removeItem(PET_ANCHOR_KEY);
              setMenu(false);
              void invoke?.("pet_set_visible", { visible: false })?.catch(() => {});
              window.setTimeout(() => void invoke?.("pet_set_visible", { visible: true })?.catch(() => {}), 150);
            }}
          >
            重置位置
          </button>
          <button
            type="button"
            className="pet-menu-item"
            onClick={() => {
              localStorage.setItem(PET_ENABLED_KEY, "0");
              void invoke?.("pet_set_visible", { visible: false })?.catch(() => {});
              setMenu(false);
            }}
          >
            隐藏桌宠（托盘可恢复）
          </button>
        </div>
      )}
    </div>
  );
}
