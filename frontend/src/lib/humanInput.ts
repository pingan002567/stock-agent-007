/** DeerFlow-native human_input protocol (align with upstream Human Input Card). */

export type HumanInputMode = "free_text" | "single_choice" | "choice_with_other" | "form";

export type HumanInputOption = {
  id: string;
  label: string;
  value: string;
};

export type HumanInputFieldType =
  | "text"
  | "textarea"
  | "number"
  | "select"
  | "multi_select"
  | "checkbox"
  | "date";

export type HumanInputField = {
  name: string;
  label: string;
  type: HumanInputFieldType;
  required: boolean;
  placeholder?: string;
  options?: HumanInputOption[];
};

export type HumanInputRequest = {
  version: 1 | 2;
  kind: "human_input_request";
  source: string;
  request_id: string;
  tool_call_id?: string;
  clarification_type?: string;
  title?: string;
  question: string;
  context?: string | null;
  input_mode: HumanInputMode;
  options?: HumanInputOption[];
  fields?: HumanInputField[];
  call_id?: string;
};

export type HumanInputResponse =
  | {
      version: 1;
      kind: "human_input_response";
      source: string;
      request_id: string;
      response_kind: "option";
      option_id: string;
      value: string;
    }
  | {
      version: 1;
      kind: "human_input_response";
      source: string;
      request_id: string;
      response_kind: "text";
      value: string;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function parseOptions(value: unknown): HumanInputOption[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return undefined;
  const options: HumanInputOption[] = [];
  const seen = new Set<string>();
  for (const [idx, item] of value.entries()) {
    if (typeof item === "string" && item.trim()) {
      const id = `opt-${idx + 1}`;
      options.push({ id, label: item.trim(), value: item.trim() });
      continue;
    }
    if (!isRecord(item)) return undefined;
    const id = nonEmpty(item.id) ? item.id : `opt-${idx + 1}`;
    const label = nonEmpty(item.label) ? item.label : nonEmpty(item.value) ? item.value : null;
    const optionValue = nonEmpty(item.value) ? item.value : label;
    if (!label || !optionValue || seen.has(id)) return undefined;
    seen.add(id);
    options.push({ id, label, value: optionValue });
  }
  return options;
}

/** Harness often embeds "1. … / 2. …" inside question markdown — lift them into options. */
export function extractOptionsFromMarkdown(text: string): HumanInputOption[] {
  const options: HumanInputOption[] = [];
  const seen = new Set<string>();
  const re = /^\s*(?:\d+[\.\、\)]\s+|[-*]\s+)(.+?)\s*$/gm;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = re.exec(text)) !== null) {
    const label = match[1].trim();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    idx += 1;
    options.push({ id: `opt-${idx}`, label, value: label });
  }
  return options;
}

export function splitClarificationMarkdown(text: string): {
  context: string | null;
  question: string;
  options: HumanInputOption[];
} {
  const raw = text.trim();
  if (!raw) {
    return { context: null, question: "需要你补充一些信息才能继续", options: [] };
  }
  const options = extractOptionsFromMarkdown(raw);
  let body = raw;
  if (options.length) {
    const lines = raw.split(/\r?\n/);
    const kept: string[] = [];
    for (const line of lines) {
      if (/^\s*(?:\d+[\.\、\)]\s+|[-*]\s+)/.test(line)) break;
      kept.push(line);
    }
    body = kept.join("\n").trim();
  }
  body = body.replace(/^[🧩❓ℹ️]\s*/, "").trim();
  let context: string | null = null;
  let question = body || raw;
  const qMatch = body.match(/第\s*\d+\s*个问题[:：]\s*/);
  if (qMatch && qMatch.index !== undefined) {
    const before = body.slice(0, qMatch.index).trim();
    const after = body.slice(qMatch.index + qMatch[0].length).trim();
    if (before) context = before;
    if (after) question = after;
  } else {
    const parts = body.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
    if (parts.length >= 2) {
      context = parts[0];
      question = parts.slice(1).join("\n\n");
    }
  }
  question = question.replace(/^第\s*\d+\s*个问题[:：]\s*/, "").trim() || question;
  return { context, question, options };
}

function parseFields(value: unknown): HumanInputField[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return undefined;
  const fields: HumanInputField[] = [];
  const seen = new Set<string>();
  for (const field of value) {
    if (!isRecord(field) || !nonEmpty(field.name) || seen.has(field.name)) return undefined;
    seen.add(field.name);
    const label = nonEmpty(field.label) ? field.label : field.name;
    const type = (nonEmpty(field.type) ? field.type : "text") as HumanInputFieldType;
    const options = parseOptions(field.options);
    if (field.options !== undefined && options === undefined) return undefined;
    fields.push({
      name: field.name,
      label,
      type,
      required: field.required === true,
      ...(nonEmpty(field.placeholder) ? { placeholder: field.placeholder } : {}),
      ...(options ? { options } : {}),
    });
  }
  return fields;
}

