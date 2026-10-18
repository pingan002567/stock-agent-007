# 桌面端设计 token 与组件规范

> 本项目的桌面客户端（`frontend/` + `desktop/` Tauri 壳）视觉语言以 **DeepSeek Harness** 为基准。
> 本文的每个数值都取自 DSH 安装包里的真实定义（`app.asar` 内 `@deepseek-ai/dsh-client-ui-primitives`
> 与 `dsh-web-frontend`），不是凭截图估的。
>
> 唯一实现位置：**`frontend/src/index.css` 顶部的 `:root` 与 `:root.light`**。
> 改颜色/圆角/阴影只改这里，**不要**在组件里写死。

---

## 0. 三条原则

1. **靠层级分层，不靠边框**。区分区块用 `canvas → sidebar → surface → surface-2` 四层底色。
   描边数量没有硬性减少（仍有 145 处 `1px solid`，多数是表格/分隔线这类合理用途），
   但**全部收敛到 `--line-soft` 的低对比**，视觉重量降下来了。
   阴影则做了实打实的收敛：硬编码 `rgba` 阴影从 **22 处降到 2 处**（只剩一个脉冲动画），
   其余全部改用 `var(--elev-*)`（现有 29 处引用）。状态点的「发光」效果已全部移除 —— DSH 是平色点。
2. **一个强调色**。蓝色只用于**链接 / 焦点 / 状态点**。主操作按钮是高对比**黑/白**，不是蓝。
3. **阴影只给浮层**。卡片、列表、表格一律不用阴影；只有浮在内容之上的层（模态、下拉、toast）才有 elevation。

---

## 1. 颜色

### 1.1 语义 token（`frontend/src/index.css`）

| token | 深色 | 浅色 | 用途 | DSH 对应 |
|---|---|---|---|---|
| `--canvas` | `#151517` | `#ffffff` | 中栏底（对话区） | `bg-base` ← neutral-bluish-950 |
| `--sidebar` | `#232324` | `#f9fafb` | 左右两栏底 | `bg-layer-1` ← 875 |
| `--surface` | `#2c2c2e` | `#ffffff` | 卡片/输入条纸面 | `bg-layer-2` ← 850 |
| `--surface-2` | `#353638` | `#f5f6f7` | 悬停块/选中块 | `bg-layer-3` ← 800 |
| `--ink` | `#f9fafb` | `#0f1115` | 正文、**主按钮底** | `label-primary` ← 50 / 1000 |
| `--ink-2` | `#ebeef2` | `#1f2126` | 主按钮 hover | — |
| `--muted` | `#cfd3d6` | `#61666b` | 次级文字 | `label-secondary` ← 300 / 700 |
| `--faint` | `#adb2b8` | `#81858c` | 三级文字/标签 | `label-tertiary` ← 400 / 600 |
| `--line` | `rgba(255,255,255,.12)` | `rgba(0,0,0,.10)` | 强分隔（弹窗描边） | `border-l2` |
| `--line-soft` | `rgba(255,255,255,.06)` | `rgba(0,0,0,.04)` | 弱分隔（卡片/表格/列表） | `border-l1` |
| `--blue` | `#60a5fa` | `#3b82f6` | 链接、焦点、状态点 | `static-blue-400/500` |
| `--blue-hover` | `#93c5fd` | `#2563eb` | — | blue-300/600 |
| `--green` / `--red` / `--amber` | `#4ade80` / `#f87171` / `#fbbf24` | `#16a34a` / `#dc2626` / `#b45309` | 涨 / 跌 / 警告 | — |
| `--hover` | `rgba(255,255,255,.08)` | `rgba(38,49,72,.06)` | 交互 hover 底 | `interactive-bg-hover` |
| `--active` | `rgba(255,255,255,.14)` | `rgba(38,49,72,.10)` | 交互 active 底 | `interactive-bg-active` |
| `--btn-subtle` | `rgba(84,85,87,.50)` | `rgba(38,49,72,.08)` | 弱填充按钮（如「新建对话」） | `button-tool-bar-fill` |
| `--overlay` | `rgba(0,0,0,.50)` | `rgba(0,0,0,.24)` | 模态遮罩（**不模糊**） | `bg-mask-1` |

### 1.2 色阶（需要新色时从这里取，别自造）

