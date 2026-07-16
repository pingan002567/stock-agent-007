"""StockAgent launchd 服务管理 CLI（桌面化阶段 1，doc/DESKTOP_APP_PLAN.md §2/§3.1）。

用法::

    python -m backend.service_cli doctor
    python -m backend.service_cli install [--port 6666] [--data-dir PATH]
    python -m backend.service_cli status
    python -m backend.service_cli restart
    python -m backend.service_cli uninstall
    python -m backend.service_cli reset [--delete-data]

设计要点（TeamClaw 平移，见计划文档 §3.1）：
- **doctor 单点判定**：所有环境探测集中在此输出 JSON，壳/引导 UI 只渲染 checklist；
- **动态端口**：请求端口被占自动向后顺延，结果写进 service.json 供壳读取；
- **服务状态目录固定**（``~/Library/Application Support/StockAgent``）、数据目录可选；
- **restart 用 kickstart -k**：原地重启顺带拾取升级后的代码，避开 bootout+bootstrap 竞态；
- **reset 是统一的卸载入口**（TeamClaw 的教训是卸载逻辑散落三处）。

所有命令输出单个 JSON 对象到 stdout，退出码 0=成功。仅支持 macOS（launchd）。
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from backend import paths

LABEL = "com.stockagent.backend"
# 桌面服务默认端口。不能用 6666：6665-6669 在 WebKit/Chromium 的受限端口名单
# （IRC 保留），WKWebView 对其 fetch/导航一律静默失败——实测踩坑，见
# doc/DESKTOP_APP_PLAN.md §2。浏览器开发流（8888 代理 6666）不受影响。
DEFAULT_PORT = 8686
# WebKit/Chromium 共同封锁的常见回环端口（节选自 fetch spec bad ports）
BLOCKED_PORTS = {6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080}
PORT_SCAN_RANGE = 50
HEALTH_TIMEOUT_SEC = 2.0
STARTUP_WAIT_ROUNDS = 24  # × 0.5s = 12s，对齐计划文档「轮询 12×500ms」


def _state_dir() -> Path:
    return paths.service_state_dir()


def _service_json_path() -> Path:
    return _state_dir() / "service.json"


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def _venv_python() -> Path:
    return paths.REPO_ROOT / ".venv" / "bin" / "python"


def read_service_config() -> dict[str, Any] | None:
    try:
        return json.loads(_service_json_path().read_text())
    except (OSError, ValueError):
        return None


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # SO_REUSEADDR 对齐 uvicorn 的绑定语义：旧进程退出后的 TIME_WAIT
        # 端口对新服务是可用的，探测不设此选项会误判占用导致端口顺延
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pick_port(requested: int) -> int:
    """请求端口可用则用之，否则向后顺延（§2 改造清单 2：端口被占不该让应用打不开）。
    跳过浏览器引擎封锁端口——webview 连不上等于服务白装。"""
    for port in range(requested, requested + PORT_SCAN_RANGE):
        if port not in BLOCKED_PORTS and _port_free(port):
            return port
    raise RuntimeError(f"no free port in [{requested}, {requested + PORT_SCAN_RANGE})")


def probe_health(port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=HEALTH_TIMEOUT_SEC
        ) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args], capture_output=True, text=True, timeout=30
    )


def _service_loaded() -> bool:
    return _launchctl("print", f"{_launchd_domain()}/{LABEL}").returncode == 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _service_pid() -> int | None:
    out = _launchctl("print", f"{_launchd_domain()}/{LABEL}").stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("pid = "):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def _read_env_file() -> dict[str, str]:
    """读仓库 .env（阶段 1 开发形态；阶段 2 密钥入库设置页后可移除）。"""
    env: dict[str, str] = {}
    env_file = paths.REPO_ROOT / ".env"
    if not env_file.is_file():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _service_environment(data_dir: Path) -> dict[str, str]:
    dotenv = _read_env_file()
    env = {
        "WORKBENCH_DATA_DIR": str(data_dir),
        # 与 start.sh load_env 对齐的 AI 默认值
        "WORKBENCH_AI_MODE": dotenv.get("WORKBENCH_AI_MODE", "direct"),
        "OPENAI_BASE_URL": dotenv.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
        "WORKBENCH_AI_MODEL": dotenv.get("WORKBENCH_AI_MODEL", "deepseek-chat"),
        "NO_PROXY": dotenv.get(
            "NO_PROXY", "eastmoney.com,push2.eastmoney.com,finance.sina.com.cn"
        ),
    }
    if dotenv.get("OPENAI_API_KEY"):
        env["OPENAI_API_KEY"] = dotenv["OPENAI_API_KEY"]
    return env


def validate_data_dir(raw: str | Path) -> Path:
    """数据目录校验在服务端做（§3.1.3）：拒绝根路径与服务状态目录内部。"""
    candidate = Path(raw).expanduser().resolve()
    if candidate == Path("/") or candidate == Path.home():
        raise ValueError(f"refusing dangerous data dir: {candidate}")
    state = _state_dir().resolve()
    if candidate == state or state in candidate.parents:
        # 允许固定推荐位 state/data，拒绝其余内部路径（防软链循环/误删服务状态）
        if candidate != paths.default_desktop_data_dir().resolve():
            raise ValueError(f"data dir must not live inside service state dir: {candidate}")
    return candidate


def _update_workspace_registry(data_dir: Path, port: int) -> None:
    """状态目录 workspaces.json：最近工作区注册表（vault 切换器的数据源）。
    去重后按 last_used 倒序，保留最近 10 条。"""
    from datetime import datetime, timezone

    registry_path = _state_dir() / "workspaces.json"
    try:
        items = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            items = []
    except (OSError, ValueError):
        items = []

    name = data_dir.name if data_dir.name != "data" else data_dir.parent.name
    try:
        meta = json.loads((data_dir / "workspace.json").read_text(encoding="utf-8"))
        name = str(meta.get("name") or name)
    except (OSError, ValueError):
        pass

    entry = {
        "dir": str(data_dir),
        "name": name,
        "port": port,
        "last_used": datetime.now(timezone.utc).isoformat(),
    }
    items = [entry] + [w for w in items if w.get("dir") != str(data_dir)]
    registry_path.write_text(
        json.dumps(items[:10], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_plist(port: int, data_dir: Path) -> Path:
    logs = _state_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            str(_venv_python()),
            "-m",
            "uvicorn",
            "backend.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            # 重启/切换场景 5 秒内强制断掉 in-flight 请求，避免旧进程占着端口
            # 等 AKShare 长任务收尾（实测会让切换后端口漂移）
            "--timeout-graceful-shutdown",
            "5",
        ],
        "WorkingDirectory": str(paths.REPO_ROOT),
        "EnvironmentVariables": _service_environment(data_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs / "backend.out.log"),
        "StandardErrorPath": str(logs / "backend.err.log"),
    }
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        plistlib.dump(plist, fh)
    return path


# ── commands ──


def cmd_doctor(_args: argparse.Namespace) -> dict[str, Any]:
    config = read_service_config()
    port = int(config["port"]) if config and config.get("port") else DEFAULT_PORT
    data_dir = Path(config["data_dir"]) if config and config.get("data_dir") else paths.default_desktop_data_dir()
    data_dir_writable = False
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        data_dir_writable = True
    except OSError:
        pass
    health = probe_health(port)
    return {
        "platform_ok": sys.platform == "darwin",
        "repo_root": str(paths.REPO_ROOT),
        "venv_python": str(_venv_python()),
        "venv_python_exists": _venv_python().is_file(),
        "frontend_dist_exists": paths.frontend_dist().is_dir(),
        "service_installed": _plist_path().is_file(),
        "service_loaded": _service_loaded(),
        "service_pid": _service_pid(),
        "port": port,
        "port_listening": _port_listening(port),
        "backend_healthy": health is not None,
        "backend_runtime": (health or {}).get("runtime"),
        "data_dir": str(data_dir),
        "data_dir_writable": data_dir_writable,
        "state_dir": str(_state_dir()),
    }


def cmd_install(args: argparse.Namespace) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise RuntimeError("launchd install is macOS-only")
    if not _venv_python().is_file():
        raise RuntimeError(f"venv python not found: {_venv_python()} (run ./install.sh first)")
    data_dir = validate_data_dir(args.data_dir or paths.default_desktop_data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)

    # 切换场景：旧档案也写入注册表，否则无法从切换器一键切回
    previous = read_service_config()
    if previous and previous.get("data_dir") and previous["data_dir"] != str(data_dir):
        try:
            _update_workspace_registry(Path(previous["data_dir"]), int(previous.get("port") or DEFAULT_PORT))
        except Exception:
            pass

    # 已在跑的旧服务先卸载再装。必须坚持等到请求端口真正释放：
    # 端口顺延会让停在旧端口的前端全线断连（实测踩坑）。
    if _service_loaded():
        old_pid = _service_pid()
        _launchctl("bootout", f"{_launchd_domain()}/{LABEL}")
        requested = args.port or DEFAULT_PORT
        deadline = time.time() + 20
        while time.time() < deadline:
            if _port_free(requested):
                break
            if old_pid and not _pid_alive(old_pid):
                break  # 旧进程已死但端口仍被占 = 第三方占用，交给 pick_port 顺延
            time.sleep(0.5)
        else:
            # 优雅期用尽仍不退（如卡在长任务的旧 uvicorn）：强杀兜底
            if old_pid and _pid_alive(old_pid):
                try:
                    os.kill(old_pid, 9)
                except OSError:
                    pass
                time.sleep(1.0)

    port = pick_port(args.port or DEFAULT_PORT)
    plist_path = _write_plist(port, data_dir)

    # 先写配置、后 bootstrap（§3.1.2：不装出没配置好的空服务）
    _state_dir().mkdir(parents=True, exist_ok=True)
    _service_json_path().write_text(json.dumps({
        "label": LABEL,
        "port": port,
        "data_dir": str(data_dir),
        "plist": str(plist_path),
        "repo_root": str(paths.REPO_ROOT),
    }, indent=2, ensure_ascii=False))
    _update_workspace_registry(data_dir, port)

    # bootout 后同 label 立即 bootstrap 会撞 launchd 竞态（I/O error，
    # 见 DESKTOP_APP_PLAN §3.1.4 对 kickstart 的取舍说明）——重试退避
    last_err = ""
    for attempt in range(6):
        result = _launchctl("bootstrap", _launchd_domain(), str(plist_path))
        if result.returncode == 0:
            break
        last_err = result.stderr.strip() or result.stdout.strip()
        time.sleep(1.0 + attempt * 0.5)
    else:
        raise RuntimeError(f"launchctl bootstrap failed after retries: {last_err}")

    healthy = False
    for _ in range(STARTUP_WAIT_ROUNDS):
        if probe_health(port):
            healthy = True
            break
        time.sleep(0.5)
    return {
        "installed": True,
        "port": port,
        "data_dir": str(data_dir),
        "plist": str(plist_path),
        "backend_healthy": healthy,
    }


def cmd_status(_args: argparse.Namespace) -> dict[str, Any]:
    config = read_service_config()
    port = int(config["port"]) if config and config.get("port") else DEFAULT_PORT
    health = probe_health(port)
    return {
        "service_installed": _plist_path().is_file(),
        "service_loaded": _service_loaded(),
        "service_pid": _service_pid(),
        "port": port,
        "backend_healthy": health is not None,
        "agent_runtime": (health or {}).get("agent_runtime", {}).get("active_client")
        if health else None,
    }


def cmd_restart(_args: argparse.Namespace) -> dict[str, Any]:
    result = _launchctl("kickstart", "-k", f"{_launchd_domain()}/{LABEL}")
    if result.returncode != 0:
        raise RuntimeError(f"launchctl kickstart failed: {result.stderr.strip()}")
    config = read_service_config()
    port = int(config["port"]) if config and config.get("port") else DEFAULT_PORT
    healthy = False
    for _ in range(STARTUP_WAIT_ROUNDS):
        if probe_health(port):
            healthy = True
            break
        time.sleep(0.5)
    return {"restarted": True, "port": port, "backend_healthy": healthy}


def cmd_uninstall(_args: argparse.Namespace) -> dict[str, Any]:
    was_loaded = _service_loaded()
    if was_loaded:
        _launchctl("bootout", f"{_launchd_domain()}/{LABEL}")
    plist_existed = _plist_path().is_file()
    _plist_path().unlink(missing_ok=True)
    return {"uninstalled": True, "was_loaded": was_loaded, "plist_removed": plist_existed}


def cmd_reset(args: argparse.Namespace) -> dict[str, Any]:
    out = cmd_uninstall(args)
    config = read_service_config()
    _service_json_path().unlink(missing_ok=True)
    data_deleted = False
    if args.delete_data and config and config.get("data_dir"):
        data_dir = Path(config["data_dir"])
        try:
            if data_dir.is_dir():
                validate_data_dir(data_dir)  # 危险路径直接抛错，宁可留下也不误删
                shutil.rmtree(data_dir)
                data_deleted = True
        except ValueError:
            pass
    out.update({"reset": True, "service_json_removed": True, "data_deleted": data_deleted})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stockagent-service", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p_install = sub.add_parser("install")
    p_install.add_argument("--port", type=int, default=None)
    p_install.add_argument("--data-dir", default=None)
    sub.add_parser("status")
    sub.add_parser("restart")
    sub.add_parser("uninstall")
    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--delete-data", action="store_true")

    args = parser.parse_args(argv)
    handlers = {
        "doctor": cmd_doctor,
        "install": cmd_install,
        "status": cmd_status,
        "restart": cmd_restart,
        "uninstall": cmd_uninstall,
        "reset": cmd_reset,
    }
    try:
        result = handlers[args.command](args)
    except Exception as exc:  # 单一 JSON 出口：壳只需解析 stdout
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