export function parseHumanInputRequest(value: unknown): HumanInputRequest | null {
  if (!isRecord(value)) return null;
  let question = nonEmpty(value.question) ? value.question.trim() : null;
  if (!question) return null;

  const callId = nonEmpty(value.tool_call_id)
    ? value.tool_call_id
    : nonEmpty(value.call_id)
      ? value.call_id
      : undefined;
  const requestId = nonEmpty(value.request_id)
    ? value.request_id
    : callId
      ? `clarification:${callId}`
      : `clarification:${question.slice(0, 24)}`;

  let inputMode = value.input_mode;
  let options = parseOptions(value.options);
  let context = value.context;
  // Legacy / harness markdown blobs: lift numbered options out of the question body.
  if ((!options || options.length === 0) && (/\n\s*\d+[\.\、\)]/.test(question) || /第\s*\d+\s*个问题/.test(question))) {
    const split = splitClarificationMarkdown(question);
    question = split.question;
    options = split.options.length ? split.options : options;
    if ((context === undefined || context === null || context === "") && split.context) {
      context = split.context;
    }
  }
  const fields = parseFields(value.fields);
  if (inputMode !== "free_text" && inputMode !== "single_choice" && inputMode !== "choice_with_other" && inputMode !== "form") {
    inputMode = fields && fields.length > 0
      ? "form"
      : options && options.length > 0
        ? "choice_with_other"
        : "free_text";
  }
  if (
    (inputMode === "single_choice" || inputMode === "choice_with_other")
    && (!options || options.length === 0)
  ) {
    inputMode = "free_text";
  }
  if (inputMode === "form" && (!fields || fields.length === 0)) {
    inputMode = options && options.length > 0 ? "choice_with_other" : "free_text";
  }

  return {
    version: value.version === 2 || inputMode === "form" ? 2 : 1,
    kind: "human_input_request",
    source: nonEmpty(value.source) ? value.source : "ask_clarification",
    request_id: requestId,
    ...(callId ? { tool_call_id: callId, call_id: callId } : {}),
    ...(nonEmpty(value.clarification_type) ? { clarification_type: value.clarification_type } : {}),
    ...(nonEmpty(value.title) ? { title: value.title } : {}),
    question,
    ...(context === undefined || context === null || typeof context === "string"
      ? { context: typeof context === "string" ? context : null }
      : {}),
    input_mode: inputMode as HumanInputMode,
    ...(options && options.length ? { options } : {}),
    ...(fields ? { fields } : {}),
  };
}

export function createHumanInputOptionResponse(
  request: HumanInputRequest,
  option: HumanInputOption,
): HumanInputResponse {
  return {
    version: 1,
    kind: "human_input_response",
    source: request.source,
    request_id: request.request_id,
    response_kind: "option",
    option_id: option.id,
    value: option.value,
  };
}

export function buildHumanInputFormSummary(
  request: HumanInputRequest,
  values: Record<string, string | boolean | string[]>,
): string {
  const parts: string[] = [];
  for (const field of request.fields ?? []) {
    const value = values[field.name];
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) continue;
    const formatted = Array.isArray(value) ? value.join(", ") : typeof value === "boolean" ? (value ? "yes" : "no") : String(value);
    parts.push(`${field.label}: ${formatted}`);
  }
  return parts.join("; ");
}

export function buildHumanInputFormSubmissionValue(
  request: HumanInputRequest,
  values: Record<string, string | boolean | string[]>,
): string {
  const record: Record<string, string | boolean | string[]> = {};
  for (const field of request.fields ?? []) {
    const value = values[field.name];
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) continue;
    record[field.name] = value;
  }
  return `${buildHumanInputFormSummary(request, values)} [values: ${JSON.stringify(record)}]`;
}

export function createHumanInputTextResponse(
  request: HumanInputRequest,
  value: string,
): HumanInputResponse {
  return {
    version: 1,
    kind: "human_input_response",
    source: request.source,
    request_id: request.request_id,
    response_kind: "text",
    value: value.trim(),
  };
}

export function buildHumanInputResponseText(request: HumanInputRequest, value: string): string {
  return `For your clarification "${request.question}", my answer is: ${value.trim()}`;
}

export function parseHumanInputResponse(value: unknown): HumanInputResponse | null {
  if (!isRecord(value)) return null;
  if (value.version !== 1 || value.kind !== "human_input_response") return null;
  if (!nonEmpty(value.source) || !nonEmpty(value.request_id) || !nonEmpty(value.value)) return null;
  if (value.response_kind === "option") {
    if (!nonEmpty(value.option_id)) return null;
    return {
      version: 1,
      kind: "human_input_response",
      source: value.source,
      request_id: value.request_id,
      response_kind: "option",
      option_id: value.option_id,
      value: value.value,
    };
  }
  if (value.response_kind === "text") {
    return {
      version: 1,
      kind: "human_input_response",
      source: value.source,
      request_id: value.request_id,
      response_kind: "text",
      value: value.value,
    };
  }
  return null;
}
