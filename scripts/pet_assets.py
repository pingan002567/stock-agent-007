#!/usr/bin/env python3
"""桌宠素材管线：把 ~/Downloads/柴犬关键帧 的生成图处理成桌宠可用的资源。

做四件事（每一步都有踩坑记录，改参数前先读）：

1. 去背景 —— 背景是奶油色，但狗自己的白胸毛和背景只差 8/255，
   全局抠色会把狗挖出洞。做法：只去掉「与画面边缘连通」的那片背景
   （形态学重建），并且把梯度大的像素排除出「背景」（描边屏障），
   flood 就穿不过轮廓。
2. 归一化对齐 —— 循环帧是图像模型生成的"关键帧"，不是同一套骨骼渲染：
   主体包围盒在 1425x1915 ~ 1559x1981 之间抖、位置差 130px。
   所以统一用「帧 0 的缩放系数」等比缩放所有帧（保留呼吸的轻微高度变化），
   再水平居中 + 底边对齐（脚踩同一条线）。
3. 统一尺寸 —— 264x264 画布（2x），主体高 240。
4. 打包 —— 循环帧打成横向 sprite sheet（一次请求、一次解码、CSS steps 播放），
   静态帧单独出 WebP(q82)。

用法：
    python3 scripts/pet_assets.py --src ~/Downloads/柴犬关键帧
"""

from __future__ import annotations

import argparse
import os

import numpy as np
from PIL import Image, ImageFilter

CANVAS = 396          # 画布边长（3x：132pt 显示，2x/3x 屏都清晰）
SUBJECT_H = 360       # 主体目标高度
QUALITY = 82


def cut_background(im: Image.Image) -> Image.Image:
    """去掉与边缘连通的背景，返回 RGBA（其余部分保留原始像素）。"""
    rgb = im.convert("RGB")
    a = np.asarray(rgb).astype(np.int16)
    h, w, _ = a.shape
    bg = np.median(np.array([a[2, 2], a[2, w - 3], a[h - 3, 2], a[h - 3, w - 3]]), axis=0)
    dist = np.sqrt(((a - bg) ** 2).sum(axis=2))

    # 描边/边缘屏障：梯度大的地方不当背景，flood 穿不过轮廓
    g = np.asarray(rgb.convert("L").filter(ImageFilter.GaussianBlur(1))).astype(np.float32)
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    near = (dist < 26) & (np.hypot(gx, gy) < 12)

    seed = np.zeros((h, w), bool)
    seed[0, :] = near[0, :]
    seed[-1, :] = near[-1, :]
    seed[:, 0] = near[:, 0]
    seed[:, -1] = near[:, -1]
    cur = seed
    for _ in range(4000):
        nxt = cur.copy()
        nxt[1:, :] |= cur[:-1, :]
        nxt[:-1, :] |= cur[1:, :]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        nxt &= near
        if nxt.sum() == cur.sum():
            break
        cur = nxt

    alpha = np.where(cur, 0.0, 1.0)
    edge = cur & (dist > 10)
    alpha[edge] = np.clip((dist[edge] - 10) / 16.0, 0, 1)

    # 第二道：素材自带地面阴影是"很亮的柔光"，在深色桌面上会变成一块白垫子。
    # 把「接近背景 或 很亮」的像素也当成可通行，仍然用梯度当屏障，
    # 这样能吃掉阴影但不会吃掉被描边围住的白色胸毛。
    lum = a.mean(axis=2)
    passable = (((dist < 60) | (lum > 196)) & (np.hypot(gx, gy) < 14))
    seed2 = np.zeros((h, w), bool)
    seed2[0, :] = passable[0, :]
    seed2[-1, :] = passable[-1, :]
    seed2[:, 0] = passable[:, 0]
    seed2[:, -1] = passable[:, -1]
    cur2 = seed2
    for _ in range(4000):
        nxt = cur2.copy()
        nxt[1:, :] |= cur2[:-1, :]
        nxt[:-1, :] |= cur2[1:, :]
        nxt[:, 1:] |= cur2[:, :-1]
        nxt[:, :-1] |= cur2[:, 1:]
        nxt &= passable
        if nxt.sum() == cur2.sum():
            break
        cur2 = nxt
    alpha = np.where(cur2, 0.0, alpha)

    return Image.fromarray(np.dstack([np.asarray(rgb), (alpha * 255).astype(np.uint8)]), "RGBA")


def subject_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    bb = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bb:
        raise ValueError("空图：抠完背景没有剩下主体")
    return bb


def head_center_x(im: Image.Image, bbox) -> float:
    """主体上部 30% 的 alpha 质心 x —— 四足循环里头部最稳，
    用它做水平锚点，比用整只包围盒中心稳得多（否则跑起来会左右漂）。"""
    alpha = np.asarray(im)[:, :, 3].astype(np.float32)
    x0, y0, x1, y1 = bbox
    band = alpha[y0:y0 + max(1, int((y1 - y0) * 0.3)), x0:x1]
    cols = band.sum(axis=0)
    if cols.sum() <= 0:
        return (x0 + x1) / 2
    return x0 + float((cols * np.arange(len(cols))).sum() / cols.sum())


