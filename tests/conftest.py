from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _force_stub_ai_mode(request, monkeypatch, tmp_path):
    """Pin the AI runtime to deterministic stub mode for the default test run.

    Without this, ``DeerFlowClientAdapter.from_env()`` resolves to direct/embedded
    whenever the dev shell exports ``OPENAI_API_KEY`` / ``WORKBENCH_AI_MODE``, which
    makes the deterministic Copilot-stream tests non-reproducible.

    Stub is forced via ``WORKBENCH_DEERFLOW_MODE=stub`` (the documented switch) while
    clearing any ambient ``WORKBENCH_AI_MODE`` — so tests that opt into embedded by
    setting their own ``WORKBENCH_DEERFLOW_MODE`` still win. Tests marked ``deerflow``
    (opt-in real-runtime smoke) or ``ai_regression`` (need real tool coverage + seed
    data) are exempt entirely.
    """
    if "deerflow" in request.keywords or "ai_regression" in request.keywords:
        return
    monkeypatch.delenv("WORKBENCH_AI_MODE", raising=False)
    # Clear ambient credentials so the embedded branch never auto-upgrades to direct
    # mode (which would hit a real model). This globalises the per-test
    # _force_stub_runtime intent; tests opting into embedded set their own
    # WORKBENCH_DEERFLOW_MODE and still get a clean (non-direct) runtime.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKBENCH_AI_API_KEY", raising=False)
    monkeypatch.setenv("WORKBENCH_DEERFLOW_MODE", "stub")
    monkeypatch.setenv("WORKBENCH_SKIP_SEED", "1")
    # 用户级凭证隔离：指向测试临时路径，避免开发机上的真实
    # credentials.json 经分层合成注入 env（embedded 会因此升格 direct）
    monkeypatch.setenv("WORKBENCH_CREDENTIALS_PATH", str(tmp_path / "credentials.json"))
