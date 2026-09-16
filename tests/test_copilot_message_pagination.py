from __future__ import annotations

from fastapi.testclient import TestClient

from backend.schemas import CopilotMessage, CopilotSessionCreateRequest


def make_client(tmp_path) -> TestClient:
    from backend.app import create_app

    app = create_app(db_path=tmp_path / "copilot_page.sqlite3", files_root=tmp_path / "files")
    return TestClient(app)


def _seed_turns(repo, session_id: str, n: int) -> list[str]:
    """Insert n user turns each with a final_answer; return user message_ids oldest→newest."""
    user_ids: list[str] = []
    for i in range(n):
        run_id = f"run_{i:03d}"
        user_id = f"user_{i:03d}"
        user_ids.append(user_id)
        # Stagger timestamps so ordering is stable.
        ts = f"2026-01-01T00:{i:02d}:00+00:00"
        repo.save_copilot_message(
            CopilotMessage(
                message_id=user_id,
                session_id=session_id,
                role="user",
                kind="user_message",
                text=f"q{i}",
                run_id=run_id,
                created_at=ts,
            )
        )
        repo.save_copilot_message(
            CopilotMessage(
                message_id=f"final_{i:03d}",
                session_id=session_id,
                role="assistant",
                kind="final_answer",
                text=f"a{i}",
                run_id=run_id,
                created_at=f"2026-01-01T00:{i:02d}:30+00:00",
            )
        )
    return user_ids


def test_messages_without_limit_returns_full_history(tmp_path):
    client = make_client(tmp_path)
    services = client.app.state.services
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="page-full")
    )
    _seed_turns(services.repo, session.session_id, 5)

    resp = client.get(f"/api/copilot/sessions/{session.session_id}/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert "has_more" not in body
    assert len(body["items"]) == 10


def test_messages_limit_turns_returns_latest_page(tmp_path):
    client = make_client(tmp_path)
    services = client.app.state.services
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="page-latest")
    )
    user_ids = _seed_turns(services.repo, session.session_id, 5)

    resp = client.get(
        f"/api/copilot/sessions/{session.session_id}/messages",
        params={"limit_turns": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_more"] is True
    assert body["next_before"] == user_ids[3]  # oldest of the latest 2 turns (indices 3,4)
    texts = [m["text"] for m in body["items"] if m["role"] == "user"]
    assert texts == ["q3", "q4"]
    assert {m["text"] for m in body["items"] if m["kind"] == "final_answer"} == {"a3", "a4"}


def test_messages_before_cursor_loads_older_page(tmp_path):
    client = make_client(tmp_path)
    services = client.app.state.services
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="page-older")
    )
    user_ids = _seed_turns(services.repo, session.session_id, 5)

    first = client.get(
        f"/api/copilot/sessions/{session.session_id}/messages",
        params={"limit_turns": 2},
    ).json()
    second = client.get(
        f"/api/copilot/sessions/{session.session_id}/messages",
        params={"limit_turns": 2, "before": first["next_before"]},
    ).json()

    assert second["has_more"] is True
    assert second["next_before"] == user_ids[1]
    texts = [m["text"] for m in second["items"] if m["role"] == "user"]
    assert texts == ["q1", "q2"]

    third = client.get(
        f"/api/copilot/sessions/{session.session_id}/messages",
        params={"limit_turns": 2, "before": second["next_before"]},
    ).json()
    assert third["has_more"] is False
    assert third["next_before"] is None
    texts = [m["text"] for m in third["items"] if m["role"] == "user"]
    assert texts == ["q0"]


def test_messages_page_keeps_run_messages_together(tmp_path):
    client = make_client(tmp_path)
    services = client.app.state.services
    session = services.copilot_service.create_session(
        CopilotSessionCreateRequest(title="page-run")
    )
    sid = session.session_id
    services.repo.save_copilot_message(
        CopilotMessage(
            message_id="user_a",
            session_id=sid,
            role="user",
            kind="user_message",
            text="qa",
            run_id="run_a",
            created_at="2026-01-01T01:00:00+00:00",
        )
    )
    services.repo.save_copilot_message(
        CopilotMessage(
            message_id="tool_a",
            session_id=sid,
            role="assistant",
            kind="tool_result",
            text="tool",
            run_id="run_a",
            created_at="2026-01-01T01:00:10+00:00",
        )
    )
    services.repo.save_copilot_message(
        CopilotMessage(
            message_id="final_a",
            session_id=sid,
            role="assistant",
            kind="final_answer",
            text="aa",
            run_id="run_a",
            created_at="2026-01-01T01:00:20+00:00",
        )
    )
    services.repo.save_copilot_message(
        CopilotMessage(
            message_id="user_b",
            session_id=sid,
            role="user",
            kind="user_message",
            text="qb",
            run_id="run_b",
            created_at="2026-01-01T02:00:00+00:00",
        )
    )
    services.repo.save_copilot_message(
        CopilotMessage(
            message_id="final_b",
            session_id=sid,
            role="assistant",
            kind="final_answer",
            text="ab",
            run_id="run_b",
            created_at="2026-01-01T02:00:20+00:00",
        )
    )

    page = client.get(
        f"/api/copilot/sessions/{sid}/messages",
        params={"limit_turns": 1},
    ).json()
    assert page["has_more"] is True
    kinds = [m["kind"] for m in page["items"]]
    assert kinds == ["user_message", "final_answer"]
    assert page["items"][0]["text"] == "qb"

    older = client.get(
        f"/api/copilot/sessions/{sid}/messages",
        params={"limit_turns": 1, "before": page["next_before"]},
    ).json()
    assert older["has_more"] is False
    assert [m["kind"] for m in older["items"]] == [
        "user_message",
        "tool_result",
        "final_answer",
    ]
