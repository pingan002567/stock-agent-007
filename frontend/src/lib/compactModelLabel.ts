/** Composer 模型 pill 用的短标签（下拉仍用完整 label）。 */
const PROVIDER_TAGS: Record<string, string> = {
  deepseek: "DS",
  kimi: "Kimi",
  qwen: "Qwen",
  zhipu: "GLM",
  mimo: "MiMo",
  openai: "GPT",
  siliconflow: "SF",
  openrouter: "OR",
  ollama: "Ollama",
};

const MODEL_PREFIX_RE = /^(deepseek-?|kimi-?|glm-?|mimo-?|qwen-?|gpt-?|moonshot-?)/i;
const BRAND_PREFIX_RE = /^(DeepSeek|Kimi|Qwen|GLM|MiMo|GPT|OpenAI|Moonshot|SiliconFlow)\s*/i;

function providerTag(providerId: string, providerName?: string): string {
  return PROVIDER_TAGS[providerId] ?? (providerName?.split(/\s+/)[0] ?? providerId);
}

function modelTag(modelId: string, modelName?: string): string {
  if (modelName) {
    const trimmed = modelName.replace(BRAND_PREFIX_RE, "").trim();
    if (trimmed) return trimmed;
  }
  const fromId = modelId.replace(MODEL_PREFIX_RE, "");
  return fromId || modelId;
}

export function compactModelLabelFromRef(
  ref: string | null,
  fullLabel?: string,
): string {
  if (!ref) return "AI";
  if (!ref.includes("/")) return ref;
  const [providerId, modelId] = ref.split("/", 2);
  let providerName: string | undefined;
  let modelName: string | undefined;
  if (fullLabel?.includes(" · ")) {
    [providerName, modelName] = fullLabel.split(" · ", 2);
  }
  return `${providerTag(providerId, providerName)} · ${modelTag(modelId, modelName)}`;
}
