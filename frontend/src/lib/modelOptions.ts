import type { LlmModelRow } from "@/api/llmProviders";

/** 「默认模型」下拉的候选项合并：
 *
 *  - **实时拉取**到的模型优先（厂商此刻真的在售）
 *  - 内置目录兜底（拉取失败 / 没点拉取时）
 *  - 当前已选中的模型即使不在名单里也保留，否则下拉框会把选择"吞掉"
 *
 * 纯函数，便于测试：`lint` 也不允许组件文件导出非组件。
 */
export interface ModelOption {
  value: string;
  label: string;
  source: "live" | "catalog" | "current";
}

export function mergeModelOptions(params: {
  connected: { id: string; name: string; models: LlmModelRow[] }[];
  live: Record<string, LlmModelRow[] | undefined>;
  current?: string;
}): ModelOption[] {
  const { connected, live, current } = params;
  const out: ModelOption[] = [];
  const seen = new Set<string>();

  const push = (providerId: string, providerName: string, model: LlmModelRow, source: ModelOption["source"]) => {
    const value = `${providerId}/${model.id}`;
    if (seen.has(value) || value === current) return;
    seen.add(value);
    out.push({ value, label: `${providerName} · ${model.name || model.id}`, source });
  };

  // 当前选中的排最前，避免被实时/目录列表挤到不可见位置
  if (current) {
    const [pid, ...rest] = current.split("/");
    const modelId = rest.join("/");
    const provider = connected.find((p) => p.id === pid);
    if (provider && modelId) {
      out.push({ value: current, label: `${provider.name} · ${modelId}（当前）`, source: "current" });
      seen.add(current);
    }
  }

  for (const provider of connected) {
    for (const model of live[provider.id] ?? []) push(provider.id, provider.name, model, "live");
    for (const model of provider.models) push(provider.id, provider.name, model, "catalog");
  }
  return out;
}

/** 每个提供商可用的模型数：实时优先，没有实时就用目录数 */
export function modelCounts(params: {
  connected: { id: string; models: LlmModelRow[] }[];
  live: Record<string, LlmModelRow[] | undefined>;
}): Record<string, { count: number; source: "live" | "catalog" }> {
  const out: Record<string, { count: number; source: "live" | "catalog" }> = {};
  for (const provider of params.connected) {
    const liveModels = params.live[provider.id];
    out[provider.id] = liveModels?.length
      ? { count: liveModels.length, source: "live" }
      : { count: provider.models.length, source: "catalog" };
  }
  return out;
}
