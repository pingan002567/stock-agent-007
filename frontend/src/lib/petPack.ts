/** 桌宠资源包（对齐 ChatGPT / Codex 宠物的打包方式）。
 *
 *  一个宠物 = 一个目录：
 *
 *      pet.json       元数据 + 动作表（行号 / 帧数 / fps）
 *      atlas.webp     一张图集：**行 = 动作，列 = 帧**，单格 cell×cell，未用格全透明
 *
 *  这样自定义宠物只要把两个文件放进目录即可，**不需要重新编译前端**。
 *  内置柴犬走的是同一套格式（`frontend/src/assets/pet/`），dogfooding 保证格式不会跑偏。
 */

/** 一个动作在 atlas 里的位置与播放参数 */
export interface PetAnimation {
  /** 行号（0 起） */
  row: number;
  /** 该动作用到几帧（从第 0 列开始） */
  frames: number;
  /** 目标帧率；0 = 只显示一帧（时长由调用方的 hold 决定） */
  fps: number;
}

export interface PetPack {
  id: string;
  displayName: string;
  description?: string;
  /** 单格边长（atlas 网格） */
  cell: number;
  /** 舞台显示边长（CSS px）；缺省按 132 */
  stage?: number;
  cols: number;
  rows: number;
  /** 图集文件名（同目录下） */
  spritesheet: string;
  animations: Record<string, PetAnimation>;
}

export interface LoadedPack {
  pack: PetPack;
  /** 可直接塞进 backgroundImage 的 URL（内置走打包产物，自定义走数据 URL / 文件协议） */
  sheetUrl: string;
  source: "builtin" | "custom";
  /** 自定义包的来源目录（便于界面显示与"打开目录"） */
  dir?: string;
}

/** 桌宠要能跑起来，至少得有这两个动作 */
export const REQUIRED_ANIMATIONS = ["idle", "walk"] as const;

const MAX_CELL = 1024;
const MIN_CELL = 32;

function fail(msg: string): never {
  throw new Error(`宠物包不合法：${msg}`);
}

/** 校验并补默认值。错误信息要能让做宠物的人自己看懂哪里写错了。 */
export function normalizePack(raw: unknown): PetPack {
  if (!raw || typeof raw !== "object") fail("pet.json 不是对象");
  const o = raw as Record<string, unknown>;

  const id = typeof o.id === "string" ? o.id.trim() : "";
  if (!id) fail("缺少 id");
  const displayName = typeof o.displayName === "string" ? o.displayName.trim() : id;

  const cell = Number(o.cell);
  if (!Number.isFinite(cell) || cell < MIN_CELL || cell > MAX_CELL) {
    fail(`cell 必须是 ${MIN_CELL}~${MAX_CELL} 的数字`);
  }

  const rawAnimations = o.animations;
  if (!rawAnimations || typeof rawAnimations !== "object") fail("缺少 animations");
  const animations: Record<string, PetAnimation> = {};
  for (const [name, value] of Object.entries(rawAnimations as Record<string, unknown>)) {
    const a = value as Record<string, unknown> | null;
    if (!a || typeof a !== "object") fail(`animations.${name} 不是对象`);
    const row = Number(a.row);
    const frames = Number(a.frames);
    const fps = Number(a.fps ?? 0);
    if (!Number.isInteger(row) || row < 0) fail(`animations.${name}.row 必须是非负整数`);
    if (!Number.isInteger(frames) || frames < 1) fail(`animations.${name}.frames 必须 ≥ 1`);
    if (!Number.isFinite(fps) || fps < 0) fail(`animations.${name}.fps 不能为负`);
    animations[name] = { row, frames, fps };
  }
  if (Object.keys(animations).length === 0) fail("animations 为空");
  for (const need of REQUIRED_ANIMATIONS) {
    if (!animations[need]) fail(`缺少必需动作 ${need}`);
  }

  // cols/rows 可以省略：从动作表推出来（省得做宠物的人算格子）
  const cols = Number.isFinite(Number(o.cols))
    ? Number(o.cols)
    : Math.max(...Object.values(animations).map((a) => a.frames));
  const rows = Number.isFinite(Number(o.rows))
    ? Number(o.rows)
    : Math.max(...Object.values(animations).map((a) => a.row)) + 1;
  if (!Number.isInteger(cols) || cols < 1) fail("cols 非法");
  if (!Number.isInteger(rows) || rows < 1) fail("rows 非法");
  for (const [name, a] of Object.entries(animations)) {
    if (a.row >= rows) fail(`animations.${name}.row=${a.row} 超出 rows=${rows}`);
    if (a.frames > cols) fail(`animations.${name}.frames=${a.frames} 超出 cols=${cols}`);
  }

  const spritesheet = typeof o.spritesheet === "string" && o.spritesheet ? o.spritesheet : "atlas.webp";
  const stage = Number(o.stage);
  return {
    id,
    displayName,
    description: typeof o.description === "string" ? o.description : undefined,
    cell,
    stage: Number.isFinite(stage) && stage > 0 ? stage : 132,
    cols,
    rows,
    spritesheet,
    animations,
  };
}

export function animationOf(pack: PetPack, name: string): PetAnimation | null {
  return pack.animations[name] ?? null;
}

/** 每帧时长（ms）；fps 为 0 时返回 0，调用方按静态帧处理 */
export function frameInterval(anim: PetAnimation): number {
  return anim.fps > 0 ? 1000 / anim.fps : 0;
}
