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

