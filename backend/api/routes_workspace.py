"""工作区（用户档案）API：当前档案信息 + vault 式切换（方案 A）。

切换 = 分离子进程跑 ``service_cli install --data-dir <新目录>``（会 bootout 当前
服务→重写 plist→bootstrap 新目录），本进程随之被 launchd 终止；前端收到响应后
轮询 /api/health 等新档案上线再整页刷新。

开发态（``make dev-stack`` / ``scripts/stack.sh`` 直连 uvicorn）优先走 Tauri ``service_cli install`` 桥；
HTTP ``/switch`` 在无 launchd 时也会 spawn install，但 ``make dev-stack`` 重启会覆盖——
见 ``scripts/stack.sh`` 对 launchd 后端的复用逻辑。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend import paths
from backend import service_cli

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _resolved_dir(raw: str | Path) -> Path:
    return service_cli.validate_data_dir(raw)


def _workspace_name(data_dir: Path) -> str:
    try:
        meta = json.loads((data_dir / "workspace.json").read_text(encoding="utf-8"))
        if meta.get("name"):
            return str(meta["name"])
    except (OSError, ValueError):
        pass
    return data_dir.name if data_dir.name != "data" else data_dir.parent.name


def _registry() -> list[dict]:
    try:
        items = json.loads(
            (paths.service_state_dir() / "workspaces.json").read_text(encoding="utf-8")
        )
        if not isinstance(items, list):
            items = []
    except (OSError, ValueError):
        items = []
    valid: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_dir = str(item.get("dir") or "").strip()
        if not raw_dir:
            continue
        try:
            service_cli.validate_data_dir(raw_dir)
        except ValueError:
            continue
        valid.append(item)
    return valid


@router.get("")
def workspace_info():
    data_dir = paths.data_dir().resolve()
    current = str(data_dir)
    config = service_cli.read_service_config()
    loaded = service_cli.service_loaded()
    recents = [w for w in _registry() if w.get("dir") and w["dir"] != current]
    configured_dir = str(Path(config["data_dir"]).resolve()) if config and config.get("data_dir") else None
    return {
        "name": _workspace_name(data_dir),
        "data_dir": current,
        "port": (config or {}).get("port"),
        "switchable": loaded or config is not None,
        "service_mode": "launchd" if loaded else "dev",
        "service_loaded": loaded,
        "configured_data_dir": configured_dir,
        "recents": recents,
    }


@router.post("/resolve")
def workspace_resolve(payload: dict):
    raw = str(payload.get("data_dir") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="data_dir is required")
    try:
        target = _resolved_dir(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data_dir": str(target)}


@router.post("/switch")
def workspace_switch(payload: dict):
    raw = str(payload.get("data_dir") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="data_dir is required")

    config = service_cli.read_service_config()
    if config is None:
        raise HTTPException(
            status_code=409,
            detail="尚未注册 launchd 服务；请用 Tauri 桌面切换，或先运行 service_cli install",
        )
    try:
        target = _resolved_dir(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if str(target) == str(paths.data_dir().resolve()):
        return {"ok": True, "switching": False, "detail": "已在该工作区", "target": str(target)}

    log_dir = paths.service_state_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    switch_log = open(log_dir / "switch.log", "ab")
    subprocess.Popen(
        [
            sys.executable, "-m", "backend.service_cli", "install",
            "--port", str(config.get("port") or service_cli.DEFAULT_PORT),
            "--data-dir", str(target),
        ],
        cwd=str(paths.REPO_ROOT),
        start_new_session=True,
        stdout=switch_log,
        stderr=switch_log,
    )
    return {
        "ok": True,
        "switching": True,
        "target": str(target),
        "port": int(config.get("port") or service_cli.DEFAULT_PORT),
    }


@router.post("/remove")
def workspace_remove(payload: dict):
    """从注册表移除工作区，并可选删除本地数据目录。不可删除当前或 launchd 注册目录。"""
    raw = str(payload.get("data_dir") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="data_dir is required")
    delete_files = bool(payload.get("delete_files", True))
    try:
        target = _resolved_dir(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    current = paths.data_dir().resolve()
    if target == current:
        raise HTTPException(status_code=400, detail="不能删除当前正在使用的工作区")

    config = service_cli.read_service_config()
    if config and config.get("data_dir"):
        configured = Path(str(config["data_dir"])).expanduser().resolve()
        if target == configured:
            raise HTTPException(
                status_code=409,
                detail="不能删除 launchd 已注册的工作区，请先切换到其他工作区",
            )

    service_cli.remove_from_workspace_registry(target)
    if delete_files:
        try:
            service_cli.delete_workspace_directory(target)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"删除数据目录失败: {exc}") from exc

    return {"ok": True, "removed": str(target), "delete_files": delete_files}
