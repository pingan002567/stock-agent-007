/** Reject session titles leaked from the prompt envelope / JSON wrappers. */
export function isUsableSessionTitle(title: string | null | undefined): boolean {
  if (typeof title !== "string") return false;
  const text = title.trim();
  if (!text) return false;
  if (text.startsWith("{") || text.startsWith("<")) return false;
  if (text.startsWith("[") && !scheduledTaskSessionTitle(text)) return false;
  const lowered = text.toLowerCase();
  if (lowered.includes("workbench_context")) return false;
  if (lowered.includes("envelope_version")) return false;
  if (lowered.startsWith("page:") && (lowered.includes("authority") || lowered.includes("symbol:"))) {
    return false;
  }
  return true;
}

export function scheduledTaskSessionTitle(title: string | null | undefined): string | null {
  if (typeof title !== "string") return null;
  const match = title.trim().match(/^\[定时任务·([^\s\]]+)\s+(\d{2}-\d{2})/);
  return match ? `${match[1]} ${match[2]}` : null;
}

export function displaySessionTitle(
  title: string | null | undefined,
  fallback = "新会话",
): string {
  const scheduled = scheduledTaskSessionTitle(title);
  if (scheduled) return scheduled;
  return isUsableSessionTitle(title) ? String(title).trim() : fallback;
}
