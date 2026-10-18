/**
 * Format a timestamp as relative time ago (e.g., "2分钟前", "1小时前", "昨天 14:32")
 */
export function formatTimeAgo(dateStr?: string): string {
  if (!dateStr) return "";
  
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) return "刚刚";
  if (diffMinutes < 60) return `${diffMinutes}分钟前`;
  if (diffHours < 24) return `${diffHours}小时前`;
  if (diffDays === 1) return `昨天 ${date.getHours().toString().padStart(2, "0")}:${date.getMinutes().toString().padStart(2, "0")}`;
  if (diffDays < 7) return `${diffDays}天前`;
  
  // Format as MM-DD HH:mm
  const month = (date.getMonth() + 1).toString().padStart(2, "0");
  const day = date.getDate().toString().padStart(2, "0");
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

/**
 * Format a timestamp as short time (e.g., "14:32")
 */
export function formatShortTime(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  return `${date.getHours().toString().padStart(2, "0")}:${date.getMinutes().toString().padStart(2, "0")}`;
}

/**
 * Format a timestamp as date (e.g., "2024-06-07")
 */
export function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  return dateStr.slice(0, 10);
}

/** UTC ISO 串 → 本地 HH:MM:SS(消息气泡用;裸 slice 会显示 UTC 时刻) */
export function formatLocalTime(dateStr?: string): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "";
  const p2 = (n: number) => String(n).padStart(2, "0");
  return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
}

/** 纯文本位置去掉 Markdown 强调标记。
 *  简报结论等只有一两行的字段走的是纯文本渲染（不是 Markdown 组件），
 *  正文里的 ** 会原样漏出来。 */
export function stripInlineMarkdown(input?: string | null): string {
  if (!input) return "";
  return input
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*([^*\n]+)\*/g, "$1")
    // 后端存的摘要可能被截断，只剩半对 ** （如「…收盘）**」），成对正则删不掉
    .replace(/\*{1,2}(?=\s|$)/g, "")
    .replace(/\*\*/g, "")
    .trim();
}
