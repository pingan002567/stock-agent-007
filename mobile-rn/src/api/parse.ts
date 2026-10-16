import type { SSEEvent } from './sse';
import type { AssistantState, Clarification, ClarificationOption, SkillTraceStep, ToolChip } from '../types';
import { emptyAssistant } from '../types';

export type StreamUpdate =
  | { kind: 'reasoning'; text: string }
  | { kind: 'tool_call'; callId: string; name: string }
  | { kind: 'tool_result'; callId: string; preview: string }
  | { kind: 'partial_answer'; text: string }
  | { kind: 'final_answer'; text: string }
  | { kind: 'clarification'; request: Clarification | null; text: string }
  | { kind: 'skill_trace'; steps: SkillTraceStep[] }
  | { kind: 'error'; message: string }
  | { kind: 'title'; title: string }
  | { kind: 'liveness' }
  | { kind: 'ignore' };

function asObj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

/**
 * 事件归约。语义对齐 iOS `CopilotStreamParser`（ChatModels.swift:203-289）：
 * type 双轨（event.type 优先，回退 obj.type）、payload 双轨（payload 子对象或平铺）。
 */
export function parseStreamEvent(event: SSEEvent): StreamUpdate {
  let obj: Record<string, unknown>;
  try {
    obj = JSON.parse(event.data) as Record<string, unknown>;
  } catch {
    return { kind: 'ignore' };
  }
  const type = event.type && event.type !== 'message' ? event.type : ((obj.type as string) ?? 'message');
  const payload = asObj(obj.payload);

  const str = (...keys: string[]): string => {
    for (const k of keys) {
      const v = payload[k] ?? obj[k];
      if (typeof v === 'string' && v.length > 0) return v;
    }
    return '';
  };

  switch (type) {
    case 'reasoning': {
      const text = str('text', 'latest_text');
      return text ? { kind: 'reasoning', text } : { kind: 'ignore' };
    }
    case 'tool_call': {
      const name = str('tool', 'name') || 'tool';
      if (name === 'write_todos') return { kind: 'ignore' };
      const callId = str('call_id') || `${name}-${Date.now()}`;
      return { kind: 'tool_call', callId, name };
    }
    case 'tool_result': {
      const callId = str('call_id');
      if (!callId) return { kind: 'ignore' };
      return { kind: 'tool_result', callId, preview: toolResultPreview(payload) };
    }
    case 'partial_answer':
    case 'message': {
      const text = str('text', 'content');
      return text ? { kind: 'partial_answer', text } : { kind: 'ignore' };
    }
    case 'final':
    case 'final_answer': {
      const clar = parseClarification(payload.clarification) ?? parseClarification(obj.clarification);
      if (clar) return { kind: 'clarification', request: clar, text: clar.question };
      return { kind: 'final_answer', text: str('conclusion', 'text', 'content') };
    }
    case 'clarification': {
      const req = parseClarification(payload) ?? parseClarification(obj);
      const text = req?.question ?? str('question', 'text');
      return { kind: 'clarification', request: req, text };
    }
    case 'skill_trace': {
      const steps = parseSkillTrace(payload.items ?? payload.skill_trace ?? payload) ?? parseSkillTrace(obj.skill_trace);
      return steps.length ? { kind: 'skill_trace', steps } : { kind: 'ignore' };
    }
    case 'error': {
      return { kind: 'error', message: str('message', 'error') || event.data };
    }
    case 'title': {
      const title = str('title');
      return title ? { kind: 'title', title } : { kind: 'ignore' };
    }
    case 'ping':
    case 'progress':
      return { kind: 'liveness' };
    default:
      return { kind: 'ignore' };
  }
}

function toolResultPreview(payload: Record<string, unknown>): string {
  for (const k of ['text', 'output', 'result', 'result_preview']) {
    const v = payload[k];
    if (typeof v === 'string' && v.length > 0) return v.slice(0, 2000);
  }
  const rp = asObj(payload.result_preview);
  for (const k of ['text', 'output', 'result']) {
    const v = rp[k];
    if (typeof v === 'string' && v.length > 0) return v.slice(0, 2000);
  }
  return '';
}

