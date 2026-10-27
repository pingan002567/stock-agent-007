# 自定义宠物包

> 桌宠的宠物是一包**数据**，不是编译进前端的资源。把目录放好、在设置里选一下就能换，
> 不用重新打包应用。格式与 ChatGPT / Codex 宠物的「图集 + 元数据」一致。

## 目录位置

```
~/.stockagent/pets/<你的宠物名>/
  pet.json         元数据 + 动作表
  atlas.webp       一张图集：行 = 动作，列 = 帧
```

放好后打开「设置 → 外观 → 桌宠」，点**刷新**，选中它即可。

## pet.json

```json
{
  "id": "shiba",
  "displayName": "柴犬助手",
  "description": "像素风柴犬",
  "cell": 396,
  "stage": 132,
  "cols": 13,
  "rows": 12,
  "spritesheet": "atlas.webp",
  "animations": {
    "idle":  { "row": 0, "frames": 9,  "fps": 3.75 },
    "walk":  { "row": 1, "frames": 12, "fps": 15 },
    "run":   { "row": 2, "frames": 13, "fps": 18 },
    "tail":  { "row": 3, "frames": 12, "fps": 14.5 },
    "alert": { "row": 4, "frames": 2,  "fps": 2.2 },
    "error": { "row": 5, "frames": 2,  "fps": 1.4 },
    "sleep": { "row": 6, "frames": 1,  "fps": 0 }
  }
}
```

| 字段 | 说明 |
|---|---|
| `id` | 唯一标识（目录名也行） |
| `displayName` | 设置页显示的名字 |
| `cell` | 图集单格边长（px），32~1024 |
| `stage` | 舞台显示边长（CSS px），缺省 132 |
| `cols` / `rows` | 图集列数/行数；**可省略**，会按动作表推导 |
| `spritesheet` | 图集文件名，缺省 `atlas.webp` |
| `animations.*.row` | 该动作在图集的第几行（0 起） |
| `animations.*.frames` | 用到几帧（从第 0 列开始） |
| `animations.*.fps` | 播放帧率；`0` = 只显示一帧 |

**必需动作**：`idle`、`walk`。其余按需提供，缺了会回退到 `idle`：

| 动作 | 什么时候播 |
|---|---|
| `idle` | 空闲待机 |
| `walk` | 拖动宠物 |
| `run` | AI 正在跑任务 |
| `tail` | 任务刚完成 |
| `alert` | 有待确认的事项 |
| `error` | 出错 |
| `sleep` | 长时间无操作 |
| `clap` / `phone` / `stretch` / `tilt` / `yawn` | 随机小动作（一次性） |

## 图集规范

```
宽 = cols × cell      高 = rows × cell
行 = 动作，列 = 帧，第 0 列是最左
没用到格子必须**完全透明**（不要放阴影/背景/辅助线）
```

建议：

- **单格构图对齐**：所有帧在格子里对齐同一地面线，否则播放时会上下颠（内置柴犬就是踩到 y=380 的基线）
- **同一缩放比例**：不要按内容裁剪单独放大某一帧，体型会忽大忽小
- 透明背景 PNG → 导出 WebP（q80~85），一张图集通常几百 KB

## 做一只宠物的最小流程

1. 按上表准备 N 行 × M 列的逐帧图，拼成一张透明底大图
2. 写 `pet.json`，`row`/`frames`/`fps` 对上你的排版
3. 放进 `~/.stockagent/pets/<名字>/`，`atlas.webp` + `pet.json`
4. 设置 → 外观 → 桌宠 → 刷新 → 选中

包不合法时设置页会**红色标出并显示具体原因**（例如 `animations.walk.row=5 超出 rows=3`），
同时桌宠会回退到内置宠物，不会白屏。

## 参考实现

内置柴犬就是这个格式，可以直接抄它的结构：

```bash
.venv/bin/python scripts/build_pet_assets.py --src ~/Downloads/柴犬关键帧
# 产出 frontend/src/assets/pet/{atlas.webp,pet.json}
```

脚本里有三件值得复用的事：白底洪水填充抠图（不伤胸口白毛）、统一比例缩放、
踩地帧的基线对齐。