```
00  #ffffff   150 #e9ecf2   400 #adb2b8   750 #43454a   950 #151517
50  #f9fafb   200 #e1e5ee   500 #979da6   800 #353638   1000 #0f1115
60  #f5f6f7   300 #cfd3d6   600 #81858c   850 #2c2c2e
75  #f1f3f5   700 #61666b   875 #232324   900 #1b1b1c
100 #ebeef2
```

---

## 2. 圆角

**与主题无关**，只在 `:root` 定义一次。

| 变量 | 值 | 用在 |
|---|---|---|
| `--radius-sm` | 8px | 小控件、列表行、分页按钮 |
| `--radius-md` | 12px | **按钮默认**、输入框、菜单 |
| `--radius-lg` | 12px | （兼容别名） |
| `--radius-xl` | 16px | **卡片 / panel** |
| `--radius-panel` | 20px | 输入条、设置模态 |

> DSH 的完整标度是 `4 / 8 / 12 / 16 / 20 / 28`。上表只用到了常用四档；
> 需要更小的（如 tag）直接用 `4px` 或在 8px 基础上做。

---

## 3. 层级（elevation）

三段式：**第一段是环状描边**（`0 0 0 1px`，代替 `border`，圆角与描边永远对齐），
后两段是 3~5% 的环境光。原来的 `0 4px 12px rgba(0,0,0,.32)` 比它重约 8 倍。

```css
--elev-panel:     0 0 0 1px rgba(255,255,255,.06), 0 3px 8px rgba(0,0,0,.03), 0 0 16px rgba(0,0,0,.02);
--elev-prominent: 0 0 0 1px rgba(255,255,255,.06), 0 3px 8px rgba(0,0,0,.04), 0 0 20px rgba(0,0,0,.05);
--elev-soft:      0 0 0 1px rgba(255,255,255,.06), 0 4px 16px rgba(0,0,0,.03), 0 0 24px rgba(0,0,0,.03);
```

兼容别名（老代码用这些，已重映射，会自动生效）：
`--shadow-sm → elev-panel`、`--shadow-md/lg → elev-prominent`、`--shadow-glow → 0 0 0 1px var(--blue-soft)`。

| 层级 | 用在 |
|---|---|
| 无阴影 | 卡片、列表、表格、输入条 —— **一律不加** |
| `elev-panel` | 贴边的面板/下拉 |
| `elev-prominent` | 模态、菜单、toast（真正浮起来的） |
| `elev-soft` | 输入条（`--composer-shadow` 指向它） |

---

## 4. 排版

- 字体栈：`"PingFang SC", "Noto Sans SC", "Source Han Sans SC", -apple-system, BlinkMacSystemFont, "Microsoft YaHei", system-ui, sans-serif`
- 等宽：`"JetBrains Mono", "SF Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`
- **字号下限 11px**（2026-10 已把全项目 9~12.5px 统一 +1px，共 228 处，另补齐 6 处 9~10px）
  - 唯一例外：`.model-pill-caret` 的 `8px` 是 `▾` 字形，属于图标不属于正文

| 层级 | 字号 | 用途 |
|---|---|---|
| 页面标题 | 15~16px / 650 | `func-title`、面板标题 |
| 卡片主数值 | 15~24px / 650 | KPI |
| **正文** | 13px | 对话、列表主文案（**主力字号，151 处**） |
| 次级 | 12px | 元信息、表格单元格 |
| 标签 | 11px | 表头、badge、时间戳（**下限**） |

---

## 5. 组件配方

### 5.1 按钮

基类在 `index.css` 的 `button { ... }`：**透明底 + 0.5px 发丝描边 + radius 12 + 只过渡背景色**。

| 变体 | class | 样式 |
|---|---|---|
| 主操作 | `.primary` | `background: var(--ink)` / `color: var(--canvas)`。**深色=白底黑字，浅色=黑底白字** |
| 次要 | `.outline` | 透明 + `0.5px solid var(--line)` |
| 幽灵 | `.ghost` | 全透明，hover 才出 `var(--hover)` |
| 弱填充 | — | `background: var(--btn-subtle)`（仅侧栏 CTA 这类） |
| 危险 | `.danger` | `color: var(--red)`，hover `var(--red-soft)` |
| 小号 | `.small` | 28px 高 / 12px 字 / radius 8 |
| 禁用 | `:disabled` | **`opacity: .4`**（不要改成灰底） |

