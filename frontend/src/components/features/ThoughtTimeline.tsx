import { useState } from "react";
import { toolLabel, type StreamStep, type StreamToolCall } from "@/hooks/useCopilotChat";
import { toolParamSummary } from "@/components/features/taskToolMeta";
import { formatDuration } from "@/utils/format";
import { skillLabelOf } from "@/components/features/skillLabels";
import { truncateText } from "@/components/features/taskToolMeta";
import { summarizeToolResult } from "@/lib/toolResultSummary";
import { commandOutputOf, exitCodeOf, loopStats } from "@/lib/agentLoop";

/** Agent loop 时间线（DSH / Claude Code 的表现）：
 *
 *  一整轮回答的「思考 → 工具 → 思考 → 命令 → …」收成一个可折叠的 loop：
 *  - 头部一行统计（思考几步 / 调用几个工具 / 几条命令 / 用时 / 几轮）
 *  - 流式中默认展开、完成后默认折叠（用户手动状态优先）
 *  - 三种节点视觉分层：思考（灰）/ 工具（等宽）/ 命令（终端块）
 *  - 状态三档：成功 ✓ / 降级 ! / 失败 ✕
 */

/** 结果短就压成一行，长或带换行才展开成 3 行块 */
const OUTPUT_BLOCK_THRESHOLD = 120;

function SparkIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3l1.9 5.7L19.6 10l-5.7 1.9L12 17.6l-1.9-5.7L4.4 10l5.7-1.9z" />
    </svg>
  );
}

function ToolIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  );
}

function TermIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="5" width="16" height="14" rx="2" />
      <path d="M7.5 10.5L10 13l-2.5 2.5M13 15.5h4" />
    </svg>
  );
}

function SubagentIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="5" y="7" width="14" height="11" rx="2" />
      <path d="M12 3v4M8 12h.01M16 12h.01M9 16h6" />
    </svg>
  );
}

/** 单次耗时：工具级用「0.8s」这种短格式，loop 级用 formatDuration */
function fmtMs(ms?: number): string {
  if (!ms || !Number.isFinite(ms) || ms < 0) return "";
  const sec = ms / 1000;
  return sec < 10 ? `${sec.toFixed(1)}s` : `${Math.round(sec)}s`;
}

function taskEngLabel(tool: StreamToolCall): string {
  if (tool.subagentType) return tool.subagentType;
  if (tool.taskDescription) return truncateText(tool.taskDescription, 48);
  if (tool.taskPrompt) return truncateText(tool.taskPrompt, 48);
  return "task";
}

function toolResultLine(tool: StreamToolCall): string | null {
  if (tool.status === "running" || !tool.resultText) return null;
  const summary = summarizeToolResult(tool.name, tool.resultText);
  if (summary) return summary;
  const raw = tool.resultText.replace(/\s+/g, " ").trim();
  // 结构化 payload 但取不到可读字段 → 不显示这一行：
  // 状态已由右侧 ✓/! 表达，重复一遍「已完成」没有信息量，露原始 JSON 更糟
  if (!raw || raw.startsWith("{") || raw.startsWith("[")) return null;
  return truncateText(raw, 72);
}

/** 状态点：成功 / 降级 / 失败 / 进行中 */
function statusOf(tool: StreamToolCall): { cls: string; glyph: string; title: string } {
  if (tool.status === "running") return { cls: "busy", glyph: "…", title: "执行中" };
  if (tool.status === "failed") return { cls: "bad", glyph: "✕", title: "失败" };
  if (tool.degraded) return { cls: "warn", glyph: "!", title: "部分可用（降级）" };
  return { cls: "ok", glyph: "✓", title: "成功" };
}

/** 工具结果块：默认 3 行，点开看全文 */
function OutputBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const body = text.replace(/\s+$/, "");
  const lines = body.split("\n").length;
  const collapsible = lines > 3 || body.length > OUTPUT_BLOCK_THRESHOLD;
  return (
    <>
      <div
        className={`out${collapsible && !open ? " clamp" : ""}`}
        role={collapsible ? "button" : undefined}
        tabIndex={collapsible ? 0 : undefined}
        title={collapsible && !open ? "点击展开" : undefined}
        onClick={collapsible ? (e) => { e.stopPropagation(); setOpen((v) => !v); } : undefined}
        onKeyDown={collapsible ? (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen((v) => !v); }
        } : undefined}
      >
        {body}
      </div>
      {collapsible ? (
        <button
          type="button"
          className="out-more"
          onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        >
          {open ? "收起" : `展开全部（${lines} 行）`}
        </button>
      ) : null}
    </>
  );
}

