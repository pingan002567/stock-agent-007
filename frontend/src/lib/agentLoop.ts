import type { StreamStep, StreamToolCall } from "@/hooks/useCopilotChat";

/** Agent loop 的纯函数部分（统计 / exit code 解析）。
 *
 *  放在 lib 里而不是组件文件里：组件文件只导出组件，
 *  否则 React Fast Refresh 会失效（lint 会报 only-export-components）。
 */

export interface LoopStats {
  reasoning: number;
  tools: number;
  commands: number;
  rounds: number;
}

/** 统计一轮 loop：命令单独计数（它不是 API 工具）；轮次取最大值 */
export function loopStats(steps: StreamStep[]): LoopStats {
  let reasoning = 0;
  let tools = 0;
  let commands = 0;
  let rounds = 0;
  for (const step of steps) {
    if (step.kind === "reasoning") {
      reasoning += 1;
      continue;
    }
    if (step.tool.kind === "command") commands += 1;
    else tools += 1;
    rounds = Math.max(rounds, step.tool.round ?? 0);
  }
  return { reasoning, tools, commands, rounds };
}

/** 从结果里认 exit code：JSON 字段优先，其次文本里的 "exit code N" */
export function exitCodeOf(tool: StreamToolCall): number | null {
  const raw = tool.resultText;
  if (!raw) return null;
  const head = raw.trimStart();
  if (head.startsWith("{")) {
    try {
      const parsed = JSON.parse(head) as Record<string, unknown>;
      for (const key of ["exit_code", "exitCode", "returncode", "code"]) {
        const v = parsed[key];
        if (typeof v === "number" && Number.isInteger(v)) return v;
      }
    } catch { /* 非严格 JSON，走下面的文本匹配 */ }
  }
  const m = raw.match(/exit(?:\s+code)?[:\s]+(-?\d+)/i);
  return m ? Number(m[1]) : null;
}

/** 命令输出：工具桥常把结果包成 {stdout, stderr, exit_code}，终端块只显示 stdout/stderr */
export function commandOutputOf(tool: StreamToolCall): string {
  const raw = (tool.resultText ?? "").replace(/\s+$/, "");
  if (!raw) return "";
  if (!raw.trimStart().startsWith("{")) return raw;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const parts = [parsed.stdout, parsed.stderr]
      .filter((v): v is string => typeof v === "string" && v.trim() !== "");
    if (parts.length) return parts.join("\n").replace(/\s+$/, "");
  } catch { /* 不是严格 JSON 就原样显示 */ }
  return raw;
}


/** 思考步落位：让每个思考块紧贴它所驱动的**第一张**工具卡之前。
 *
 *  背景：后端把思维链挂在「带 tool_calls 的分片」上，所以 `reasoning` 事件总是晚于
 *  `tool_call` 到达（实测序列：CALL, CALL, REASON, RESULT, RESULT）。如果按到达顺序
 *  追加，一段「打算先取数」的计划就会显示在结果之后，把因果讲反。
 *
 *  判据是尾部的**工具组**（连续的工具步）：
 *  - 组里还有工具没返回结果（status === "running"）→ 这是「计划型思考」，插到组首；
 *    这类思考**一定**早于它自己的 tool_result 到达，所以「没返回结果」足以识别，
 *    不需要猜。
 *  - 组里全部已返回 → 这是「结果后的复盘」，追加在后面（唯一该在后面的情况）。
 *  - 尾部不是工具（思考/空）→ 追加，交给上面的合并逻辑。
 *
 *  ⚠️ 只前插**组内位置**，不改工具之间的相对顺序，也不改轮次编号。
 */
export function placeReasoningStep<T extends StreamStep>(steps: T[], step: T): T[] {
  // 找尾部的连续工具组
  let start = steps.length;
  while (start > 0 && steps[start - 1].kind === "tool") start -= 1;

  if (start === steps.length) return [...steps, step];

  const pending = steps.slice(start).some((s) => s.kind === "tool" && s.tool.status === "running");
  if (!pending) return [...steps, step];

  // 组里还有工具在跑 → 这段思考是发起调用前的判断，插到组首
  return [...steps.slice(0, start), step, ...steps.slice(start)];
}