```tsx
<button className="primary">保存</button>
<button className="outline">取消</button>
<button className="ghost">更多</button>
<button className="small danger">删除</button>
```

> ⚠️ 不要再写 `background: var(--blue)`。蓝色不是主色。
> 现存的蓝色填充只剩状态点（`event-dot`、`thinking-block-pulse`）和 toggle 打开态，属于"状态"不属于"操作"。

### 5.2 卡片 / 面板

```css
background: var(--panel);            /* = surface */
border: 1px solid var(--line-soft);  /* 只用弱描边 */
border-radius: var(--radius-xl);     /* 16 */
/* 不加 box-shadow */
```
需要"浮起来"时用 `box-shadow: var(--elev-panel)`，**不要自己写 px 阴影**。

### 5.3 表格

```css
th, td { border-bottom: 1px solid var(--line-soft); }  /* 只有横线，无竖线 */
th { color: var(--faint); font-size: 11px; background: var(--bg-secondary); }
```
功能面板（520px）内的表格：

```css
.func-body table { display: block; overflow-x: auto; max-width: 100%; }
.func-body table th, .func-body table td { white-space: nowrap; padding: 9px 7px; }
```
> 列多时**横向滚动**，不要删列、不要让文字换行。

### 5.4 长列表

```css
.intel-item {
  padding: 11px 10px;
  background: transparent;
  border-bottom: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
}
.intel-item:hover { background: var(--hover); }
.intel-item:last-child { border-bottom: none; }
```
**选中态 = `background: var(--surface-2)`**，不要加左侧竖线（历史遗留已全部清除）。

### 5.5 输入框 / 输入条

```css
input, textarea, select { border: 1px solid var(--line-soft); border-radius: var(--radius-md); }
.composer-card { border-radius: var(--radius-panel); }  /* 20，药丸 */
```
发送键：圆形 30px + `background: var(--ink)` + `color: var(--canvas)`。

### 5.6 浮层（菜单 / 提示 / 模态）

**半透明分三档，不要混用**：

```css
/* ① 浮层：毛玻璃 */
.session-dropdown, .settings-modal {
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  -webkit-backdrop-filter: blur(40px) saturate(150%);
  backdrop-filter: blur(40px) saturate(150%);
  box-shadow: var(--elev-prominent);
}

/* ② 遮罩：只压暗，不模糊（DSH --dsw-mask-blur: none） */
.modal-backdrop { background: var(--overlay); backdrop-filter: none; }

/* ③ 交互层 */
button:hover { background: var(--hover); }
button:active { background: var(--active); }
```

> `backdrop-filter` 有性能开销，**只给真正浮在内容上的层**，不要给列表项/卡片。

---

## 6. 禁止项

| ❌ 不要 | ✅ 应该 |
|---|---|
| 组件里写死 `#2d2d2d` / `rgba(0,0,0,.32)` | 用 `var(--surface)` / `var(--elev-panel)` |
| 给卡片加 `box-shadow` | 靠 `--line-soft` 描边 + 底色分层 |
| 用 `background: var(--blue)` 做按钮 | `var(--ink)`（主）/ `var(--btn-subtle)`（弱） |
| 选中态加 `border-left: 3px solid` | `background: var(--surface-2)` |
| 表格加竖线 / 每格线 | 只留 `border-bottom: var(--line-soft)` |

> 面板宽度 520px 下的实测：定时任务表 **478px（正好放下，无需滚动）**、
> 自选 479px、持仓 571px（8 列，横向滚动）。调整列时先跑 `mac-verify` 之类脚本量一下 `scrollWidth`。
| 字号 < 11px | 最小 11px |
| `1px` 描边用在按钮/链接上 | `0.5px`（Retina 发丝线） |
| 弹窗用 96% 不透明遮罩 | `var(--overlay)`（50% / 24%） |

---

## 7. 已知约束

1. **横向滚动与 sticky 表头互斥**
   给表格加 `overflow-x: auto` 会让它成为滚动容器，`position: sticky` 会绑到该容器上；
   而容器高度等于内容高度（纵向不自滚），表头粘不住。
   实测：注水到 2862px 高，滚动 600px 后表头 `top` 从 290 → -310。
   → 结论：**别给表格做 sticky**；长列表用卡片列表（见 5.4），短表格不需要。

