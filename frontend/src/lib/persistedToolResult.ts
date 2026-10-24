/** 历史消息里 tool_result 的可读文本。
 *
 *  流式事件带完整 result；落库消息只留 `{tool, call_id, result_preview}`，
 *  其中 `result_preview` 可能是：
 *    - `{value: "<json 字符串>"}`（工具返回字符串时的包装，最常见）
 *    - 白名单字段对象（`{status, summary, ...}`）
 *    - `{status: "needs_confirmation", reason, next_action}`
 *  直接 JSON.stringify 整个 payload 会把包装也显示出来（用户看到的就是
 *  `{"tool":"get_daily_history","execution_mode":null,...}` 这种噪声）。
 */
export function persistedToolResultText(payload?: Record<string, unknown>): string | undefined {
  if (!payload) return undefined;
  const preview = payload.result_preview;
  if (preview && typeof preview === "object" && !Array.isArray(preview)) {
    const obj = preview as Record<string, unknown>;
    const value = obj.value;
    if (typeof value === "string") return prettyMaybeJson(value);
    if (value !== undefined) return prettyMaybeJson(JSON.stringify(value));
    if (Object.keys(obj).length) return prettyMaybeJson(JSON.stringify(obj));
    return undefined;
  }
  if (typeof preview === "string") return prettyMaybeJson(preview);
  // 没有 preview（老数据 / 其它工具）：退回通用提取
  const direct = payload.text ?? payload.output ?? payload.result;
  if (direct !== undefined && direct !== null && direct !== "") {
    return typeof direct === "string" ? direct : prettyMaybeJson(JSON.stringify(direct));
  }
  return undefined;
}

/** JSON 字符串 → 缩进后的文本；不是 JSON 就原样返回 */
export function prettyMaybeJson(raw: string): string {
  const text = raw.trim();
  if (!(text.startsWith("{") || text.startsWith("["))) return raw;
  try {
    return JSON.stringify(JSON.parse(text), null, 1);
  } catch {
    return raw;
  }
}
