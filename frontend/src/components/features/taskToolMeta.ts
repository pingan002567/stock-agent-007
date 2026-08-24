/** task 工具参数解析（流式 arguments + 持久化 task_meta） */

export interface TaskToolMeta {
  subagentType?: string;
  description?: string;
  prompt?: string;
}

function pickStr(v: unknown): string | undefined {
  if (v === null || v === undefined) return undefined;
  const s = String(v).trim();
  return s || undefined;
}

export function parseTaskToolArgs(args: unknown): TaskToolMeta {
  let raw = args;
  if (typeof raw === "string") {
    try { raw = JSON.parse(raw); } catch { raw = {}; }
  }
  if (!raw || typeof raw !== "object") return {};
  const o = raw as Record<string, unknown>;
  return {
    subagentType: pickStr(o.subagent_type ?? o.subagentType),
    description: pickStr(o.description),
    prompt: pickStr(o.prompt ?? o.task),
  };
}

/** 从 tool_call SSE / 持久化 message payload 提取委派元数据 */
export function parseTaskToolPayload(payload: Record<string, unknown> | undefined): TaskToolMeta {
  if (!payload) return {};
  const tm = payload.task_meta;
  if (tm && typeof tm === "object") {
    const t = tm as Record<string, unknown>;
    return {
      subagentType: pickStr(t.subagent_type ?? t.subagentType),
      description: pickStr(t.description),
      prompt: pickStr(t.prompt),
    };
  }
  if (payload.arguments !== undefined) {
    return parseTaskToolArgs(payload.arguments);
  }
  if (payload.arguments_preview && typeof payload.arguments_preview === "object") {
    return parseTaskToolArgs(payload.arguments_preview);
  }
  return {
    subagentType: pickStr(payload.subagent_type),
    description: pickStr(payload.description),
    prompt: pickStr(payload.prompt),
  };
}

export function mergeTaskMeta(
  base: TaskToolMeta | undefined,
  extra: TaskToolMeta,
): TaskToolMeta {
  return {
    subagentType: extra.subagentType ?? base?.subagentType,
    description: extra.description ?? base?.description,
    prompt: extra.prompt ?? base?.prompt,
  };
}

export function truncateText(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}