2. **`color-mix()` 依赖**：工程里已大量使用，需 Chromium 111+ / Safari 16.2+（Tauri 的 WKWebView 满足）。

3. **主题跟随系统**：`prefers-color-scheme` → `:root.light`。新增颜色**必须两个块都加**，否则浅色下会继承深色值。

---

## 8. 新增页面 checklist

- [ ] 容器用 `--canvas` 或 `--sidebar`，内容块用 `--surface`
- [ ] 卡片：`--line-soft` 描边 + `--radius-xl`，**不加阴影**
- [ ] 按钮只用 `.primary` / `.outline` / `.ghost` / `.danger` / `.small`
- [ ] 表格只有横线；面板内加 `overflow-x: auto` + `nowrap`
- [ ] 长列表用 `.intel-item`（发丝线行），选中用 `--surface-2`
- [ ] 文字至少 11px；正文 13px
- [ ] 浮层加毛玻璃；遮罩用 `--overlay` 且不模糊
- [ ] 深色/浅色都验（`colorScheme: dark|light` 各截一次图）

---

## 9. 代码位置

| 内容 | 位置 |
|---|---|
| 全部 token（深色） | `frontend/src/index.css` → `:root, :root.dark` |
| 全部 token（浅色） | `frontend/src/index.css` → `:root.light` |
| 按钮基类与变体 | `frontend/src/index.css` → `button { }` 起 |
| 面板/卡片 | `.panel, .page-hero` |
| 表格 | `th, td` / `.data-table` / `.func-body table` |
| 长列表 | `.intel-item` |
| 输入条 | `.composer-card` / `.composer-send` |
| 浮层材质 | `.session-dropdown` / `.settings-modal` / `.modal-backdrop` |
| 图标 | 内联 SVG，`stroke="currentColor"`，见 `components/layout/nav.tsx` |

---

## 附：与 DSH 的对应关系（溯源）

| 本项目 | DSH | 出处 |
|---|---|---|
| `--canvas` ~ `--surface-2` | `--dsw-alias-bg-base` / `bg-layer-1..3` | `dsh-web-frontend` 主题块 |
| `--ink` / `--muted` / `--faint` | `label-primary` / `label-secondary` / `label-tertiary` | 同上 |
| `--line` / `--line-soft` | `border-l2` / `border-l1` | 同上 |
| `--hover` / `--active` | `interactive-bg-hover` / `interactive-bg-active` | 同上 |
| `--btn-subtle` | `button-tool-bar-fill`（`rgba(84,85,87,.5)`） | 同上 |
| `--elev-*` | `elevation-panel` / `prominent` / `soft` | 同上 |
| 圆角标度 | `--dsw-radius-xs/sm/md/lg/xl/panel` | `@deepseek-ai/dsh-client-ui-primitives` |
| 按钮尺寸/变体 | `Button.module.css`（md 36 / sm 28，`.outline` 0.5px） | 同上 |
| 毛玻璃配方 | `--dsw-menu-backdrop-filter: blur(40px) saturate(150%)` | 同上 |


---

## 变更记录

### 2026-10 · 向 DSH 靠齐（4 个提交）

| 提交 | 内容 |
|---|---|
| `0273db0` | 布局/数据第一批：权重自算、股票头像取名称首字、面板 424→520、表格可横向滚动、KPI 2×2、去重复 KPI、favicon |
| `8d3d978` | 统计卡 emoji 图标 → 线性 SVG（`components/ui/KpiIcon.tsx`） |
| `fc87dd3` | **token 四步走**：色板（neutral-bluish）+ 圆角 8/12/16/20 + elevation 三段式 + 按钮体系 + 浮层毛玻璃 + 遮罩 96%→50% |
| `c3a684b` | 字号整体提级 228 处 |
| `0ff56c5` | 长列表改发丝线行、去掉 3 处行内左侧竖线、分页激活态改高对比 |
| （本文） | 阴影收敛 22→2、字号下限补齐、任务表收到 478px 免滚动、设计规范成文 |

### 已知未做 / 有意不做

- **sticky 表头**：与横向滚动 CSS 互斥（见 §7），已用长列表替代
- **Toast 彩底**：保留 success/error/info 的语义色，未套毛玻璃
- **面板宽度持久化**：只改了 CSS 默认 520px；若本机存过 `func-panel-w`，需手动拖一次
