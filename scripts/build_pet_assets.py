"""把「柴犬关键帧」原始图打包成桌宠资源（frontend/src/assets/pet）。

用法::

    .venv/bin/python scripts/build_pet_assets.py --src ~/Downloads/柴犬关键帧

为什么要这个脚本（而不是手工导图）：
1. 原图是 2026×2069 的白底 JPEG，桌宠要的是 **396×396 透明底 webp**；
2. 循环动画在代码里是**横向 sprite 条**（8 帧拼一张），不是逐帧图片；
3. 最关键的一条：**所有帧必须用同一个缩放比例**。逐帧按内容裁剪/缩放会让
   宠物体型忽大忽小 —— 这正是上次「体型不连贯」的成因，所以这里只做
   全图统一缩放 + 居中补边，绝不按帧裁剪。

白底抠图用「从四边洪水填充」而不是全图去白：柴犬胸口/爪子本身是白的，
全图去白会把胸口打穿。洪水填充只吃掉与边缘连通的背景。
"""

from __future__ import annotations

import argparse
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

# 循环：目录名 → (输出文件名, 帧数)
LOOPS = {
    "坐立待机循环": ("loop-idle-breathe", 8),
    "走路循环": ("loop-walk", 8),
    "跑步循环": ("loop-run", 8),
    "尾巴摇摆循环": ("loop-tail", 8),
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


def _strip(frames: list[Image.Image], out: Path) -> None:
    sheet = Image.new("RGBA", (FRAME * len(frames), FRAME), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * FRAME, 0), frame)
    sheet.save(out, "WEBP", quality=QUALITY, method=6)


def _frame_files(folder: Path, expected: int) -> list[Path]:
    """按帧号挑帧：同名编号有多个变体时取排序后的第一个。

    新素材（像素风）每个编号可能有多张变体，例如
    `walk_04_前伸帧` / `walk_04_接触帧`、`tail_02_右摆` / `tail_02_右摆30度`。
    循环要的是「一个编号一帧」，所以按编号分组、每组取第一张，
    再校验数量 —— 数量对不上直接报错，不做静默裁剪。
    """
    files = sorted(folder.glob("*.png")) or sorted(folder.glob("*.jpg"))
    by_index: dict[str, Path] = {}
    for f in files:
        m = re.match(r"[a-z]+_(\d+)", f.stem)
        if not m:
            continue
        by_index.setdefault(m.group(1), f)  # sorted 后第一个即该编号首张
    picked = [by_index[k] for k in sorted(by_index)]
    if len(picked) != expected:
        raise SystemExit(
            f"{folder.name}: 期望 {expected} 帧，按编号去重后得到 {len(picked)} 帧"
            f"（原始文件 {len(files)} 张）"
        )
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="柴犬关键帧 目录")
    ap.add_argument("--out", default="frontend/src/assets/pet", help="输出目录")
    args = ap.parse_args()

    src = Path(args.src).expanduser()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for folder, (name, expected) in LOOPS.items():
        files = _frame_files(src / folder, expected)
        frames = [_fit(_transparent(Image.open(f))) for f in files]
        _strip(frames, out / f"{name}.webp")
        print(f"✅ {name}.webp  ({len(frames)} 帧)")

    for prefix, name in STILLS.items():
        matches = list(src.glob(f"{prefix}*.png")) + list(src.glob(f"{prefix}*.jpg"))
        if not matches:
            raise SystemExit(f"找不到 {prefix}*")
        _fit(_transparent(Image.open(matches[0]))).save(
            out / f"{name}.webp", "WEBP", quality=QUALITY, method=6
        )
        print(f"✅ {name}.webp  ← {matches[0].name}")

    folder, prefix, name = SLEEP_SOURCE
    files = [f for f in _frame_files(src / folder, LOOPS[folder][1]) if f.stem.startswith(prefix)]
    if not files:
        raise SystemExit(f"找不到 {folder}/{prefix}")
    _fit(_transparent(Image.open(files[0]))).save(
        out / f"{name}.webp", "WEBP", quality=QUALITY, method=6
    )
    print(f"✅ {name}.webp  ← {folder}/{files[0].name}")


if __name__ == "__main__":
    main()
