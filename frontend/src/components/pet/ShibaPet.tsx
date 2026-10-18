/** 趴姿客服柴犬 —— 桌宠本体。
 *
 *  画布 160×132（宽扁，符合趴姿），窗口按 132×108 显示。
 *  配色取样自 App 图标 `icons/128x128@2x.png`，与图标同一个角色（耳麦 + 领结）。
 *  5 个状态共用同一套轮廓，只换眼睛 / 耳朵 / 嘴 / 尾巴 / 附加件。
 */

export type PetState = "idle" | "working" | "done" | "alert" | "error";

const C = { tan: "#EEBF84", dark: "#604C38", cream: "#FDF7ED" } as const;

/** 五官都围绕头的中心 (80, 50) */
function Eyes({ state }: { state: PetState }) {
  switch (state) {
    case "idle":
      return (
        <>
          <path d="M56 45 q5 -6 10 0" stroke={C.dark} strokeWidth={3.2} fill="none" strokeLinecap="round" />
          <path d="M94 45 q5 -6 10 0" stroke={C.dark} strokeWidth={3.2} fill="none" strokeLinecap="round" />
        </>
      );
    case "done":
      return (
        <>
          <path d="M55 47 q6 -8 12 0" stroke={C.dark} strokeWidth={3.4} fill="none" strokeLinecap="round" />
          <path d="M93 47 q6 -8 12 0" stroke={C.dark} strokeWidth={3.4} fill="none" strokeLinecap="round" />
        </>
      );
    case "working":
      return (
        <>
          <ellipse cx={61} cy={45} rx={4.2} ry={4.8} fill={C.dark} />
          <ellipse cx={99} cy={45} rx={4.2} ry={4.8} fill={C.dark} />
          <circle cx={62.4} cy={43} r={1.4} fill="#fff" />
          <circle cx={100.4} cy={43} r={1.4} fill="#fff" />
        </>
      );
    case "alert":
      return (
        <>
          <circle cx={61} cy={44} r={5.6} fill="#fff" stroke={C.dark} strokeWidth={2} />
          <circle cx={99} cy={44} r={5.6} fill="#fff" stroke={C.dark} strokeWidth={2} />
          <circle cx={61} cy={44} r={2.2} fill={C.dark} />
          <circle cx={99} cy={44} r={2.2} fill={C.dark} />
        </>
      );
    case "error":
      return (
        <>
          <path d="M56 44 q5 6 10 2" stroke={C.dark} strokeWidth={3.2} fill="none" strokeLinecap="round" />
          <path d="M94 46 q5 -4 10 -2" stroke={C.dark} strokeWidth={3.2} fill="none" strokeLinecap="round" />
          <path d="M55 35 q5 1 9 4" stroke={C.dark} strokeWidth={2.6} strokeLinecap="round" />
          <path d="M105 35 q-5 1 -9 4" stroke={C.dark} strokeWidth={2.6} strokeLinecap="round" />
        </>
      );
  }
}

function Mouth({ state }: { state: PetState }) {
  switch (state) {
    case "idle":
      return <path d="M74 66 q6 3.6 12 0" stroke={C.dark} strokeWidth={2.2} fill="none" strokeLinecap="round" />;
    case "done":
      return (
        <>
          <path d="M71 64 q9 9 18 0" stroke={C.dark} strokeWidth={2.6} fill="none" strokeLinecap="round" />
          <ellipse cx={80} cy={69} rx={3.6} ry={2.4} fill="#e08a8a" />
        </>
      );
    case "working":
      return <path d="M73 67 h14" stroke={C.dark} strokeWidth={2.2} strokeLinecap="round" />;
    case "alert":
      return <ellipse cx={80} cy={68} rx={3} ry={3.8} fill={C.dark} />;
    case "error":
      return <path d="M73 69 q7 -5 14 0" stroke={C.dark} strokeWidth={2.4} fill="none" strokeLinecap="round" />;
  }
}

const EAR_L: Record<PetState, string> = {
  idle: "M57 31 L47 2 L78 20",
  working: "M58 28 L49 -1 L80 18",
  done: "M57 29 L44 2 L77 18",
  alert: "M59 26 L51 -2 L81 18",
  error: "M56 33 L39 17 L74 21",
};
const EAR_R: Record<PetState, string> = {
  idle: "M103 31 L113 2 L82 20",
  working: "M102 28 L111 -1 L80 18",
  done: "M103 29 L116 2 L83 18",
  alert: "M101 26 L109 -2 L79 18",
  error: "M104 33 L121 17 L86 21",
};
const EAR_LI: Record<PetState, string> = {
  idle: "M58 27 L51 8 L75 21",
  working: "M59 24 L53 5 L77 19",
  done: "M58 25 L48 8 L74 19",
  alert: "M60 22 L55 4 L78 19",
  error: "M57 29 L45 18 L71 21",
};
const EAR_RI: Record<PetState, string> = {
  idle: "M102 27 L109 8 L85 21",
  working: "M101 24 L107 5 L83 19",
  done: "M102 25 L112 8 L86 19",
  alert: "M100 22 L105 4 L82 19",
  error: "M103 29 L115 18 L89 21",
};

