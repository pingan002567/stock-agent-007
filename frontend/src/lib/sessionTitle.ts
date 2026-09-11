/** Reject session titles leaked from the prompt envelope / JSON wrappers. */
export function isUsableSessionTitle(title: string | null | undefined): boolean {
  if (typeof title !== "string") return false;
  const text = title.trim();
  if (!text) return false;
  if (text.startsWith("{") || text.startsWith("[") || text.startsWith("<")) return false;
  const lowered = text.toLowerCase();
  if (lowered.includes("workbench_context")) return false;
  if (lowered.includes("envelope_version")) return false;
  if (lowered.startsWith("page:") && (lowered.includes("authority") || lowered.includes("symbol:"))) {
    return false;
  }
  return true;
}

export function displaySessionTitle(
  title: string | null | undefined,
  fallback = "新会话",
): string {
  return isUsableSessionTitle(title) ? String(title).trim() : fallback;
}
