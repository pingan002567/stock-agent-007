import { useState } from "react";
import { skillTraceItems, type SkillTraceItem } from "@/api/copilot";

/** final payload 的富信息条：信心度 / 反方观点 / 引用来源 / skill 链路 / token 成本。
 *  流式气泡（final 阶段）与持久化消息共用。 */

const CONFIDENCE_META: Record<string, { label: string; color: string; bg: string }> = {
  high: { label: "信心度 高", color: "var(--green)", bg: "var(--green-soft)" },
  medium: { label: "信心度 中", color: "var(--amber)", bg: "var(--amber-soft)" },
  low: { label: "信心度 低", color: "var(--red)", bg: "var(--red-soft)" },
};

function asStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).filter(Boolean);
}

function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

// 预算语义状态（available/required=可委派，delegated/done=实际发生，missed=必跑缺席）
const TRACE_STATUS_CLASS: Record<string, string> = {
  blocked: " blocked",
  delegated: " active",
  done: " done",
  missed: " missed",
  over_budget: " missed",
};

// 徽章链只在实际发生过委派后出现:纯白名单(available/required)是"额度"
// 而非执行,闲聊轮展示它只会造成"调用了技能"的误解
const OBSERVED = new Set(["delegated", "done", "missed", "over_budget"]);

export function SkillTraceChain({ items }: { items: SkillTraceItem[] }) {
  if (items.length === 0) return null;
  if (!items.some((item) => OBSERVED.has(item.status ?? ""))) return null;
  return (
    <div className="skill-trace-chain">
      {items.map((item, i) => (
        <span key={item.skill || i} className="skill-trace-node">
          {i > 0 && <span className="skill-trace-arrow">→</span>}
          <span
            className={`skill-trace-chip${TRACE_STATUS_CLASS[item.status || ""] || ""}`}
            title={[item.status, item.purpose, item.blocked_reason].filter(Boolean).join(" · ")}
          >
            {item.label || item.skill}
            {item.authority_level && <span className="skill-trace-auth">{item.authority_level}</span>}
          </span>
        </span>
      ))}
    </div>
  );
}

export function CopilotFinalMeta({ payload }: { payload: Record<string, unknown> }) {
  const [openCounter, setOpenCounter] = useState(false);
  const [openRefs, setOpenRefs] = useState(false);

  const confidence = CONFIDENCE_META[String(payload.confidence || "")];
  const counterReasons = asStringArray(payload.counter_reasons);
  const evidenceRefs = asStringArray(payload.evidence_refs);
  const trace = skillTraceItems(payload.skill_trace);
  const usage = (payload.usage || {}) as Record<string, unknown>;
  const tokensIn = Number(usage.input_tokens || usage.prompt_tokens || 0);
  const tokensOut = Number(usage.output_tokens || usage.completion_tokens || 0);
  const cost = Number(payload.cost_estimate || 0);

  const hasAny =
    confidence || counterReasons.length > 0 || evidenceRefs.length > 0 || trace.length > 0 || tokensIn + tokensOut > 0;
  if (!hasAny) return null;

  return (
    <div className="final-meta">
      <SkillTraceChain items={trace} />
      <div className="final-meta-badges">
        {confidence && (
          <span className="final-meta-badge" style={{ color: confidence.color, background: confidence.bg }}>
            {confidence.label}
          </span>
        )}
        {counterReasons.length > 0 && (
          <button className="final-meta-toggle" onClick={() => setOpenCounter((v) => !v)}>
            {openCounter ? "▼" : "▶"} 反方观点 {counterReasons.length}
          </button>
        )}
        {evidenceRefs.length > 0 && (
          <button className="final-meta-toggle" onClick={() => setOpenRefs((v) => !v)}>
            {openRefs ? "▼" : "▶"} 引用来源 {evidenceRefs.length}
          </button>
        )}
        {tokensIn + tokensOut > 0 && (
          <span className="final-meta-usage">
            {formatTokens(tokensIn)} in / {formatTokens(tokensOut)} out
            {cost > 0 && ` · ≈$${cost.toFixed(4)}`}
          </span>
        )}
      </div>
      {openCounter && (
        <ul className="final-meta-list counter">
          {counterReasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}
      {openRefs && (
        <ul className="final-meta-list refs">
          {evidenceRefs.map((ref, i) => (
            <li key={i}>{ref}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