function Ears({ state }: { state: PetState }) {
  return (
    <>
      <path d={EAR_L[state]} fill={C.tan} stroke={C.dark} strokeWidth={3} strokeLinejoin="round" />
      <path d={EAR_LI[state]} fill={C.dark} opacity={0.9} />
      <path d={EAR_R[state]} fill={C.tan} stroke={C.dark} strokeWidth={3} strokeLinejoin="round" />
      <path d={EAR_RI[state]} fill={C.dark} opacity={0.9} />
    </>
  );
}

/** 尾巴：done 摇 / alert 炸毛竖起 / error 垂地 */
function Tail({ state }: { state: PetState }) {
  const d =
    state === "error"
      ? "M120 102 q18 4 22 14"
      : state === "alert"
        ? "M120 84 q20 -16 26 -34"
        : "M122 90 q18 -8 22 -26";
  const tip = state === "error" ? [143, 117] : state === "alert" ? [147, 48] : [145, 62];
  return (
    <>
      <path
        d={d}
        className={state === "done" ? "pet-tail" : undefined}
        stroke={C.tan}
        strokeWidth={14}
        fill="none"
        strokeLinecap="round"
      />
      <path d={d} stroke={C.dark} strokeWidth={3} fill="none" strokeLinecap="round" opacity={0.26} transform="translate(0,7)" />
      <circle cx={tip[0]} cy={tip[1]} r={7.5} fill={C.cream} stroke={C.dark} strokeWidth={2.6} />
    </>
  );
}

function Extras({ state }: { state: PetState }) {
  switch (state) {
    case "working":
      return (
        <g fontSize={14} fill={C.dark} fontWeight={800}>
          <text className="pet-d1" x={124} y={40}>·</text>
          <text className="pet-d2" x={130} y={40}>·</text>
          <text className="pet-d3" x={136} y={40}>·</text>
        </g>
      );
    case "alert":
      return (
        <>
          <path d="M106 30 q4 6 0 8 q-4 -2 0 -8" fill="#9ad4f7" stroke="#4c9fd6" strokeWidth={1.2} />
          <text x={124} y={22} fontSize={16} fill="#f87171" fontWeight={800}>!</text>
        </>
      );
    case "done":
      return (
        <g>
          <circle cx={126} cy={22} r={8.5} fill="#4ade80" />
          <path d="M122.5 22 l2.8 2.8 4.6 -5.4" stroke="#0f1115" strokeWidth={2.3} fill="none" strokeLinecap="round" />
        </g>
      );
    case "error":
      return <text x={120} y={26} fontSize={16} fill={C.dark} fontWeight={700} opacity={0.65}>…</text>;
    default:
      return null;
  }
}

export function ShibaPet({ state }: { state: PetState }) {
  return (
    <svg viewBox="0 0 160 132" fill="none" xmlns="http://www.w3.org/2000/svg" className={`pet-svg pet-${state}`}>
      {/* 地面投影：透明桌面上也站得住 */}
      <ellipse cx={80} cy={123} rx={52} ry={6} fill="#000" opacity={0.13} />
      <Tail state={state} />
      {/* 身体：趴着的「面包」 */}
      <ellipse cx={80} cy={94} rx={50} ry={27} fill={C.tan} stroke={C.dark} strokeWidth={3} />
      <ellipse cx={80} cy={101} rx={31} ry={16} fill={C.cream} />
      {/* 前爪 */}
      <rect x={47} y={106} width={27} height={12} rx={6} fill={C.cream} stroke={C.dark} strokeWidth={2.8} />
      <rect x={86} y={106} width={27} height={12} rx={6} fill={C.cream} stroke={C.dark} strokeWidth={2.8} />
      <path
        d="M57 112 v4 M64 112 v4 M96 112 v4 M103 112 v4"
        stroke={C.dark}
        strokeWidth={1.8}
        strokeLinecap="round"
        opacity={0.5}
      />
      <Ears state={state} />
      {/* 头 */}
      <ellipse cx={80} cy={50} rx={33} ry={28} fill={C.tan} stroke={C.dark} strokeWidth={3} />
      <circle cx={62} cy={62} r={15.5} fill={C.cream} />
      <circle cx={98} cy={62} r={15.5} fill={C.cream} />
      <ellipse cx={80} cy={72} rx={18} ry={11.5} fill={C.cream} />
      <path d="M80 37 q-5 12 -5 18 h10 q0 -6 -5 -18 z" fill={C.tan} />
      <Eyes state={state} />
      <path d="M74 57 q6 -3 12 0 q0 7.5 -6 7.5 q-6 0 -6 -7.5 z" fill={C.dark} />
      <Mouth state={state} />
      {/* 耳麦 */}
      <path d="M48 36 A33 33 0 0 1 112 36" stroke={C.dark} strokeWidth={3.2} strokeLinecap="round" fill="none" />
      <rect x={99} y={31} width={13} height={20} rx={6.5} fill={C.dark} />
      <path d="M105 51 q-3 13 -17 15" stroke={C.dark} strokeWidth={2.8} fill="none" strokeLinecap="round" />
      <ellipse cx={87} cy={67} rx={4.4} ry={3.2} fill={C.dark} />
      {/* 领结 */}
      <g transform="translate(80 82)">
        <path d="M-3 0 l-11 -7 v14 z" fill={C.dark} />
        <path d="M3 0 l11 -7 v14 z" fill={C.dark} />
        <circle cx={0} cy={0} r={3.3} fill={C.dark} />
      </g>
      <Extras state={state} />
    </svg>
  );
}
