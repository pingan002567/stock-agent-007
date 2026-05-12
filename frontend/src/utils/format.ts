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