function parseClarification(raw: unknown): Clarification | null {
  const o = asObj(raw);
  const question = (o.question as string) ?? (o.text as string) ?? '';
  if (!question.trim()) return null;
  const requestId = (o.request_id as string) ?? (o.call_id as string) ?? `clarification:${Date.now()}`;
  const optionsRaw = Array.isArray(o.options) ? o.options : [];
  const options: ClarificationOption[] = [];
  optionsRaw.forEach((item, idx) => {
    if (typeof item === 'string' && item.trim()) {
      options.push({ id: `opt-${idx + 1}`, label: item.trim(), value: item.trim() });
    } else {
      const io = asObj(item);
      const label = (io.label as string) ?? (io.value as string) ?? '';
      const value = (io.value as string) ?? label;
      const id = (io.id as string) ?? `opt-${idx + 1}`;
      if (label) options.push({ id, label, value });
    }
  });
  return {
    requestId,
    question,
    options,
    inputMode: (o.input_mode as string) ?? (options.length ? 'choice_with_other' : 'free_text'),
  };
}

function parseSkillTrace(raw: unknown): SkillTraceStep[] {
  const rows: unknown[] = Array.isArray(raw) ? raw : asObj(raw).items && Array.isArray(asObj(raw).items) ? (asObj(raw).items as unknown[]) : [raw];
  return rows
    .map((r) => asObj(r))
    .filter((o) => Object.keys(o).length > 0)
    .map((o) => ({ ...o } as SkillTraceStep));
}

/**
 * 把一条 StreamUpdate 归约到轮次状态。**幂等**：断线重连时先清空状态再逐条重放，
 * 所以这里不依赖任何「上次状态」，只做「追加/覆盖」语义。
 */
export function applyStreamUpdate(state: AssistantState, u: StreamUpdate): void {
  switch (u.kind) {
    case 'reasoning': {
      state.phase = 'reasoning';
      if (state.reasoningText.length === 0) state.reasoningText = u.text;
      else if (state.reasoningText !== u.text) state.reasoningText += '\n' + u.text;
      break;
    }
    case 'tool_call': {
      state.phase = 'tools';
      if (!state.tools.some((t) => t.id === u.callId)) {
        state.tools.push({ id: u.callId, name: u.name, status: 'running', resultPreview: '' });
      }
      break;
    }
    case 'tool_result': {
      state.phase = 'tools';
      const t = state.tools.find((x) => x.id === u.callId);
      if (t) {
        t.status = 'done';
        t.resultPreview = u.preview;
      } else {
        state.tools.push({ id: u.callId, name: 'tool', status: 'done', resultPreview: u.preview });
      }
      break;
    }
    case 'partial_answer': {
      state.phase = 'answering';
      state.answerText += u.text;
      break;
    }
    case 'final_answer': {
      state.phase = 'final';
      state.streaming = false;
      if (u.text) state.answerText = u.text;
      break;
    }
    case 'clarification': {
      state.phase = 'clarification';
      state.streaming = false;
      state.failed = false;
      if (u.request) state.clarification = u.request;
      if (u.text) state.answerText = state.answerText || u.text;
      break;
    }
    case 'skill_trace': {
      const map = new Map<string, SkillTraceStep>();
      for (const s of state.skillTrace) map.set(String(s.skill ?? s.step ?? JSON.stringify(s)), s);
      for (const s of u.steps) map.set(String(s.skill ?? s.step ?? JSON.stringify(s)), s);
      state.skillTrace = [...map.values()].sort((a, b) => (a.step ?? 0) - (b.step ?? 0));
      break;
    }
    case 'error': {
      const isCancel = u.message.includes('停止');
      state.phase = isCancel ? 'final' : 'error';
      state.failed = !isCancel;
      state.streaming = false;
      if (!state.answerText) state.answerText = u.message;
      break;
    }
    case 'title':
    case 'liveness':
    case 'ignore':
      break;
  }
}

export function newAssistant(): AssistantState {
  return emptyAssistant();
}