def place(im: Image.Image, bbox, scale: float, anchor_x: float) -> Image.Image:
    """按 scale 缩放后：水平按 anchor_x 对齐到画布中心，底边贴画布底部。"""
    sub = im.crop(bbox)
    w = max(1, int(round(sub.width * scale)))
    h = max(1, int(round(sub.height * scale)))
    sub = sub.resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    offset_x = int(round(CANVAS / 2 - (anchor_x - bbox[0]) * scale))
    canvas.paste(sub, (offset_x, CANVAS - h), sub)
    return canvas


def fit_scale(bbox) -> float:
    """同时满足「高度 = SUBJECT_H」和「宽度不超画布」的缩放系数。"""
    h = bbox[3] - bbox[1]
    w = bbox[2] - bbox[0]
    return min(SUBJECT_H / h, (CANVAS - 12) / w)


def load_frames(src_dir: str) -> tuple[list, list]:
    names = sorted(os.listdir(src_dir))
    frames = [cut_background(Image.open(os.path.join(src_dir, n))) for n in names]
    return frames, [subject_bbox(f) for f in frames]


def group_scale(frames: list, boxes: list, pick: list[int] | None = None) -> float:
    """按整组算缩放：高度不超过 SUBJECT_H，且「头到最左 + 头到最右」不超过画布宽度。
    必须在铺图之前算 —— 铺完再量，量到的是已经裁过的结果，永远看不出溢出。"""
    idx = [(i - 1) for i in pick] if pick else list(range(len(frames)))
    heads = [head_center_x(frames[i], boxes[i]) for i in idx]
    bs = [boxes[i] for i in idx]
    max_h = max(b[3] - b[1] for b in bs)
    left = max(h - b[0] for h, b in zip(heads, bs))
    right = max(b[2] - h for h, b in zip(heads, bs))
    return min(SUBJECT_H / max_h, (CANVAS - 8) / (left + right))


def build_loop(frames: list, boxes: list, out_path: str, scale: float | None = None, pick: list[int] | None = None) -> None:
    """pick: 1-based 帧号子集（把 8 帧拆成"呼吸 / 眨�眼 / 歪头"几段用）。"""
    idx = [(i - 1) for i in pick] if pick else list(range(len(frames)))
    sel_f = [frames[i] for i in idx]
    sel_b = [boxes[i] for i in idx]
    if scale is None:
        scale = group_scale(frames, boxes, pick)
    placed = [place(f, b, scale, head_center_x(f, b)) for f, b in zip(sel_f, sel_b)]

    sheet = Image.new("RGBA", (CANVAS * len(placed), CANVAS), (0, 0, 0, 0))
    for i, p in enumerate(placed):
        sheet.paste(p, (i * CANVAS, 0), p)
    sheet.save(out_path, "WEBP", quality=QUALITY, method=6)
    print(f"  loop  {os.path.basename(out_path):22} {len(placed)} 帧  {os.path.getsize(out_path)//1024}KB")


def build_static(src: str, out_path: str) -> None:
    im = cut_background(Image.open(src))
    bb = subject_bbox(im)
    scale = group_scale([im], [bb])
    place(im, bb, scale, head_center_x(im, bb)).save(out_path, "WEBP", quality=QUALITY, method=6)
    print(f"  still {os.path.basename(out_path):22}          {os.path.getsize(out_path)//1024}KB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.expanduser("~/Downloads/柴犬关键帧"))
    ap.add_argument("--out", default="frontend/src/assets/pet")
    args = ap.parse_args()
    out = args.out
    os.makedirs(out, exist_ok=True)

    print("循环（sprite sheet）：")
    # 待机 8 帧是「呼吸 + 眨眼 + 歪头」三段拼的：整段循环会每 1.4s 眨一次眼（太频繁），
    # 所以拆开：呼吸常驻循环，眨眼/歪头偶尔插播。
    idle_f, idle_b = load_frames(os.path.join(args.src, "坐立待机循环"))
    scale_idle = group_scale(idle_f, idle_b)
    build_loop(idle_f, idle_b, f"{out}/loop-idle-breathe.webp", scale_idle, [1, 2, 3])
    build_loop(idle_f, idle_b, f"{out}/loop-idle-blink.webp", scale_idle, [4, 5, 6])
    build_loop(idle_f, idle_b, f"{out}/loop-idle-tilt.webp", scale_idle, [7, 8])

    for name, folder in (("run", "跑步循环"), ("walk", "走路循环"), ("tail", "尾巴摇摆循环")):
        f, b = load_frames(os.path.join(args.src, folder))
        build_loop(f, b, f"{out}/loop-{name}.webp")

    print("静态关键帧：")
    stills = {
        "alert": ["04_惊讶抬爪.png", "05_收到敬礼.png"],
        "error": ["08_无语扶额.png", "02_委屈抱胸.png"],
        # 一次性小动作（点击/闲时随机播）
        "clap": ["01_开心拍掌.png", "10_下班开心.png"],
        "phone": ["11_摸鱼看手机.png"],
        "stretch": ["15_伸懒腰.png"],
        "tilt": ["16_歪头疑惑.png"],
        "yawn": ["36_打哈欠.png"],
    }
    for state, files in stills.items():
        for i, f in enumerate(files, start=1):
            build_static(os.path.join(args.src, f), f"{out}/{state}-{i}.webp")

    # 睡觉：直接取待机循环里的「全闭眼」帧
    build_static(
        os.path.join(args.src, "坐立待机循环", sorted(os.listdir(os.path.join(args.src, "坐立待机循环")))[4]),
        f"{out}/sleep-1.webp",
    )

if __name__ == "__main__":
    main()
