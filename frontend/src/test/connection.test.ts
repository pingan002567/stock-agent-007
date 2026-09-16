import { afterEach, describe, expect, it, vi } from "vitest";
import { getApiBase } from "@/api/client";
import {
  CONNECTION_STORAGE_KEY,
  canStartLocalBackend,
  canUseLocalMode,
  isMobileLayout,
  formatConnectionLabel,
  remoteUrlHint,
  shouldAutoConnect,
  loadConnection,
  normalizeRemoteUrl,
  probeHealth,
  resolveApiBase,
  saveConnection,
} from "@/lib/connection";

afterEach(() => {
  localStorage.clear();
  window.__STOCKAGENT_FORCE_REMOTE__ = undefined;
  window.__TAURI__ = undefined;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("normalizeRemoteUrl", () => {
  it("requires http(s) and strips trailing slash", () => {
    expect(normalizeRemoteUrl("http://47.103.58.33:8686/")).toBe("https://47.103.58.33:8686");
    expect(normalizeRemoteUrl("https://example.com/api/")).toBe("https://example.com/api");
    expect(normalizeRemoteUrl("127.0.0.1:8686")).toBe("http://127.0.0.1:8686");
  });

  it("upgrades non-loopback http to https", () => {
    expect(normalizeRemoteUrl("http://10.0.0.2:8686")).toBe("https://10.0.0.2:8686");
  });

  it("rejects empty or non-http schemes", () => {
    expect(() => normalizeRemoteUrl("")).toThrow("请填写远端地址");
    expect(() => normalizeRemoteUrl("ftp://x")).toThrow("只支持 http 或 https 地址");
    expect(() => normalizeRemoteUrl("not a url")).toThrow("地址格式不正确");
  });
});

describe("resolveApiBase", () => {
  it("uses loopback for local mode", () => {
    expect(resolveApiBase({ mode: "local" })).toBe("http://127.0.0.1:8686");
    expect(resolveApiBase({ mode: "local", localPort: 9000 })).toBe("http://127.0.0.1:9000");
  });

  it("uses remote URL for remote mode", () => {
    expect(resolveApiBase({ mode: "remote", remoteUrl: "http://10.0.0.2:8686/" })).toBe(
      "https://10.0.0.2:8686",
    );
    expect(() => resolveApiBase({ mode: "remote" })).toThrow("未配置远端地址");
  });
});

describe("connection persistence", () => {
  it("round-trips a remote profile", () => {
    saveConnection({ mode: "remote", remoteUrl: "http://example.com:8686/", accessToken: "tok" });
    expect(loadConnection()).toEqual({
      mode: "remote",
      remoteUrl: "https://example.com:8686",
      localPort: undefined,
      accessToken: "tok",
    });
    expect(JSON.parse(localStorage.getItem(CONNECTION_STORAGE_KEY) || "{}").mode).toBe("remote");
    expect(getApiBase()).toBe("https://example.com:8686");
  });
});

describe("formatConnectionLabel", () => {
  it("labels local and remote hosts", () => {
    expect(formatConnectionLabel({ mode: "local", localPort: 8686 })).toBe("本地 · 8686");
    expect(formatConnectionLabel({ mode: "remote", remoteUrl: "http://47.1.2.3:8686" })).toBe(
      "远端 · 47.1.2.3:8686",
    );
  });
});

describe("local mode availability", () => {
  it("hides local mode when the shell forces remote", () => {
    expect(canUseLocalMode()).toBe(true);
    window.__STOCKAGENT_FORCE_REMOTE__ = true;
    expect(canUseLocalMode()).toBe(false);
  });

  it("only starts a local backend when Tauri service_cli is present", () => {
    expect(canStartLocalBackend()).toBe(false);
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    expect(canStartLocalBackend()).toBe(true);
  });

  it("does not fall back to loopback when the shell forces remote", () => {
    window.__STOCKAGENT_FORCE_REMOTE__ = true;
    expect(getApiBase()).toBe("");
  });

  it("does not auto-connect or prefill a host on mobile", () => {
    expect(shouldAutoConnect()).toBe(true);
    window.__STOCKAGENT_FORCE_REMOTE__ = true;
    expect(shouldAutoConnect()).toBe(false);
    expect(remoteUrlHint(null)).toBe("");
  });

  it("uses the Cursor-style mobile shell on native or narrow viewports", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("720px"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    expect(isMobileLayout()).toBe(true);
    window.__STOCKAGENT_FORCE_REMOTE__ = true;
    expect(isMobileLayout()).toBe(true);
  });
});

describe("probeHealth", () => {
  it("accepts a workbench health payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", server_role: "workbench", agent_runtime: { active_client: "direct" } }),
      }),
    );
    const r = await probeHealth("http://47.103.58.33:8686/");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.data.server_role).toBe("workbench");
    expect(fetch).toHaveBeenCalledWith(
      "https://47.103.58.33:8686/api/health",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("returns a clear error for invalid URLs and failed probes", async () => {
    expect((await probeHealth("ftp://x")).ok).toBe(false);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const r = await probeHealth("http://127.0.0.1:8686");
    expect(r).toEqual({ ok: false, error: "无法连上后端，请确认服务已启动、地址正确，且本机能访问该主机" });
  });

  it("treats health without agent_runtime as missing token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", server_role: "workbench" }),
      }),
    );
    expect(await probeHealth("http://example.com")).toEqual({
      ok: false,
      error: "需要访问令牌",
    });
  });
});
