import { useCallback, useEffect, useState } from "react";
import {
  canStartLocalBackend,
  canUseLocalMode,
  DEFAULT_LOCAL_PORT,
  invokeServiceCli,
  loadConnection,
  probeHealth,
  remoteUrlHint,
  resolveApiBase,
  saveConnection,
  shouldAutoConnect,
  type ConnectionMode,
  type ConnectionProfile,
  type ServiceDoctor,
} from "@/lib/connection";

const ENV_LABELS: Record<string, string> = {
  platform_ok: "请在 Mac 上打开此应用",
  venv_python_exists: "还没有装好运行环境，请先运行安装脚本 ./install.sh",
};

type GateView = "checking" | "pick" | "local-setup" | "local-repair" | "busy";

export function ConnectionGate({
  forceSelect = false,
  onConnected,
}: {
  forceSelect?: boolean;
  onConnected: () => void;
}) {
  const allowLocal = canUseLocalMode();
  const manageLocal = canStartLocalBackend();
  const [saved] = useState(() => loadConnection());
  const [view, setView] = useState<GateView>(
    forceSelect || !saved || !shouldAutoConnect() ? "pick" : "checking",
  );
  const [mode, setMode] = useState<ConnectionMode>(
    allowLocal ? (saved?.mode ?? "local") : "remote",
  );
  const [remoteUrl, setRemoteUrl] = useState(remoteUrlHint(saved));
  const [accessToken, setAccessToken] = useState(saved?.accessToken ?? "");
  const [chosenDir, setChosenDir] = useState("");
  const [envProblems, setEnvProblems] = useState<string[]>([]);
  const [repairLog, setRepairLog] = useState("");
  const [busyText, setBusyText] = useState("正在连接…");
  const [error, setError] = useState("");

  const finish = useCallback(
    (profile: ConnectionProfile) => {
      saveConnection(profile);
      onConnected();
    },
    [onConnected],
  );

  const enterLocal = useCallback(
    async (port: number) => {
      const profile: ConnectionProfile = {
        mode: "local",
        localPort: port,
        remoteUrl: saved?.remoteUrl,
        accessToken: saved?.accessToken,
      };
      const probed = await probeHealth(resolveApiBase(profile), 8000, profile.accessToken);
      if (!probed.ok) throw new Error(probed.error);
      finish(profile);
    },
    [finish, saved?.accessToken, saved?.remoteUrl],
  );

  const runLocalDesktop = useCallback(async () => {
    setError("");
    setBusyText("正在检查本机后端…");
    setView("busy");
    try {
      const d = await invokeServiceCli<ServiceDoctor>(["doctor"]);
      const port = d.port || DEFAULT_LOCAL_PORT;
      if (d.backend_healthy) {
        const probed = await probeHealth(`http://127.0.0.1:${port}`);
        if (probed.ok) {
          await enterLocal(port);
          return;
        }
        setRepairLog(`端口 ${port} 对应用不可达`);
        setView("local-repair");
        return;
      }
      if (!d.service_installed) {
        const problems = Object.keys(ENV_LABELS).filter((k) => d[k as keyof ServiceDoctor] === false);
        setEnvProblems(problems.map((k) => ENV_LABELS[k] || k));
        setChosenDir(d.data_dir || "");
        setView("local-setup");
        return;
      }
      setBusyText("服务未响应，正在重启…");
      const r = await invokeServiceCli<ServiceDoctor>(["restart"]);
      if (r.ok && r.backend_healthy && r.port) {
        await enterLocal(r.port);
        return;
      }
      setRepairLog((d.state_dir || "") + "/logs/backend.err.log");
      setView("local-repair");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setView("pick");
    }
  }, [enterLocal]);

  const runLocalBrowser = useCallback(async () => {
    setError("");
    setBusyText("正在连接本机后端…");
    setView("busy");
    try {
      await enterLocal(DEFAULT_LOCAL_PORT);
    } catch (err) {
      setError(
        (err instanceof Error ? err.message : String(err))
        + "。浏览器开发请先启动 make backend-dev。",
      );
      setView("pick");
    }
  }, [enterLocal]);

  const connectRemote = useCallback(async () => {
    setError("");
    setBusyText("正在测试远端连接…");
    setView("busy");
    try {
      const profile: ConnectionProfile = {
        mode: "remote",
        remoteUrl,
        localPort: saved?.localPort,
        accessToken,
      };
      const probed = await probeHealth(resolveApiBase(profile), 8000, accessToken);
      if (!probed.ok) throw new Error(probed.error);
      finish(profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setView("pick");
    }
  }, [accessToken, finish, remoteUrl, saved?.localPort]);

  useEffect(() => {
    if (forceSelect || !saved || !shouldAutoConnect()) return;
    let cancelled = false;
    void (async () => {
      try {
        const probed = await probeHealth(resolveApiBase(saved), 8000, saved.accessToken);
        if (cancelled) return;
        if (probed.ok) {
          onConnected();
          return;
        }
        setError(probed.error);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
      if (!cancelled) setView("pick");
    })();
    return () => { cancelled = true; };
    // 只在首屏用当时读到的 profile 探活
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forceSelect]);

  const browseDir = async () => {
    const dialogOpen = window.__TAURI__?.dialog?.open;
    if (!dialogOpen) return;
    try {
      const picked = await dialogOpen({ directory: true, defaultPath: chosenDir, title: "选择工作区文件夹" });
      if (picked) setChosenDir(picked);
    } catch (err) {
      setError(String(err));
    }
  };

  const installLocal = async () => {
    setError("");
    setBusyText("正在初始化本机后端…");
    setView("busy");
    try {
      const r = await invokeServiceCli<ServiceDoctor>(["install", "--data-dir", chosenDir]);
      const port = r.port || DEFAULT_LOCAL_PORT;
      if (r.ok && r.backend_healthy) {
        await enterLocal(port);
        return;
      }
      const probed = await probeHealth(`http://127.0.0.1:${port}`, 20000);
      if (probed.ok) {
        await enterLocal(port);
        return;
      }
      setError(r.error || "服务已注册但未响应，请重试");
      setView("local-setup");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setView("local-setup");
    }
  };

  const retryLocal = async () => {
    setError("");
    setBusyText("正在重启本机后端…");
    setView("busy");
    try {
      const r = await invokeServiceCli<ServiceDoctor>(["restart"]);
      if (r.ok && r.backend_healthy && r.port) {
        await enterLocal(r.port);
        return;
      }
      setError(r.error || "重启后仍未通过健康检查");
      setView("local-repair");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setView("local-repair");
    }
  };

  const resetLocal = async () => {
    setError("");
    try {
      await invokeServiceCli(["uninstall"]);
      const d = await invokeServiceCli<ServiceDoctor>(["doctor"]);
      setChosenDir(d.data_dir || "");
      setView("local-setup");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (view === "checking" || view === "busy") {
    return (
      <div className="setup-boot" role="status">
        <div className="conn-spinner" aria-hidden />
        <p>{view === "checking" ? "正在打开工作台…" : busyText}</p>
      </div>
    );
  }

  if (view === "local-setup") {
    return (
      <div className="setup-wizard">
        <div className="setup-wizard-card conn-card-wide">
          <h1 className="setup-title">欢迎使用 Stock Agent</h1>
          <p className="setup-lead">资料保存在这台电脑上。先选一个文件夹，会话、持仓和设置都会放在这里。</p>
          {envProblems.length > 0 ? (
            <div className="conn-env-err">{envProblems.map((line) => <div key={line}>· {line}</div>)}</div>
          ) : null}
          <div className="conn-dir-row">
            <div className="conn-dir-info">
              <div className="conn-dir-label">工作区</div>
              <div className="conn-dir-path">{chosenDir || "未选择"}</div>
            </div>
            {window.__TAURI__?.dialog?.open ? (
              <button type="button" className="ghost" onClick={() => void browseDir()}>更改…</button>
            ) : null}
          </div>
          {error ? <div className="setup-error">{error}</div> : null}
          <button type="button" className="primary setup-next" disabled={!chosenDir || envProblems.length > 0} onClick={() => void installLocal()}>
            开始使用
          </button>
          <button type="button" className="ghost setup-back" onClick={() => setView("pick")}>返回</button>
        </div>
      </div>
    );
  }

  if (view === "local-repair") {
    return (
      <div className="setup-wizard">
        <div className="setup-wizard-card">
          <h1 className="setup-title">服务未响应</h1>
          <p className="setup-lead">后台服务已注册但探活失败。{repairLog ? <>日志：<code>{repairLog}</code></> : null}</p>
          {error ? <div className="setup-error">{error}</div> : null}
          <button type="button" className="primary setup-next" onClick={() => void retryLocal()}>重启服务重试</button>
          <button type="button" className="ghost setup-back" onClick={() => void resetLocal()}>强制重置（重新注册服务）</button>
          <button type="button" className="ghost setup-back" onClick={() => setView("pick")}>改连其他后端</button>
        </div>
      </div>
    );
  }

  return (
    <div className="setup-wizard">
      <div className="setup-wizard-card conn-card-wide">
        <h1 className="setup-title">{allowLocal ? "选择后端" : "连接后端"}</h1>
        <p className="setup-lead">
          {allowLocal
            ? "界面在这台设备上运行。数据与模型请求发往你选择的后端。"
            : "填写你的服务地址和访问令牌。只有点连接后，App 才会访问后端。"}
        </p>

        <div className={`conn-modes${!allowLocal ? " single" : ""}`}>
          {allowLocal ? (
            <button
              type="button"
              className={`conn-mode${mode === "local" ? " on" : ""}`}
              onClick={() => setMode("local")}
            >
              <strong>这台电脑</strong>
              <span>启动或连接本机后端。工作区文件夹留在本地。</span>
            </button>
          ) : null}
          <button
            type="button"
            className={`conn-mode${mode === "remote" ? " on" : ""}`}
            onClick={() => setMode("remote")}
          >
            <strong>远端服务</strong>
            <span>连接已部署的后端。手机端只能用这种方式。</span>
          </button>
        </div>

        {mode === "remote" ? (
          <>
            <label className="setup-default">
              <span>后端地址</span>
              <input
                value={remoteUrl}
                onChange={(e) => setRemoteUrl(e.target.value)}
                placeholder="https://47.103.58.33"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            <p className="setup-lead" style={{ marginTop: 4, marginBottom: 0 }}>
              须用 <code>https://</code>（不要 http）。推荐{" "}
              <button
                type="button"
                className="linkish"
                onClick={() => setRemoteUrl("https://47.103.58.33")}
              >
                https://47.103.58.33
              </button>
              {" "}或{" "}
              <button
                type="button"
                className="linkish"
                onClick={() => setRemoteUrl("https://47.103.58.33:8686")}
              >
                :8686
              </button>
              。自签证书需在本机钥匙串信任：
              <a
                href="https://47.103.58.33:8686/ota/stock-agent.crt"
                target="_blank"
                rel="noreferrer"
              >
                下载证书
              </a>
              ，双击导入「系统」钥匙串后设为「始终信任」。
            </p>
            <label className="setup-default">
              <span>访问令牌</span>
              <input
                type="password"
                value={accessToken}
                onChange={(e) => setAccessToken(e.target.value)}
                placeholder="WORKBENCH_ACCESS_TOKEN"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
          </>
        ) : (
          <p className="setup-lead" style={{ marginTop: 8 }}>
            {manageLocal
              ? "将检查并按需启动本机后台服务。"
              : "将连接本机 8686 端口上已运行的后端（开发时请先 make backend-dev）。"}
          </p>
        )}

        {error ? <div className="setup-error">{error}</div> : null}
        <button
          type="button"
          className="primary setup-next"
          disabled={mode === "remote" && !remoteUrl.trim()}
          onClick={() => {
            if (mode === "remote") void connectRemote();
            else if (manageLocal) void runLocalDesktop();
            else void runLocalBrowser();
          }}
        >
          {mode === "remote" ? "连接" : "进入工作台"}
        </button>
      </div>
    </div>
  );
}
