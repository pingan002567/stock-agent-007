import { describe, expect, it, vi } from "vitest";
import { interceptAnchorClick, isAppLocalHref } from "@/lib/openExternalUrl";

describe("isAppLocalHref", () => {
  const base = "http://127.0.0.1:8686/app";

  it("keeps workbench and relative links in-app", () => {
    expect(isAppLocalHref("/api/reports/x/export?format=pdf", base)).toBe(true);
    expect(isAppLocalHref("#section", base)).toBe(true);
    expect(isAppLocalHref("http://127.0.0.1:8686/reports", base)).toBe(true);
    expect(isAppLocalHref("http://localhost:8686/", base)).toBe(true);
    expect(isAppLocalHref("tauri://localhost", base)).toBe(true);
  });

  it("sends news and mailto links outside", () => {
    expect(isAppLocalHref("https://www.jiemian.com/article/1.html", base)).toBe(false);
    expect(isAppLocalHref("http://finance.sina.com.cn/x", base)).toBe(false);
    expect(isAppLocalHref("mailto:a@b.com", base)).toBe(false);
  });
});

describe("interceptAnchorClick", () => {
  it("prevents in-webview navigation for external http links", () => {
    const a = document.createElement("a");
    a.href = "https://www.jiemian.com/article/1.html";
    a.textContent = "新闻";
    document.body.appendChild(a);
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    Object.defineProperty(ev, "target", { value: a });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    expect(interceptAnchorClick(ev)).toBe(true);
    expect(ev.defaultPrevented).toBe(true);
    expect(open).toHaveBeenCalled();
    open.mockRestore();
    a.remove();
  });

  it("leaves same-origin download links alone", () => {
    const a = document.createElement("a");
    a.href = "/api/reports/x/export?format=markdown";
    a.setAttribute("download", "");
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    Object.defineProperty(ev, "target", { value: a });
    expect(interceptAnchorClick(ev)).toBe(false);
    expect(ev.defaultPrevented).toBe(false);
  });
});
