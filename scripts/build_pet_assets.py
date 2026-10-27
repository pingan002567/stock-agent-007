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

    meta: dict[str, dict] = {}
    for folder, (name, expected) in LOOPS.items():
        files = _frame_files(src / folder, expected)
        frames = [_fit(_transparent(Image.open(f))) for f in files]
        if name not in AIRBORNE:
            frames = [_align_baseline(f) for f in frames]
        _strip(frames, out / f"{name}.webp")
        fps = LOOP_FPS[name]
        meta[name] = {
            "frames": len(frames),
            "ms": round(len(frames) / fps * 1000),
            "baseline": None if name in AIRBORNE else BASELINE,
        }
        print(f"✅ {name}.webp  ({len(frames)} 帧 · {meta[name]['ms']}ms · {fps:g}fps"
              f"{' · 腾空不对齐' if name in AIRBORNE else ' · 脚底对齐'})")

    for prefix, name in STILLS.items():  # noqa: PLR1702
        matches = list(src.glob(f"{prefix}*.png")) + list(src.glob(f"{prefix}*.jpg"))
        if not matches:
            raise SystemExit(f"找不到 {prefix}*")
        still = _align_baseline(_fit(_transparent(Image.open(matches[0]))))
        still.save(out / f"{name}.webp", "WEBP", quality=QUALITY, method=6)
        print(f"✅ {name}.webp  ← {matches[0].name}")

    folder, prefix, name = SLEEP_SOURCE
    files = [f for f in _frame_files(src / folder, LOOPS[folder][1]) if f.stem.startswith(prefix)]
    if not files:
        raise SystemExit(f"找不到 {folder}/{prefix}")
    _align_baseline(_fit(_transparent(Image.open(files[0])))).save(
        out / f"{name}.webp", "WEBP", quality=QUALITY, method=6
    )
    print(f"✅ {name}.webp  ← {folder}/{files[0].name}")

    # 帧数/时长的单一数据源：前端直接 import 这个 JSON，不再在组件里写死 8/9/12/13
    meta_path = out / "pet.meta.json"
    meta_path.write_text(
        json.dumps(
            {"cell": FRAME, "stage": 132, "loops": meta, "generated_by": "scripts/build_pet_assets.py"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"✅ {meta_path.name}  {json.dumps(meta, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
