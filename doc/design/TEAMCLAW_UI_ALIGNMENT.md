# UI 向 TeamClaw 对齐 —— 调研分析

**Status:** 已实施 P0-P3（2026-07-16：`4f23e95` token 地基 / `b6befa8` 聊天三件套 / `990057c` Composer+微交互）。设置三原语与头像色板亦已完成（SettingCard/SectionHeader 合一原语 + ToggleSwitch + actorColor 10 色盘/AI 方盘人圆形）——对齐清单全部落地
**素材:** TeamClaw `AGENTS.md` §1-§8（设计规范原文）+ `packages/app/` 实现实测（globals.css / App.tsx / message.tsx / ToolCallCard.tsx / Settings.tsx / button.tsx 等）

---

## 1. TeamClaw 设计体系的核心事实

设计方向 **“Editorial Calm”**：纸感中性色、品牌色只做小面积点缀、中文优先排版、信息密度高于典型聊天应用但卡片内留呼吸感。

### 1.1 token 体系（唯一源 `globals.css`，Tailwind v4 `@theme inline`）

- **表面四层语义**（light 为正典主题）：
  `--background #fbfaf7`（画布）→ `--paper #ffffff`（卡片/消息面）→ `--panel #efece4`（侧栏）→ `--selected #e7e2d6`（选中行）
- **墨色四层**：`--foreground #1a1a14` → `--ink-2 #3d3c34` → `--muted-foreground #75736a` → `--faint #a8a6a0`（时间戳/meta/分组标签）
- **边框双级**：`--border rgba(26,26,20,.08)` / `--border-soft rgba(26,26,20,.05)`
- **强调色宪法**：珊瑚 `--coral #e85a4a`，**每屏最多 2 处**，白名单=活跃会话左条(2px)/未读徽标/发送键/AI pill 边/AI 头像环。success、focus、link、hover 一律禁用品牌色，改用 ink/muted/border。危险色 `--destructive` 独立于品牌色。
- **字体**：`PingFang SC` 打头的中文优先 sans 栈；mono = JetBrains Mono/SF Mono，**mono 专用于时间戳、工具参数、模型名、版本号、键盘 pill**。
- **字号阶梯**（硬编码精确值，禁止取整）：15/700 区块标题 → 13.5 消息正文 → 13/600 卡片标题 → 12.5 次级正文 → 12 预览/meta → 11.5 页脚 → 11 mono 时间戳 → 10.5/600 大写分组 → 9.5 mono AI pill。
- **圆角语义**：面板 14 / 气泡 16+说话侧 6 / 按钮 pill 7-8 / 内联 chip 3-4 / 工具卡 8。
- **头像 10 色板**（`actor-color.ts`）：按 actorId 哈希稳定取色，白字首字母；**AI = 圆角方块、人类 = 圆形**，20px 下即可辨类型；禁止灰色兜底。
- **暗色主题是通用 shadcn 中性灰（oklch）**，未精雕——TeamClaw 的设计工夫全在浅色。

### 1.2 布局（三栏 shell）

`NavRail 快捷入口列 │ 列表列(320px 固定) │ 聊天主区`。无拖拽 resize，靠 900/1024 两档断点；窗口 chrome 区只放原生红绿灯+右对齐品牌字，**禁止 logo 图形**。列表卡片按 今天/昨天/本周/更早 分组（10.5px 大写 faint + mono 计数）；活跃卡 = paper 底 + 2px coral 左条，hover 只微暗**不加阴影**。

### 1.3 消息三形态（§3，核心识别性决策）

- **用户消息**：右对齐气泡，`max-w-85%`（规范写 65%，实测 85%），16px 圆角+右下 6px 说话角。
- **AI 回复不是气泡，是“便签”（note）**：头像+名+AI badge+`model · time`(mono faint)+右侧复制/重试图标 → 正文 13.5/1.7 → 可选虚线顶边两列要点格 → 可选追问 pills。正文与头像列对齐（33px 缩进沟）。AI 文字内容不允许上品牌色。
- **工具调用卡**：8px 圆角双行 mono 卡——`● tool 名(参数…)  ok · 0.4s` / `→ 结果截断`；状态点 成功绿/失败红/进行琥珀。

### 1.4 Composer（§4）

纸面卡片（14px 圆角 + `0 4px 16px -10px` 轻阴影），上区 textarea、下区以 border-soft 分隔：`[Agent/模型 pill ▾] [📎] [@] [✨] …… ⌘↵(mono faint) [发送]`。发送键实测为 32px 珊瑚图标按钮，流式中切换为停止键。

### 1.5 设置页

左导航 240px（手风琴分组，展开态 `--selected` 底+加粗）+ 右内容；底部 mono 版本号 + 更新按钮。共享三原语：`SettingCard`(14px 圆角 paper 卡) / `SectionHeader`(图标盒+15px 标题+12.5px 描述) / `ToggleSwitch`(开=绿、关=墨)。

### 1.6 微交互

- hover 惯例 `hover:bg-selected/60`，过渡压倒性使用 `transition-colors duration-200`；
- **所有交互元素 `cursor: default`**（去“web 手型”，营造原生感）；
- focus ring 组件自持（1.5px ring），全局不强加；
- `prefers-reduced-motion` 全局降级动画；
- 流式动效：shimmer 文字光扫、跳动点、`--coral` 块状终端光标。

### 1.7 规范 vs 实现的已知偏差（对齐时以实测为准）

用户气泡实测 `#e8edf2` 蓝灰（规范写深墨）；工具卡实测 14/16px 圆角蓝灰系（规范写 8px 纸面）；发送键实测图标按钮（规范写文字按钮）。设计意图不变：**coral 克制、AI 非气泡、纸感中性、中文优先、mono 管元信息**。