function ToolStepRow({ tool, onClick }: { tool: StreamToolCall; onClick?: (t: StreamToolCall) => void }) {
  const running = tool.status === "running";
  const st = statusOf(tool);
  const resultLine = toolResultLine(tool);
  const raw = (tool.resultText ?? "").replace(/\s+$/, "");
  // 结构化结果（JSON）一律用块：短 JSON 走一行会因「看起来像 JSON」被丢掉，
  // 结果就是工具调用下面空空一片。
  const structured = raw.startsWith("{") || raw.startsWith("[");
  const useBlock = Boolean(raw) && (structured || raw.length > OUTPUT_BLOCK_THRESHOLD || raw.includes("\n"));

  if (tool.name === "task") {
    const skillLabel = skillLabelOf(tool.subagentType) ?? toolLabel(tool.name);
    return (
      <div
        className={`tl-step subtask${running ? " running" : ""}`}
        onClick={onClick ? () => onClick(tool) : undefined}
        role={onClick ? "button" : undefined}
      >
        <span className="tl-step-icon subagent"><SubagentIcon /></span>
        <div className="tl-step-main">
          <div className="tl-step-row">
            <span className={`tl-step-label${running ? " shimmer" : ""}`}>{skillLabel}</span>
            {paramOf(tool) ? <span className="tl-step-param">{paramOf(tool)}</span> : null}
            <span className="tl-step-eng">{taskEngLabel(tool)}</span>
            <span className="tool-tail">
              {fmtMs(tool.durationMs) ? <span>{fmtMs(tool.durationMs)}</span> : null}
              <span className={`tl-state-dot ${st.cls}`} title={st.title}>{st.glyph}</span>
            </span>
          </div>
          {resultLine ? <div className="tl-step-result">→ {resultLine}</div> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="tl-step" onClick={onClick ? () => onClick(tool) : undefined} role={onClick ? "button" : undefined}>
      <span className="tl-step-icon"><ToolIcon /></span>
      <div className="tl-step-main">
        <div className="tool-head">
          <span className={`tl-step-label${running ? " shimmer" : ""}`}>{toolLabel(tool.name)}</span>
          {paramOf(tool) ? <span className="tl-step-param">{paramOf(tool)}</span> : null}
          {/* 没有中文标签时 toolLabel 会回退成工具名，别显示两遍 */}
          {toolLabel(tool.name) !== tool.name ? <span className="tl-step-eng">{tool.name}</span> : null}
          <span className="tool-tail">
            {fmtMs(tool.durationMs) ? <span>{fmtMs(tool.durationMs)}</span> : null}
            <span className={`tl-state-dot ${st.cls}`} title={st.title}>{st.glyph}</span>
          </span>
        </div>
        {useBlock ? <OutputBlock text={raw} /> : resultLine ? <div className="tl-step-result">→ {resultLine}</div> : null}
      </div>
    </div>
  );
}

/** 命令执行：命令行 + 深色 stdout + exit code（和结构化 JSON 结果分开渲染） */
function CommandRow({ tool, onClick }: { tool: StreamToolCall; onClick?: (t: StreamToolCall) => void }) {
  const running = tool.status === "running";
  const st = statusOf(tool);
  const command = commandOf(tool);
  const exit = exitCodeOf(tool);
  const commandOutput = commandOutputOf(tool);
  return (
    <div className="tl-step" onClick={onClick ? () => onClick(tool) : undefined} role={onClick ? "button" : undefined}>
      <span className="tl-step-icon cmd"><TermIcon /></span>
      <div className="tl-step-main">
        <div className="cmd-line">
          <span className="prompt">$</span>
          <span className={`cmd-text${running ? " shimmer" : ""}`} title={command}>{command}</span>
          <span className="tool-tail">
            {fmtMs(tool.durationMs) ? <span>{fmtMs(tool.durationMs)}</span> : null}
            <span className={`tl-state-dot ${st.cls}`} title={st.title}>{st.glyph}</span>
          </span>
        </div>
        {commandOutput ? (
          <pre className={`cmd-out${tool.status === "failed" ? " failed" : ""}`}>{commandOutput}</pre>
        ) : null}
        {exit != null ? <div className="cmd-exit">exit {exit}</div> : null}
      </div>
    </div>
  );
}

/** bash 类工具的命令行：优先 args.command / cmd / script */
function commandOf(tool: StreamToolCall): string {
  const args = (tool.args ?? {}) as Record<string, unknown>;
  const direct = args.command ?? args.cmd ?? args.script ?? args.code;
  if (typeof direct === "string" && direct.trim()) return direct.replace(/\s+/g, " ").trim();
  const json = JSON.stringify(args);
  return json === "{}" ? tool.name : truncateText(json, 120);
}

/** 思考行：照 DSH 现状排版 —— 图标 + 「思考」+ · + 文本，平铺在步骤流里。
 *  文本过长（>90 字或带换行）时默认收起 3 行，点一下展开。 */
function ReasoningRow({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  const compact = (text || "").replace(/\n{2,}/g, "\n").trim();
  if (!compact) return null;
  const collapsible = compact.length > 90 || compact.includes("\n");
  const toggle = () => setOpen((v) => !v);
  return (
    <div className={`tl-step tl-think${streaming ? " streaming" : ""}${open ? " open" : ""}`}>
      <span className="tl-step-icon reasoning"><SparkIcon /></span>
      <span className="tl-think-label">思考</span>
      <span className="tl-think-sep" aria-hidden>·</span>
      <span
        className="tl-think-text"
        role={collapsible ? "button" : undefined}
        tabIndex={collapsible ? 0 : undefined}
        title={collapsible && !open ? compact : undefined}
        onClick={collapsible ? toggle : undefined}
        onKeyDown={collapsible ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } } : undefined}
      >
        {compact}
      </span>
    </div>
  );
}

/** 步骤行的"对象"：个股代码 / 搜索关键词等，取不到就不显示 */
function paramOf(tool: StreamToolCall): string {
  return toolParamSummary(tool.args);
}

export function ThoughtTimeline({ steps, active, expandAll = false, durationMs }: {
  steps: StreamStep[];
  /** 流式进行中(尾步高亮/shimmer) */
  active: boolean;
  onToolClick?: (t: StreamToolCall) => void;
  /** 轨迹视图用：强制展开，且不显示折叠头 */
  expandAll?: boolean;
  /** 本轮用时 */
  durationMs?: number;
}) {
  // 用户手动折叠/展开优先；没动过就跟着流式状态走（流式展开、完成收起）
  const [manual, setManual] = useState<boolean | null>(null);
  if (steps.length === 0) return null;

  const stats = loopStats(steps);
  const open = expandAll || (manual ?? active);

  const parts: string[] = [];
  if (stats.reasoning) parts.push(`思考 ${stats.reasoning} 步`);
  if (stats.tools) parts.push(`调用 ${stats.tools} 个工具`);
  if (stats.commands) parts.push(`${stats.commands} 条命令`);
  if ((durationMs ?? 0) > 0) parts.push(formatDuration(durationMs ?? 0));
  const title = parts.length ? parts.join(" · ") : `执行 ${steps.length} 步`;

  return (
    <div className={`thought-timeline agent-loop${open ? " open" : ""}`}>
      {expandAll ? null : (
        <button
          type="button"
          className="loop-head"
          aria-expanded={open}
          onClick={() => setManual(!open)}
        >
          <span className={`loop-icon${active ? " live" : ""}`}>
            {active ? <span className="loop-spin" aria-hidden /> : <SparkIcon />}
          </span>
          <span className="loop-title">{active ? "正在思考…" : title}</span>
          {stats.rounds > 0 ? <span className="loop-rounds">{stats.rounds} 轮</span> : null}
          <span className="loop-chev" aria-hidden>▶</span>
        </button>
      )}
      <div className="loop-body">
        <div className="tl-steps">
          {steps.map((step, i) => {
            const isLast = i === steps.length - 1;
            if (step.kind === "reasoning") {
              return (
                <ReasoningRow
                  key={step.id}
                  text={step.text}
                  streaming={active && isLast}
                />
              );
            }
            if (step.tool.kind === "command") {
              return <CommandRow key={step.id} tool={step.tool} />;
            }
            return <ToolStepRow key={step.id} tool={step.tool} />;
          })}
        </div>
      </div>
    </div>
  );
}
