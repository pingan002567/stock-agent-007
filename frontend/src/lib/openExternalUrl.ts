/** 本机工作台地址：相对路径、回环、Tauri 自定义协议。其余 http(s)/mailto 走系统浏览器。 */

declare global {
  interface Window {
    __TAURI__?: {
      core?: { invoke?: (cmd: string, payload?: Record<string, unknown>) => Promise<unknown> };
    };
  }
}

export function isAppLocalHref(href: string, base: string = typeof window === "undefined" ? "http://127.0.0.1:8686/" : window.location.href): boolean {
  const raw = href.trim();
  if (!raw || raw.startsWith("#") || raw.startsWith("javascript:")) return true;
  try {
    const url = new URL(raw, base);
    if (url.protocol === "mailto:" || url.protocol === "tel:") return false;
    if (url.protocol === "tauri:") return true;
    const host = url.hostname;
    return host === "127.0.0.1" || host === "localhost" || host === "tauri.localhost";
  } catch {
    return true;
  }
}

export async function openExternalUrl(href: string, base?: string): Promise<void> {
  const url = new URL(href, base ?? (typeof window === "undefined" ? "http://127.0.0.1:8686/" : window.location.href)).toString();
  const invoke = typeof window === "undefined" ? undefined : window.__TAURI__?.core?.invoke;
  if (invoke) {
    await invoke("open_external", { url });
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

export function interceptAnchorClick(ev: MouseEvent): boolean {
  if (ev.defaultPrevented || (ev.button !== 0 && ev.button !== 1)) {
    return false;
  }
  const target = ev.target;
  if (!(target instanceof Element)) return false;
  const anchor = target.closest("a[href]");
  if (!(anchor instanceof HTMLAnchorElement)) return false;
  if (anchor.hasAttribute("download")) return false;
  const href = anchor.getAttribute("href") || "";
  if (isAppLocalHref(href)) return false;
  ev.preventDefault();
  ev.stopPropagation();
  void openExternalUrl(href);
  return true;
}
