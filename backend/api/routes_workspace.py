"""工作区（用户档案）API：当前档案信息 + vault 式切换（方案 A）。

切换 = 分离子进程跑 ``service_cli install --data-dir <新目录>``（会 bootout 当前
服务→重写 plist→bootstrap 新目录），本进程随之被 launchd 终止；前端收到响应后
轮询 /api/health 等新档案上线再整页刷新。仅在 launchd 服务形态下可用——dev
（start.sh 手动跑）没有服务可重装，返回 409。
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
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


@router.get("")
def workspace_info():
    data_dir = paths.data_dir().resolve()
    current = str(data_dir)
    config = service_cli.read_service_config()
    recents = [w for w in _registry() if w.get("dir") and w["dir"] != current]
    return {
        "name": _workspace_name(data_dir),
        "data_dir": current,
        "port": (config or {}).get("port"),
        "switchable": config is not None,
        "recents": recents,
    }


@router.post("/switch")
def workspace_switch(payload: dict):
    raw = str(payload.get("data_dir") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="data_dir is required")

    config = service_cli.read_service_config()
    if config is None:
        raise HTTPException(
            status_code=409,
            detail="当前以开发模式运行（无 launchd 服务），请用 service_cli install 切换",
        )
    try:
        target = service_cli.validate_data_dir(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if str(target) == str(paths.data_dir().resolve()):
        return {"ok": True, "switching": False, "detail": "已在该工作区"}

    # 分离子进程执行重装：install 会 bootout 当前服务（本进程随之退出），
    # start_new_session 让子进程脱离本服务的进程组、在 bootout 后存活完成
    # bootstrap。输出落状态目录 switch.log 供事后排障。
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
    return {"ok": True, "switching": True, "target": str(target)}
