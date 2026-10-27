/** 宠物包的发现与加载（内置包 + 本地自定义包）。
 *
 *  自定义包放在 `~/.stockagent/pets/<目录名>/`，目录里两个文件：
 *
 *      pet.json     元数据 + 动作表
 *      atlas.webp   图集（行 = 动作，列 = 帧）
 *
 *  桌面端通过 Rust 命令扫描目录、用 Tauri 的 asset 协议直接读图（不经过 base64，
 *  省内存也省一次编解码）；浏览器里没有文件系统，只提供内置包。
 */

import builtinSheetUrl from "@/assets/pet/atlas.webp";
import builtinRaw from "@/assets/pet/pet.json";
import { normalizePack, type LoadedPack, type PetPack } from "@/lib/petPack";

/** 选中的宠物包 id（localStorage），缺省用内置 shiba */
export const PET_PACK_KEY = "pet.pack";

type Invoke = <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

function tauriInvoke(): Invoke | null {
  const t = (window as unknown as { __TAURI__?: { core?: { invoke?: Invoke } } }).__TAURI__;
  return t?.core?.invoke ?? null;
}

export function isDesktop(): boolean {
  return tauriInvoke() !== null;
}

/** 内置包：和自定义包走同一个格式 */
export const BUILTIN_PACK: LoadedPack = {
  pack: normalizePack(builtinRaw),
  sheetUrl: builtinSheetUrl,
  source: "builtin",
};

export interface CustomPackEntry {
  id: string;
  dir: string;
  json: string;
}

/** 列出本地自定义包（浏览器里恒为空） */
export async function listCustomPacks(): Promise<CustomPackEntry[]> {
  const invoke = tauriInvoke();
  if (!invoke) return [];
  try {
    return await invoke<CustomPackEntry[]>("pet_pack_list");
  } catch {
    return [];
  }
}

/** 自定义包根目录（浏览器里没有） */
export async function petPackRoot(): Promise<string | null> {
  const invoke = tauriInvoke();
  if (!invoke) return null;
  try {
    return await invoke<string>("pet_pack_root");
  } catch {
    return null;
  }
}

export async function revealPackDir(path: string): Promise<boolean> {
  const invoke = tauriInvoke();
  if (!invoke) return false;
  try {
    await invoke("pet_pack_reveal", { path });
    return true;
  } catch {
    return false;
  }
}

export function selectedPackId(): string {
  return localStorage.getItem(PET_PACK_KEY) || BUILTIN_PACK.pack.id;
}

export function setSelectedPackId(id: string): void {
  localStorage.setItem(PET_PACK_KEY, id);
}

/** 把本地文件路径转成 webview 能加载的 URL（Tauri asset 协议） */
function fileUrl(path: string): string {
  const t = (window as unknown as { __TAURI__?: { core?: { convertFileSrc?: (p: string) => string } } })
    .__TAURI__;
  if (t?.core?.convertFileSrc) return t.core.convertFileSrc(path);
  return `asset://localhost/${encodeURIComponent(path)}`;
}

/**
 * 加载指定包。
 * - 内置：直接用打包产物
 * - 自定义：读本地 pet.json + asset 协议取图集
 * 任何一步失败都**回退到内置包**，绝不让桌宠窗口白屏。
 */
export async function loadPack(id: string): Promise<LoadedPack> {
  if (!id || id === BUILTIN_PACK.pack.id) return BUILTIN_PACK;
  const entries = await listCustomPacks();
  const entry = entries.find((e) => e.id === id);
  if (!entry) return BUILTIN_PACK;
  try {
    const pack: PetPack = normalizePack(JSON.parse(entry.json));
    const dir = entry.dir.replace(/\/+$/, "");
    return { pack, sheetUrl: fileUrl(`${dir}/${pack.spritesheet}`), source: "custom", dir: entry.dir };
  } catch (err) {
    console.warn("[pet] 自定义宠物包不合法，回退内置：", err);
    return BUILTIN_PACK;
  }
}
