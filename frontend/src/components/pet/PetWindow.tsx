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
import { animationOf, frameInterval, type LoadedPack } from "@/lib/petPack";
import { BUILTIN_PACK, loadPack, selectedPackId } from "@/lib/petPackStore";

type TauriGlobal = {
  core?: { invoke?: <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
};

/** 主窗口 → 桌宠的度量：[x, y, w, h, scale, workX, workY, workW, workH]（物理像素） */
type Metrics = [number, number, number, number, number, number, number, number, number];

/** 一个动作引用：真正播什么由资源包（pet.json + atlas.webp）决定 */
type Clip = { name: string; hold?: number };

const BUBBLE_MS = 8000;
/** 空闲多久打哈欠准备睡 */
const SLEEP_AFTER_MS = 3 * 60 * 1000;
/** 舞台基准边长（取自资源包，缺省 132）；渲染时按当前包实时取 */
const DEFAULT_STAGE = 132;

const BASE: Record<PetState, Clip> = {
  idle: { name: "idle" },
  working: { name: "run" },
  done: { name: "tail" },
  alert: { name: "alert" },
  error: { name: "error" },
};

/** 一次性小动作：播完回基础循环 */
const ONESHOTS: Record<string, { clip: Clip; hold: number }> = {
  clap: { clip: { name: "clap" }, hold: 1000 },
  phone: { clip: { name: "phone" }, hold: 1800 },
  stretch: { clip: { name: "stretch" }, hold: 1600 },
  tilt: { clip: { name: "tilt" }, hold: 1400 },
  yawn: { clip: { name: "yawn" }, hold: 1600 },
};

const SLEEP_CLIP: Clip = { name: "sleep" };

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

/** 系统「减少动态效果」：像 ChatGPT 宠物那样退回**静帧**，而不是停在动画最后一帧。
 *  全局那条 `animation-duration: 0.01ms !important` 会把 sprite 直接跳到末帧
 *  （可能是抬腿的姿势），所以这里单独处理。 */
function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** 播放一个动作：从 atlas 里按 (row, col) 取格，JS 控帧。
 *
 *  为什么不再用 CSS `steps()`：自定义宠物的帧数是任意值，CSS 得为每个帧数
 *  预生成 keyframes；JS 逐帧只需改 background-position，且能精确控制单帧时长。
 */
function ClipView({
  pack,
  clip,
  once,
  playKey,
}: {
  pack: LoadedPack;
  clip: Clip;
  once: boolean;
  playKey: number;
}) {
  const anim = animationOf(pack.pack, clip.name) ?? pack.pack.animations.idle;
  const [frame, setFrame] = useState(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    const interval = frameInterval(anim);
    // 减少动态效果 / 单帧动作 / fps=0 → 停在第一帧（ChatGPT 宠物同款处理）
    if (reduced || anim.frames <= 1 || interval <= 0) return undefined;
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const tick = (now: number) => {
      acc += now - last;
      last = now;
      if (acc >= interval) {
        const advance = Math.floor(acc / interval);
        acc -= advance * interval;
        setFrame((f) => {
          const next = f + advance;
          return once ? Math.min(anim.frames - 1, next) : next % anim.frames;
        });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [anim, once, reduced, playKey]);

  const stage = pack.pack.stage ?? DEFAULT_STAGE;
  const { cell, cols, rows } = pack.pack;
  const shown = Math.min(frame, anim.frames - 1);
  return (
    <span
      key={`${pack.pack.id}-${clip.name}-${playKey}`}
      className="pet-sprite"
      style={{
        backgroundImage: `url(${pack.sheetUrl})`,
        backgroundSize: `${stage * cols}px ${stage * rows}px`,
        backgroundPosition: `${-shown * stage}px ${-anim.row * stage}px`,
        // 图集缩放到舞台：atlas 单格 cell px → 舞台 STAGE px
        imageRendering: cell === stage ? undefined : "auto",
      }}
    />
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
  /** 当前生效的宠物包：默认内置，选中自定义包后异步替换 */
  const [pack, setPack] = useState<LoadedPack>(BUILTIN_PACK);
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
  const scale = size.base.w / DEFAULT_STAGE;

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

  // 加载选中的宠物包：失败自动回退内置（loadPack 内部已经兜底）
  useEffect(() => {
    let alive = true;
    const sync = () => {
      void loadPack(selectedPackId()).then((next) => {
        if (!alive) return;
        setPack(next);
        const img = new Image();
        img.src = next.sheetUrl; // 预载，避免首帧闪空
      });
    };
    sync();
    // 设置页切换后立刻生效：同窗口改 localStorage 用 storage 事件收不到，
    // 这里轮询一个轻量标记（250ms，开销可忽略）
    let last = selectedPackId();
    const timer = window.setInterval(() => {
      const now = selectedPackId();
      if (now !== last) {
        last = now;
        sync();
      }
    }, 250);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  // 空闲时预热图集：所有动作共用一张图，只需要预载它（避免第一次切换时闪空窗）
  useEffect(() => {
    const preload = () => {
      const img = new Image();
      img.src = pack.sheetUrl;
    };
    const t = window.setTimeout(preload, 2500);
    return () => window.clearTimeout(t);
  }, [pack.sheetUrl]);

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
    ? { name: "walk" }
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
          <ClipView
            key={`${clip.name}-${playKey}`}
            pack={pack}
            clip={clip}
            once={Boolean(oneshot) || dragging}
            playKey={playKey}
          />
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
