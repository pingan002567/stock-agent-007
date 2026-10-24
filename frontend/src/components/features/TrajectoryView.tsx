import { formatLocalTime } from "@/utils/format";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import type { GroupedItem } from "@/components/features/CopilotPanel";
import type { StreamMessage, StreamStep, StreamToolCall } from "@/hooks/useCopilotChat";
import type { CopilotMessage } from "@/api/client";
import type { ToolInfo } from "@/components/features/CopilotMessageItem";

/** 单轮轨迹：把某一轮的工具调用/推理步按到达顺序排开 */
type Turn = {
  key: string;
  index: number;
  at: string;
  prompt: string;
  steps: StreamStep[];
};

function toolInfosToSteps(tools: ToolInfo[]): StreamStep[] {
  return tools.map((t) => ({
    kind: "tool" as const,
    id: t.id,
    tool: {
      callId: t.id,
      name: t.name,
      status: t.failed ? ("failed" as const) : t.done ? ("done" as const) : ("running" as const),
      resultText: t.resultText,
      subagentType: t.subagentType,
      taskDescription: t.taskDescription,
      taskPrompt: t.taskPrompt,
    },
  }));
}

function promptOf(msg: CopilotMessage): string {
  const t = (msg.text ?? "").trim().replace(/\s+/g, " ");
  // 定时任务等系统触发：正文是整段研究员提示词，只取方括号里的来源标签
  const tag = t.match(/^\[([^\]]{1,40})\]/);
  if (tag) return tag[1];
  return t.length > 70 ? `${t.slice(0, 70)}…` : t;
}

/**
 * 轨迹视图（对齐 DSH 的「轨迹」tab）：
 * 把散落在每条消息里的工具调用/推理步，按"轮"聚成一份可纵览的时间线。
 * 原来只能靠消息内折叠区一步步展开，看不出整轮到底跑了什么。
 */
export function TrajectoryView({
  items,
  streamMessage,
  onStreamToolClick,
}: {
  items: GroupedItem[];
  streamMessage: StreamMessage | null;
  onStreamToolClick?: (t: StreamToolCall) => void;
}) {
  const turns: Turn[] = [];
  let lastPrompt = "";
  let turnNo = 0;

  for (const item of items) {
    if (item.t === "msg") {
      if (item.msg.role === "user" && (item.msg.text ?? "").trim()) {
        lastPrompt = promptOf(item.msg);
        turnNo += 1;
      }
      const tools = item.tools ?? [];
      if (tools.length > 0) {
        turns.push({
          key: item.msg.message_id ?? `${item.msg.run_id}-${turns.length}`,
          index: turnNo || turns.length + 1,
          at: item.msg.created_at ?? "",
          prompt: lastPrompt,
          steps: toolInfosToSteps(tools),
        });
      }
      continue;
    }
    // t === "ai"：这一轮的收口消息，工具挂在这里
    if (item.tools.length > 0) {
      turns.push({
        key: item.msg.message_id ?? `${item.msg.run_id}-${turns.length}`,
        index: turnNo || turns.length + 1,
        at: item.msg.created_at ?? "",
        prompt: lastPrompt,
        steps: toolInfosToSteps(item.tools),
      });
    }
  }

  const liveSteps = streamMessage?.steps ?? [];
  const totalSteps = turns.reduce((n, t) => n + t.steps.length, 0) + liveSteps.length;

  if (turns.length === 0 && liveSteps.length === 0) {
    return (
      <div className="trajectory">
        <div className="trajectory-empty">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="6" cy="6" r="2" /><circle cx="6" cy="18" r="2" /><circle cx="18" cy="12" r="2" />
            <path d="M8 6h4a3 3 0 0 1 3 3v0M8 18h4a3 3 0 0 0 3-3v0" />
          </svg>
          <div className="trajectory-empty-title">这一轮还没有工具调用</div>
          <div className="trajectory-empty-desc">
            问一个需要查数据的问题（比如「分析 600519」），这里会按轮次列出它调用了哪些工具、每步的结果。
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="trajectory">
      <div className="trajectory-head">
        <span className="trajectory-title">执行轨迹</span>
        <span className="trajectory-meta">
          {turns.length} 轮 · {totalSteps} 步
        </span>
      </div>

      <div className="trajectory-list">
        {turns.map((turn) => (
          <section key={turn.key} className="trajectory-turn">
            <header className="trajectory-turn-head">
              <span className="trajectory-turn-no">第 {turn.index} 轮</span>
              {turn.at ? <span className="trajectory-turn-time">{formatLocalTime(turn.at)}</span> : null}
              <span className="trajectory-turn-count">{turn.steps.length} 步</span>
            </header>
            {turn.prompt ? <div className="trajectory-turn-prompt">{turn.prompt}</div> : null}
            <ThoughtTimeline steps={turn.steps} active={false} onToolClick={onStreamToolClick} expandAll />
          </section>
        ))}

        {liveSteps.length > 0 ? (
          <section className="trajectory-turn trajectory-live">
            <header className="trajectory-turn-head">
              <span className="trajectory-turn-no">
                <i className="trajectory-live-dot" />
                进行中
              </span>
              <span className="trajectory-turn-count">{liveSteps.length} 步</span>
            </header>
            <ThoughtTimeline
              steps={liveSteps}
              active
              onToolClick={onStreamToolClick}
              expandAll
            />
          </section>
        ) : null}
      </div>
    </div>
  );
}
