/** 与 backend/agent_runtime/deerflow_config.py `_VISION_MODEL_HINTS` 对齐。 */
export const VISION_MODEL_HINTS = [
  "gpt-4o",
  "gpt-4.1",
  "gpt-5",
  "o3",
  "o4",
  "claude",
  "gemini",
  "qwen-vl",
  "qwen2-vl",
  "qvq",
  "glm-4v",
  "vision",
] as const;

export const IMAGE_UPLOAD_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp"]);

export const UPLOADS_UNSUPPORTED_COPY = "当前 AI 运行时不支持读附件";

export function modelSupportsVision(modelRef: string | null | undefined): boolean {
  const name = (modelRef ?? "").toLowerCase();
  if (!name) return false;
  return VISION_MODEL_HINTS.some((hint) => name.includes(hint));
}

export function isImageUploadFilename(filename: string): boolean {
  const dot = filename.lastIndexOf(".");
  if (dot < 0) return false;
  return IMAGE_UPLOAD_EXTENSIONS.has(filename.slice(dot).toLowerCase());
}

export function attachmentsFromMessagePayload(
  payload: Record<string, unknown> | null | undefined,
): Array<{ filename: string; size: number; markdown_file?: string | null }> {
  const raw = payload?.attachments;
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: Array<{ filename: string; size: number; markdown_file?: string | null }> = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const filename = String((item as { filename?: unknown }).filename || "");
    if (!filename || seen.has(filename)) continue;
    seen.add(filename);
    const markdown = (item as { markdown_file?: unknown }).markdown_file;
    out.push({
      filename,
      size: Number((item as { size?: unknown }).size || 0),
      markdown_file: typeof markdown === "string" ? markdown : null,
    });
  }
  return out;
}
