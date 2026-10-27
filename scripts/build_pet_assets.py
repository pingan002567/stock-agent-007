"""把「柴犬关键帧」原始图打包成桌宠资源（frontend/src/assets/pet）。

用法::

    .venv/bin/python scripts/build_pet_assets.py --src ~/Downloads/柴犬关键帧

输出 **一张图集 + 一份 pet.json**（对齐 ChatGPT 宠物的做法：行 = 动作，列 = 帧），
不再输出一堆横向 sprite 条：

    frontend/src/assets/pet/
      atlas.webp    12 行 × N 列，单格 396×396
      pet.json      cell / stage / cols / rows / animations{row,frames,fps}

这样「自定义宠物」只要一个目录里放 pet.json + 一张图集，无需重新编译。

为什么要这个脚本（而不是手工导图）：
1. 原图是 2026×2069 的白底 JPEG，桌宠要的是 **396×396 透明底**；
2. 最关键的一条：**所有帧必须用同一个缩放比例**。逐帧按内容裁剪/缩放会让
   宠物体型忽大忽小 —— 这正是上次「体型不连贯」的成因，所以这里只做
   全图统一缩放 + 居中补边，绝不按帧裁剪；
3. 踩地的帧额外做**基线对齐**（只竖直平移），否则脚底跟着姿势漂，播起来上下颠。

白底抠图用「从四边洪水填充」而不是全图去白：柴犬胸口/爪子本身是白的，
全图去白会把胸口打穿。洪水填充只吃掉与边缘连通的背景。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import deque
from pathlib import Path

from PIL import Image

#: 单帧边长（与 PetWindow 的 STAGE 比例一致：132px 舞台，3x 资源）
FRAME = 396
#: 抠图容差：白底与浅灰投影都算背景
WHITE_TOLERANCE = 26
#: webp 质量
QUALITY = 82
#: 地面基线：所有「踩地」的帧把最低像素对齐到这条线（对齐 ChatGPT 宠物的固定格思路）。
#: 之前每帧只做等比缩放 + 居中补边，脚底跟着姿势在 361~385 之间漂 24px，快速播放像上下颠。
BASELINE = FRAME - 16
#: 目标播放帧率（每帧时长 = 帧数 / fps）。run 有腾空段，不做基线对齐保留弹跳。
LOOP_FPS = {
    "loop-idle-breathe": 3.75,
    "loop-walk": 15.0,
    "loop-run": 18.0,
    "loop-tail": 14.5,
}
#: 有腾空动作、不能钉住地面的循环
AIRBORNE = {"loop-run"}

#: 图集行顺序：一行一个动作，行号 = 下标。自定义宠物按同样约定即可被识别。
ATLAS_ROWS = [
    "idle", "walk", "run", "tail", "alert", "error",
    "sleep", "clap", "phone", "stretch", "tilt", "yawn",
]
#: 非循环动作的目标帧率（0 = 只播一帧，时长由前端 hold 决定）
STILL_FPS = {
    "alert": 2.2, "error": 1.4, "clap": 5.3,
    "sleep": 0, "phone": 0, "stretch": 0, "tilt": 0, "yawn": 0,
}
#: 循环动作 → (行名, 素材循环 key)
LOOP_ROWS = {
    "idle": "loop-idle-breathe",
    "walk": "loop-walk",
    "run": "loop-run",
    "tail": "loop-tail",
}
#: 单帧动作 → 由哪些 still 组成（多帧则按顺序轮播）
STILL_ROWS = {
    "alert": ["alert-1", "alert-2"],
    "error": ["error-1", "error-2"],
    "clap": ["clap-1", "clap-2"],
    "phone": ["phone-1"],
    "stretch": ["stretch-1"],
    "tilt": ["tilt-1"],
    "yawn": ["yawn-1"],
    "sleep": ["sleep-1"],
}

# 循环：目录名 → (输出文件名, 帧数)
#
# **用满素材里的全部帧**（含「同编号变体」）：实测那些变体不是重复帧，而是补间
# （walk_04_前伸 → walk_04_接触 的像素差 11，而相邻编号间距 28~36）。按编号去重
# 会让走路只剩 8 帧 / 跑步 9fps，明显卡顿。
LOOPS = {
    "坐立待机循环": ("loop-idle-breathe", 9),
    "走路循环": ("loop-walk", 12),
    "跑步循环": ("loop-run", 13),
    "尾巴摇摆循环": ("loop-tail", 12),
}

# 单帧：源文件名前缀 → 输出文件名
STILLS = {
    "01_开心拍掌": "clap-1",
    "10_下班开心": "clap-2",
    "04_惊讶抬爪": "alert-1",
    "14_跳跃欢呼": "alert-2",
    "09_上班崩溃": "error-1",
    "03_生气叉腰": "error-2",
    "11_摸鱼看手机": "phone-1",
    "15_伸懒腰": "stretch-1",
    "16_歪头疑惑": "tilt-1",
    "36_打哈欠": "yawn-1",
}

#: 睡觉用待机循环里的闭眼帧（比单独一张更自然）
SLEEP_SOURCE = ("坐立待机循环", "idle_05_全闭眼", "sleep-1")




def _is_whiteish(px: tuple[int, int, int]) -> bool:
    r, g, b = px[:3]
    return r >= 255 - WHITE_TOLERANCE and g >= 255 - WHITE_TOLERANCE and b >= 255 - WHITE_TOLERANCE


def _transparent(img: Image.Image) -> Image.Image:
    """白底 → 透明：从四边洪水填充，保留被轮廓包住的白色（胸口/爪子）。"""
    rgb = img.convert("RGB")
    w, h = rgb.size
    pixels = rgb.load()
    alpha = Image.new("L", (w, h), 255)
    ap = alpha.load()

    seen = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()

    def push(x: int, y: int) -> None:
        if 0 <= x < w and 0 <= y < h and not seen[y * w + x]:
            seen[y * w + x] = 1
            queue.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    while queue:
        x, y = queue.popleft()
        if not _is_whiteish(pixels[x, y]):
            continue
        ap[x, y] = 0
        push(x + 1, y)
        push(x - 1, y)
        push(x, y + 1)
        push(x, y - 1)

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _fit(img: Image.Image, size: int = FRAME) -> Image.Image:
    """统一比例缩放到 size 方框，居中补透明边。

    **所有帧都走这同一个函数**，不按内容裁剪 —— 体型一致全靠这条。

    降采样用 BOX（面积平均）而不是 LANCZOS：素材是**像素风**，LANCZOS 的
    振铃会在色块边缘留下一圈发亮的镶边，像素感就糊了；BOX 只做区间平均，
    色块边界干净。放大时才用 LANCZOS。
    """
    ratio = min(size / img.width, size / img.height)
    scaled = img.resize(
        (max(1, round(img.width * ratio)), max(1, round(img.height * ratio))),
        Image.BOX if ratio < 1 else Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


def _align_baseline(img: Image.Image, baseline: int = BASELINE) -> Image.Image:
    """把帧的最低不透明像素对齐到同一条地面线。

    只做**竖直平移**：等比缩放比例不变（体型一致），水平位置不变（避免横向抖动）。
    走/坐/站这类「脚一直踩地」的循环，对齐后就不会再上下漂；腾空类（run）跳过。
    """
    bbox = img.split()[3].getbbox()
    if not bbox:
        return img
    shift = baseline - bbox[3]
    if shift == 0:
        return img
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(img, (0, shift))
    return out


def _strip(frames: list[Image.Image], out: Path) -> None:
    sheet = Image.new("RGBA", (FRAME * len(frames), FRAME), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * FRAME, 0), frame)
    sheet.save(out, "WEBP", quality=QUALITY, method=6)


def _compose_atlas(rows: dict[str, list[Image.Image]], out: Path) -> tuple[int, int, int]:
    """把「行名 → 帧列表」合成一张图集，未用的格子保持全透明。"""
    cols = max(len(frames) for frames in rows.values())
    height = FRAME * len(ATLAS_ROWS)
    sheet = Image.new("RGBA", (FRAME * cols, height), (0, 0, 0, 0))
    for row, name in enumerate(ATLAS_ROWS):
        for col, frame in enumerate(rows.get(name, [])):
            sheet.paste(frame, (col * FRAME, row * FRAME), frame)
    sheet.save(out, "WEBP", quality=QUALITY, method=6)
    return cols, len(ATLAS_ROWS), FRAME


def _frame_files(folder: Path, expected: int) -> list[Path]:
    """按帧号挑帧：同名编号有多个变体时取排序后的第一个。

    新素材（像素风）每个编号可能有多张变体，例如
    `walk_04_前伸帧` / `walk_04_接触帧`、`tail_02_右摆` / `tail_02_右摆30度`。
    循环要的是「一个编号一帧」，所以按编号分组、每组取第一张，
    再校验数量 —— 数量对不上直接报错，不做静默裁剪。
    """
    files = sorted(folder.glob("*.png")) or sorted(folder.glob("*.jpg"))
    if len(files) != expected:
        raise SystemExit(f"{folder.name}: 期望 {expected} 帧，实际 {len(files)} 张")
    # 文件名里编码了相位（walk_04_前伸 / walk_04_接触 …），字典序即播放序：
    # 同编号的补间排在编号内、下一编号之前。已验证相邻帧像素差单调递增。
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="柴犬关键帧 目录")
    ap.add_argument("--out", default="frontend/src/assets/pet", help="输出目录")
    args = ap.parse_args()

    src = Path(args.src).expanduser()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows: dict[str, list[Image.Image]] = {}

    # 1) 循环：用满素材全部帧（含补间），踩地的做基线对齐
    for row_name, loop_key in LOOP_ROWS.items():
        folder = next(f for f, (name, _n) in LOOPS.items() if name == loop_key)
        expected = LOOPS[folder][1]
        files = _frame_files(src / folder, expected)
        frames = [_fit(_transparent(Image.open(f))) for f in files]
        if loop_key not in AIRBORNE:
            frames = [_align_baseline(f) for f in frames]
        rows[row_name] = frames
        print(f"✅ {row_name:8s} ← {folder}  {len(frames)} 帧  {LOOP_FPS[loop_key]:g}fps")

    # 2) 单帧动作
    for row_name, needs in STILL_ROWS.items():
        frames = []
        for need in needs:
            if need == "sleep-1":
                # 睡觉用待机循环里的全闭眼帧（单张更自然）
                folder, stem, _name = SLEEP_SOURCE
                hit = sorted((src / folder).glob(f"{stem}*.png"))
            else:
                prefix = next(p for p, name in STILLS.items() if name == need)
                hit = sorted(src.glob(f"{prefix}*.png")) + sorted(src.glob(f"{prefix}*.jpg"))
            if not hit:
                raise SystemExit(f"找不到 {need} 的源图")
            frames.append(_align_baseline(_fit(_transparent(Image.open(hit[0])))))
        rows[row_name] = frames
        print(f"✅ {row_name:8s} ← {', '.join(needs)}  {len(frames)} 帧")

    # 3) 合成图集 + 描述文件
    cols, n_rows, cell = _compose_atlas(rows, out / "atlas.webp")
    animations = {}
    for row_name in ATLAS_ROWS:
        frames = rows.get(row_name, [])
        fps = LOOP_FPS[LOOP_ROWS[row_name]] if row_name in LOOP_ROWS else STILL_FPS[row_name]
        animations[row_name] = {
            "row": ATLAS_ROWS.index(row_name),
            "frames": len(frames) or 1,
            "fps": fps,
        }
    meta = {
        "id": "shiba",
        "displayName": "柴犬助手",
        "description": "内置像素风柴犬（耳机 + 领结）",
        "cell": cell,
        "stage": 132,
        "cols": cols,
        "rows": n_rows,
        "spritesheet": "atlas.webp",
        "animations": animations,
        "generated_by": "scripts/build_pet_assets.py",
    }
    (out / "pet.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(f"✅ atlas.webp  {cols} 列 × {n_rows} 行 × {cell}px")
    print(f"✅ pet.json    {len(animations)} 个动作")

    # 4) 清掉旧格式产物，避免两套并存
    for stale in out.glob("*.webp"):
        if stale.name != "atlas.webp":
            stale.unlink()
    (out / "pet.meta.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