---

## 2. 我们的现状 vs 差距对照

| 维度 | TeamClaw | 本项目现状 | 差距评级 |
|---|---|---|---|
| 表面语义 token | bg/paper/panel/selected 四层 + 双级边框 | 位置命名（bg-secondary/tertiary/panel/soft 混用），无 selected/border-soft 语义 | ★★★ 根基 |
| 强调色纪律 | 品牌色每屏≤2处，白名单制 | 蓝色遍布（按钮/active/状态点/链接/信心度 chip…）；工具卡“完成”仍用绿 | ★★★ |
| 字体 | 中文优先本地栈 | **Google Fonts 拉 Inter+JetBrains Mono**（Latin 优先 + 桌面离线会退化），中文回退 PingFang | ★★★ |
| 字号/圆角标度 | 明确阶梯 | 组件内随手写 fontSize，圆角只有 8/12/16 三档无语义 | ★★ |
| 三栏布局 | NavRail+列表列+聊天 | 左栏(会话+设置)+聊天+右功能坞——**产品化差异，已拍板，不对齐** | —（保留） |
| 会话卡 | 2px 品牌左条+paper 底+两行预览+右上 mono 时间 | 左条✓ 分组✓；无预览行，时间在标题下 | ★ |
| 用户消息 | 右对齐 85% 气泡+说话角 | 通栏卡片，对称圆角，琥珀底 | ★★ |
| AI 回复 | **便签体**（头像行+正文+要点格+追问 pills，非气泡） | 蓝底通栏卡片（气泡系） | ★★★ 识别性最强的一项 |
| 工具卡 | 双行 mono：名(参数) + 状态·耗时 / →结果 | 单行标题+200字预览体，无参数/耗时 | ★★ |
| Composer | 纸面卡：pill/附件/⌘↵/图标发送键，流式切停止 | 裸一行：附件+textarea+发送；停止键已有；无模型 pill、无 ⌘↵ 提示 | ★★ |
| 设置页 | 左导航+SettingCard/SectionHeader/ToggleSwitch 三原语+版本沉底 | 左导航✓ 版本沉底✓；卡片是旧 panel 体、无统一开关/头部原语 | ★（骨架已对齐） |
| 微交互 | colors-200 惯例、cursor default、reduced-motion、focus 自持 | transition 随手写、pointer 手型、无 reduced-motion | ★★ |
| 头像体系 | 10 色稳定盘、AI 方/人圆 | 无头像体系（仅 Z 占位） | ★（我们单人场景弱需求） |

---

## 3. 关键决策点（需拍板）

1. **主题方向**：TeamClaw 正典是浅色纸感、暗色是敷衍灰；我们正典是暗色金融终端、浅色刚补。
   **建议**：不掉头。暗色仍为主打（金融终端场景合理），但把我们的**浅色主题整体换成 Editorial Calm 的值**（#fbfaf7/#ffffff/#efece4/#e7e2d6 + 暖墨），暗色只做语义 token 化改造。
2. **品牌色**：不换 coral（与 A 股红涨语义冲突、且我们图标是蓝系）。**对齐的是“预算纪律”**：蓝每屏≤2处（当前屏 active + 主按钮），白名单制；工具状态/成功态改 ink/muted。红绿继续锁死涨跌语义。
3. **AI 便签化**：建议跟。这是 TeamClaw 观感差异的最大单项，且我们的 AI 回复本来就带工具卡/信心度/引用等结构化元信息，便签体（头像行+正文+meta 行）比气泡更承载。
4. **布局不回改**：NavRail+双列不采纳（已拍板合并左栏）；右侧功能坞是我们的产品差异保留项。

---

## 4. 建议实施路线（待批准后执行）

| 批次 | 内容 | 量级 |
|---|---|---|
| **P0 token 地基** | ① 表面四层+边框双级+墨色四层语义 token（先映射旧变量再逐文件迁移）② 中文优先字体栈、去 Google Fonts 网络依赖 ③ 圆角/字号标度定义 ④ 浅色主题换 Editorial Calm 值 | 1 天 |
| **P1 聊天三件套** | ① AI 回复便签化（头像行+meta+正文+追问 pills）② 用户消息右对齐说话角气泡 ③ 工具卡双行 mono 形态（名+参数+状态·耗时/→结果） | 1-2 天 |
| **P2 Composer + 会话卡** | 纸面卡 composer（模型 pill 接真实 runtime 配置、⌘↵ 提示、图标发送/停止）；会话卡两行预览+右上时间 | 1 天 |
| **P3 设置原语 + 微交互** | SettingCard/SectionHeader/ToggleSwitch 三原语替换旧 panel 体；transition-colors 200ms 统一、cursor default、reduced-motion、focus ring 纪律；强调色预算清扫 | 1 天 |

不跟的：coral 换色、NavRail 双列、列表虚拟化（会话量小）、字号硬编码写法（我们保持 token 化）、Supabase/多人协作相关一切。

---

## 5. 参考文件索引（TeamClaw 仓库内）

- 设计规范：`AGENTS.md` §1-§8
- token：`packages/app/src/styles/globals.css`
- 消息：`packages/ai/message.tsx`、`components/chat/ChatMessage.tsx`、`ToolCallCard.tsx`
- Composer：`components/chat/ChatInputArea.tsx`、`packages/ai/prompt-input-ui.tsx`、`AgentSelectorDock.tsx`
- 设置：`components/settings/Settings.tsx`、`settings/shared/{SettingCard,SectionHeader,ToggleSwitch}.tsx`
- 头像色：`packages/app/src/lib/actor-color.ts`
- 断点：`hooks/use-layout-breakpoint.ts`
