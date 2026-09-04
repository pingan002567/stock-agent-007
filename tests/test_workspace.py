from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend import paths
from backend import service_cli


@pytest.fixture()
def workspace_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    current = tmp_path / "current-ws"
    current.mkdir()
    (current / "workspace.json").write_text(
        json.dumps({"name": "当前工作区"}), encoding="utf-8",
    )
    other = tmp_path / "old-ws"
    other.mkdir()
    (other / "workspace.json").write_text(
        json.dumps({"name": "旧工作区"}), encoding="utf-8",
    )
    (other / "workbench.sqlite3").write_text("x", encoding="utf-8")

    registry = [
        {"dir": str(current), "name": "当前工作区", "last_used": "2026-01-01T00:00:00+00:00"},
        {"dir": str(other), "name": "旧工作区", "last_used": "2026-01-02T00:00:00+00:00"},
    ]
    (state_dir / "workspaces.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    monkeypatch.setattr(paths, "data_dir", lambda: current)
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(current))
    monkeypatch.setattr(service_cli, "_state_dir", lambda: state_dir)
    monkeypatch.setattr(
        service_cli,
        "read_service_config",
        lambda: {"port": 8686, "data_dir": str(current)},
    )
    return {"state_dir": state_dir, "current": current, "other": other}


def test_workspace_remove_deletes_registry_and_files(workspace_env):
    other: Path = workspace_env["other"]
    app = create_app(
        db_path=workspace_env["current"] / "workbench.sqlite3",
        files_root=workspace_env["current"] / "files",
    )
    client = TestClient(app)

    resp = client.post("/api/workspace/remove", json={"data_dir": str(other), "delete_files": True})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    registry = json.loads((workspace_env["state_dir"] / "workspaces.json").read_text(encoding="utf-8"))
    assert all(item["dir"] != str(other) for item in registry)
    assert not other.exists()

    listed = client.get("/api/workspace").json()
    assert all(w["dir"] != str(other) for w in listed["recents"])


def test_workspace_remove_blocks_current(workspace_env):
    current: Path = workspace_env["current"]
    app = create_app(db_path=current / "workbench.sqlite3", files_root=current / "files")
    client = TestClient(app)

    resp = client.post("/api/workspace/remove", json={"data_dir": str(current), "delete_files": True})
    assert resp.status_code == 400
    assert "当前" in resp.json()["detail"]
