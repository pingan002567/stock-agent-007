from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional
from uuid import uuid4

from backend.agent_runtime.deerflow_client import DeerFlowClientAdapter
from backend.agent_runtime.result_normalizer import ResultNormalizer
from backend.agent_runtime.skill_registry import SkillRegistry
from backend.app_services.audit_service import AuditService
from backend.app_services.context_builder import ContextBuilder
from backend.app_services.copilot_context_builder import CopilotContextBuilder
from backend.app_services.intent_router import IntentRouter
from backend.app_services.permission_guard import PermissionGuard
from backend.app_services.runtime_observer import RuntimeObserver
from backend.app_services.task_service import TaskService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    CopilotRunLog,
    AuthorityLevel,
    CopilotMessage,
    CopilotRequest,
    CopilotRun,
    CopilotSession,
    CopilotSessionCreateRequest,
    CopilotSessionMessageRequest,
    CopilotSessionUpdateRequest,
    SSEEvent,
    model_to_dict,
    now_iso,
)


from backend.app_services.copilot_cost import _estimate_cost
from backend.app_services.copilot_errors import (
    categorize_error,
    classify_outcome,
    error_hint,
)
from backend.app_services.copilot_session_state import (
    MAX_SESSION_STATES,
    SessionStateData,
    TurnSummary,
)


@dataclass
class CopilotRunState:
    request: CopilotRequest
    session_id: str
    message_id: str
    task_id: str
    intent: str
    skill: str
    skill_trace: list[dict[str, Any]]


class CopilotService:
    def __init__(
        self,
        *,
        repo: WorkbenchRepository,
        context_builder: ContextBuilder,
        copilot_context_builder: CopilotContextBuilder,
        intent_router: IntentRouter,
        permission_guard: PermissionGuard,
        task_service: TaskService,
        audit_service: AuditService,
        deerflow: DeerFlowClientAdapter,
        skill_registry: SkillRegistry,
        result_normalizer: ResultNormalizer,
        runtime_observer: RuntimeObserver,
    ) -> None:
        self.repo = repo
        self.context_builder = context_builder
        self.copilot_context_builder = copilot_context_builder
        self.intent_router = intent_router
        self.permission_guard = permission_guard
        self.task_service = task_service
        self.audit_service = audit_service
        self.deerflow = deerflow
        self.skill_registry = skill_registry
        self.result_normalizer = result_normalizer
        self.runtime_observer = runtime_observer
        self._runs: Dict[str, CopilotRunState] = {}
        self._session_states: dict[str, SessionStateData] = {}

    def reconnect_runtime(self) -> dict[str, Any]:
        """Re-initialize DeerFlowClientAdapter from persisted runtime_config.

        Called after settings change so the runtime transitions from stub to
        embedded without a server restart.
        """
        # 兼容两种配置格式：直接在顶层或在 config 子键下
        raw_config = self.repo.get_config("runtime", {})
        runtime_config = raw_config.get("config", raw_config)
        new_adapter = DeerFlowClientAdapter.from_env(
            tool_bridge=self.deerflow.tool_bridge,
            runtime_config=runtime_config,
        )
        self.deerflow = new_adapter
        status = new_adapter.status().to_dict()
        self.audit_service.record(
            f"runtime reconnected: mode={status['mode']} active={status['active_client']} degraded={status['degraded']}",
            "runtime",
        )
        return status

    def test_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Quick model connectivity test against configured endpoint."""
        import logging

        logger = logging.getLogger("copilot_service")
        api_key = (
            payload.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("WORKBENCH_AI_API_KEY")
        )
        base_url = payload.get("base_url") or os.environ.get("OPENAI_BASE_URL") or ""
        model_name = payload.get("model_name") or self.deerflow.model_name or "gpt-4o"
        if not api_key:
            return {
                "ok": False,
                "error": "API Key 未配置。请在设置页输入或设置 OPENAI_API_KEY 环境变量。",
                "model": model_name,
                "base_url": base_url or "default",
            }
        try:
            import httpx

            url = (
                f"{base_url.rstrip('/')}/chat/completions"
                if base_url
                else "https://api.openai.com/v1/chat/completions"
            )
            transport = httpx.HTTPTransport(proxy=None)
            with httpx.Client(transport=transport, timeout=30) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        # Reasoning/thinking models spend tokens on the hidden trace;
                        # a tiny cap (e.g. 5) makes them return HTTP 400. Keep it small
                        # but large enough to clear the reasoning budget.
                        "max_tokens": 256,
                    },
                )
                if resp.status_code >= 400:
                    # Surface the upstream error body — a bare "HTTP 400" hides the
                    # real reason (bad model name, unsupported param, quota, etc.).
                    detail = resp.text.strip()
                    try:
                        body = resp.json()
                        detail = (
                            (body.get("error") or {}).get("message")
                            if isinstance(body.get("error"), dict)
                            else body.get("error") or body.get("message") or detail
                        )
                    except Exception:
                        pass
                    logger.warning(
                        "connection test HTTP %s: model=%s detail=%s",
                        resp.status_code, model_name, detail,
                    )
                    return {
                        "ok": False,
                        "error": f"HTTP {resp.status_code}: {str(detail)[:500]}",
                        "model": model_name,
                        "base_url": base_url or "default",
                    }
                data = resp.json()
            logger.info(
                "connection test OK: model=%s base_url=%s",
                model_name,
                base_url or "openai",
            )
            return {
                "ok": True,
                "model": data.get("model", model_name),
                "base_url": base_url or "https://api.openai.com/v1",
                "latency_ms": round(resp.elapsed.total_seconds() * 1000),
            }
        except Exception as exc:
            logger.warning("connection test failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "model": model_name,
                "base_url": base_url or "default",
            }

    def _get_previous_tool_calls(self, session_id: str, current_run_id: str) -> list[dict[str, str]]:
        """Get tool calls from the previous run in the same session."""
        messages = self.repo.list_copilot_messages(session_id=session_id)
        
        runs: dict[str, list[CopilotMessage]] = {}
        for msg in messages:
            if msg.run_id:
                runs.setdefault(msg.run_id, []).append(msg)
        
        run_ids_ordered = sorted(
            runs.keys(),
            key=lambda rid: min(m.created_at for m in runs[rid]),
        )
        
        previous_run_id = None
        for rid in reversed(run_ids_ordered):
            if rid != current_run_id:
                previous_run_id = rid
                break
        
        if not previous_run_id:
            return []
        
        tool_calls_map: dict[str, dict[str, str]] = {}
        for msg in runs[previous_run_id]:
            if msg.kind == 'tool_call':
                payload = json.loads(msg.payload) if isinstance(msg.payload, str) else msg.payload
                tool_name = payload.get('tool', '')
                if tool_name:
                    tool_calls_map[tool_name] = {
                        'tool': tool_name,
                        'called_at': msg.created_at,
                    }
            elif msg.kind == 'tool_result':
                payload = json.loads(msg.payload) if isinstance(msg.payload, str) else msg.payload
                tool_name = payload.get('tool', '')
                if tool_name in tool_calls_map:
                    result = payload.get('result', '')
                    result_str = str(result)
                    result_summary = result_str[:200] + '...' if len(result_str) > 200 else result_str
                    tool_calls_map[tool_name]['result_summary'] = result_summary
        
        return list(tool_calls_map.values())

    def list_sessions(self) -> list[CopilotSession]:
        return self.repo.list_copilot_sessions(limit=100)

    def create_session(self, payload: CopilotSessionCreateRequest) -> CopilotSession:
        created_at = now_iso()
        title = (payload.title or "").strip() or self._derive_title(
            anchor_symbol=payload.anchor_symbol, message=None
        )
        session = CopilotSession(
            session_id=f"session_{uuid4().hex[:12]}",
            title=title,
            current_page=payload.current_page,
            anchor_symbol=payload.anchor_symbol,
            authority_level=payload.authority_level,
            created_at=created_at,
            updated_at=created_at,
            last_message_at=None,
        )
        return self.repo.save_copilot_session(session)

    def get_session(self, session_id: str) -> CopilotSession:
        session = self.repo.get_copilot_session(session_id)
        if not session:
            raise KeyError(session_id)
        return session

    def update_session(
        self, session_id: str, payload: CopilotSessionUpdateRequest
    ) -> CopilotSession:
        session = self.get_session(session_id)
        session.title = payload.title.strip()
        session.updated_at = now_iso()
        return self.repo.save_copilot_session(session)

    def delete_session(self, session_id: str) -> None:
        self.get_session(session_id)
        self.repo.delete_copilot_session(session_id)

    def list_messages(
        self, session_id: str, *, run_id: str | None = None
    ) -> list[CopilotMessage]:
        self.get_session(session_id)
        return self.repo.list_copilot_messages(session_id=session_id, run_id=run_id)

    def has_run(self, run_id: str, session_id: str | None = None) -> bool:
        if run_id in self._runs:
            state = self._runs[run_id]
            return session_id is None or state.session_id == session_id
        if self.repo.get_task_by_run_id(
            run_id
        ) and self.repo.get_copilot_user_message_by_run_id(run_id):
            if session_id is None:
                return True
            message = self.repo.get_copilot_user_message_by_run_id(run_id)
            return bool(message and message.session_id == session_id)
        return False

    def create_session_run(
        self, session_id: str, payload: CopilotSessionMessageRequest
    ) -> CopilotRun:
        session = self.get_session(session_id)
        request = CopilotRequest(
            message=payload.message,
            page=payload.page or session.current_page,
            symbol=payload.symbol or session.anchor_symbol,
            authority_level=payload.authority_level or session.authority_level,
            session_id=session_id,
            client_message_id=payload.client_message_id,
        )
        return self.create_run(request)

    def create_run(self, request: CopilotRequest) -> CopilotRun:
        session = self._ensure_session(request)
        intent = self.intent_router.route(request.message, request.page, request.symbol)
        required = AuthorityLevel(intent.required_authority)
        self.permission_guard.require(request.authority_level, required, intent.name)
        self.skill_registry.get(intent.skill)
        run_id = f"run_{uuid4().hex[:10]}"
        skill_trace = self._build_skill_trace(intent.name, request)
        task = self.task_service.create(
            title=f"Copilot: {intent.name}",
            source=intent.skill,
            current_step="skill_plan_ready",
            run_id=run_id,
            skill_trace=skill_trace,
        )
        message_id = f"message_{uuid4().hex[:12]}"
        self.repo.save_copilot_message(
            CopilotMessage(
                message_id=message_id,
                session_id=session.session_id,
                role="user",
                kind="user_message",
                text=request.message,
                page=request.page,
                symbol=request.symbol,
                run_id=run_id,
                task_id=task.task_id,
                client_message_id=request.client_message_id,
                payload={
                    "request": {
                        "page": request.page,
                        "symbol": request.symbol,
                        "authority_level": request.authority_level.value,
                    },
                    "intent": intent.name,
                    "skill": intent.skill,
                    "skills": [item["skill"] for item in skill_trace],
                },
            )
        )
        session = self._refresh_session_title(session, request)
        self._runs[run_id] = CopilotRunState(
            request=request,
            session_id=session.session_id,
            message_id=message_id,
            task_id=task.task_id,
            intent=intent.name,
            skill=intent.skill,
            skill_trace=skill_trace,
        )
        skill_names = ",".join(item["skill"] for item in skill_trace)
        self.audit_service.record(
            "Copilot run created",
            f"{intent.name} skill={intent.skill} trace={skill_names}",
            required,
        )
        runtime_status = self.deerflow.status().to_dict()
        self.runtime_observer.save_copilot_run_log(
            CopilotRunLog(
                run_id=run_id,
                session_id=session.session_id,
                task_id=task.task_id,
                mode=runtime_status["mode"],
                active_client=runtime_status["active_client"],
                model_name=runtime_status["model_name"],
                status="running",
                tool_call_count=0,
                started_at=now_iso(),
                payload={
                    "intent": intent.name,
                    "skill": intent.skill,
                    "page": request.page,
                    "symbol": request.symbol,
                },
            )
        )
        return CopilotRun(
            run_id=run_id,
            task_id=task.task_id,
            intent=intent.name,
            skill=intent.skill,
            skills=[item["skill"] for item in skill_trace],
            session_id=session.session_id,
            message_id=message_id,
        )

    async def stream_run(
        self,
        run_id: str,
        task_id: Optional[str] = None,
        session_id: str | None = None,
    ) -> AsyncIterator[SSEEvent]:
        _start_time = time.monotonic()
        persisted_messages = self.repo.list_copilot_run_messages(run_id)
        persisted_events = [item for item in persisted_messages if item.role != "user"]
        if any(item.kind == "final_answer" for item in persisted_events):
            for item in persisted_events:
                yield self._message_to_event(item)
            return

        if persisted_events:
            recovered_state = self._runs.get(run_id) or self._recover_run_state(
                run_id, session_id
            )
            if not recovered_state:
                raise KeyError(run_id)
            for item in persisted_events:
                yield self._message_to_event(item)
            resolved_task_id = task_id or recovered_state.task_id
            error_event = SSEEvent(
                run_id=run_id,
                task_id=resolved_task_id,
                type="error",
                payload={
                    "stage": "stream_recovery",
                    "error": "copilot stream interrupted after partial output; start a new run to avoid re-executing tools",
                    "authority_level": recovered_state.request.authority_level.value,
                },
            )
            final_payload = self.result_normalizer.normalize_final(
                {
                    "conclusion": "本次 AI Chat 流式输出已中断，系统已停止恢复执行以避免重复创建报告、草案、审查或 snapshot。",
                    "confidence": "low",
                    "counter_reasons": ["检测到已有部分 SSE 事件但缺少 final_answer。"],
                    "evidence_refs": ["copilot_message", "stream_recovery_guard"],
                    "next_actions": ["重新发送消息以创建新的 run_id。"],
                    "disclaimer": "仅供研究，不构成投资建议。",
                }
            )
            final_event = SSEEvent(
                run_id=run_id,
                task_id=resolved_task_id,
                type="final",
                payload=final_payload,
            )
            self._persist_stream_event(recovered_state, error_event)
            self._persist_stream_event(recovered_state, final_event)
            self._update_task_step(
                resolved_task_id, "stream_recovery_stopped", 100, status="failed"
            )
            self._upsert_run_log(
                run_id,
                status="failed",
                error_category="stream_recovery",
                runtime_error=str(error_event.payload.get("error") or ""),
                latency_ms=(time.monotonic() - _start_time) * 1000,
            )
            yield error_event
            yield final_event
            self._runs.pop(run_id, None)
            return

        state = self._runs.get(run_id) or self._recover_run_state(run_id, session_id)
        if not state:
            raise KeyError(run_id)

        request = state.request
        # 上下文构建是同步的 repo/provider I/O（_symbol_summary 可能命中数据源），直接在
        # async 生成器里调用会阻塞事件循环、拖慢首字节并卡住其他并发请求。卸载到线程池。
        # SQLite 连接以 check_same_thread=False 打开，这里均为只读查询，跨线程安全。
        context = await asyncio.to_thread(
            self.copilot_context_builder.build,
            page=request.page,
            symbol=request.symbol,
            intent=state.intent,
        )
        session_state = self._get_or_create_session_state(state.session_id)
        if session_state.total_runs > 0:
            context["session_state"] = session_state.to_context()

        previous_tool_calls = await asyncio.to_thread(
            self._get_previous_tool_calls, state.session_id, run_id
        )
        if previous_tool_calls:
            context["previous_tool_calls"] = previous_tool_calls

        runtime_context = {**context, "_authority_level": request.authority_level.value}
        resolved_task_id = task_id or state.task_id
        # 按工具名捕获最近一次有意义的结果，供 final 阶段回填。
        # 单一累加器替代散落的硬编码 if 块（见 _capture_tool_result）。
        captured: Dict[str, Dict[str, Any] | None] = {
            "report": None,
            "draft": None,
            "review": None,
        }
        tool_call_events: list[dict[str, Any]] = []
        tool_result_events: list[dict[str, Any]] = []
        final_seen = False

        skill_trace_payload = {
            "phase": "declared",
            "items": state.skill_trace,
            "note": "声明式 skill trace；实际推理和工具流由 DeerFlow adapter 边界输出。",
        }
        skill_event = SSEEvent(
            run_id=run_id,
            task_id=resolved_task_id,
            type="skill_trace",
            payload=skill_trace_payload,
        )
        self._persist_stream_event(state, skill_event)
        yield skill_event
        self._update_task_step(resolved_task_id, "skill_trace_declared", 20)

        try:
            async for event in self.deerflow.stream(
                run_id=run_id,
                task_id=resolved_task_id,
                skill=state.skill,
                message=request.message,
                context=runtime_context,
                skill_trace=state.skill_trace,
                history=[],
                session_id=state.session_id,
                subagent_enabled=state.intent in {"rebalance_plan", "strategy_backtest"},
            ):
                payload = event["payload"]
                self._capture_tool_result(event, captured)
                if event["type"] == "final":
                    last_report_result = captured["report"]
                    last_draft_result = captured["draft"]
                    last_review_result = captured["review"]
                    try:
                        payload = self.result_normalizer.normalize_final(payload)
                        payload["skill_trace"] = state.skill_trace
                        payload.setdefault(
                            "evidence_refs",
                            self._evidence_refs(state.skill_trace, context),
                        )
                        if last_report_result:
                            self.copilot_context_builder._cache.invalidate(
                                "reports_summary"
                            )
                            payload.setdefault(
                                "report_id", last_report_result.get("report_id")
                            )
                            payload.setdefault(
                                "quality_status",
                                last_report_result.get("quality_status"),
                            )
                            payload.setdefault(
                                "evidence_refs",
                                last_report_result.get("evidence_refs")
                                or payload.get("evidence_refs"),
                            )
                            payload.setdefault(
                                "valid_until", last_report_result.get("valid_until")
                            )
                            payload["disclaimer"] = (
                                last_report_result.get("disclaimer")
                                or payload["disclaimer"]
                            )
                            if last_report_result.get("candidate_actions"):
                                payload["execution_guard"] = {
                                    **(last_report_result.get("execution_guard") or {}),
                                    "auto_trade": False,
                                }
                        if any(
                            item["skill"] in {"rebalance-planner", "strategy-analyst"}
                            for item in state.skill_trace
                        ):
                            payload["execution_guard"] = {
                                "research_only": True,
                                "auto_trade": False,
                                "status": "real_order_disabled",
                                "reason": "V1 只提供研究结论与拟单草案，真实交易保持关闭。",
                            }
                        if last_draft_result:
                            self.copilot_context_builder._cache.invalidate(
                                "holdings_summary"
                            )
                            self.copilot_context_builder._cache.invalidate(
                                "inbox_summary"
                            )
                            payload["draft_id"] = last_draft_result.get("draft_id")
                            payload["draft_status"] = last_draft_result.get(
                                "draft_status"
                            ) or last_draft_result.get("status")
                            if last_draft_result.get("status") == "needs_confirmation":
                                payload.setdefault("next_actions", []).append(
                                    "在调仓页显式创建或确认草案。"
                                )
                        if last_review_result:
                            self.copilot_context_builder._cache.invalidate(
                                "holdings_summary"
                            )
                            self.copilot_context_builder._cache.invalidate(
                                "inbox_summary"
                            )
                            payload["review_id"] = last_review_result.get("review_id")
                            payload["review_status"] = last_review_result.get("status")
                            payload["status"] = last_review_result.get("status")
                            payload["blockers"] = list(
                                last_review_result.get("blocker_codes") or []
                            )
                            payload["blocker_codes"] = list(
                                last_review_result.get("blocker_codes") or []
                            )
                            payload["execution_guard"] = last_review_result.get(
                                "execution_guard"
                            ) or payload.get("execution_guard")
                            if last_review_result.get("status") == "needs_confirmation":
                                payload.setdefault("next_actions", []).append(
                                    "在审查页显式发起 pre-trade review。"
                                )
                        payload["suggested_actions"] = self._suggest_actions(
                            page=request.page,
                            symbol=request.symbol,
                            context=context,
                            skill_trace=state.skill_trace,
                            last_report_result=last_report_result,
                            last_draft_result=last_draft_result,
                            last_review_result=last_review_result,
                        )
                        self._update_task_step(
                            resolved_task_id, "final", 100, status="done"
                        )
                        usage = payload.get("usage") or {}
                        self._upsert_run_log(
                            run_id,
                            status="completed",
                            tool_call_count=len(
                                [
                                    item
                                    for item in self.repo.list_copilot_run_messages(
                                        run_id
                                    )
                                    if item.kind == "tool_call"
                                ]
                            ),
                            usage_input_tokens=usage.get("input_tokens"),
                            usage_output_tokens=usage.get("output_tokens")
                            or usage.get("completion_tokens"),
                            latency_ms=(time.monotonic() - _start_time) * 1000,
                        )
                    except Exception as exc:
                        payload = self.result_normalizer.normalize_final(
                            payload
                            if isinstance(payload, dict)
                            else {"conclusion": "AI 最终收口已降级。"}
                        )
                        payload.setdefault("counter_reasons", []).append(
                            f"final enrichment degraded: {type(exc).__name__}"
                        )
                        payload.setdefault("skill_trace", state.skill_trace)
                        payload.setdefault(
                            "evidence_refs",
                            self._evidence_refs(state.skill_trace, context),
                        )
                sse_event = SSEEvent(
                    run_id=run_id,
                    task_id=resolved_task_id,
                    type=event["type"],
                    payload=payload,
                )
                if event["type"] == "tool_call":
                    tool_call_events.append(payload)
                elif event["type"] == "tool_result":
                    tool_result_events.append(payload)
                # Handle final events - skip empty ones, keep the one with content
                if event["type"] == "final":
                    conclusion = str(payload.get("conclusion") or "")
                    if not conclusion:
                        # Skip empty final events
                        continue
                    if final_seen:
                        # Already have a final with content, skip
                        continue
                    final_seen = True
                if event["type"] not in ("reasoning", "partial_answer", "skill_trace"):
                    self._persist_stream_event(state, sse_event)
                yield sse_event
                if event["type"] in ("final", "error"):
                    turn = self._build_turn_summary(
                        intent=state.intent,
                        user_message=request.message,
                        tool_call_events=tool_call_events,
                        tool_result_events=tool_result_events,
                        final_payload=payload if event["type"] == "final" else None,
                        error_payload=payload if event["type"] == "error" else None,
                    )
                    self._update_session_state(state.session_id, turn)
        except Exception as exc:
            error_sse = SSEEvent(
                run_id=run_id,
                task_id=resolved_task_id,
                type="error",
                payload={
                    "stage": "stream_run",
                    "error": f"stream crashed: {exc}",
                    "authority_level": request.authority_level.value,
                },
            )
            self._persist_stream_event(state, error_sse)
            yield error_sse
            fallback_payload = self.result_normalizer.normalize_final(
                {
                    "conclusion": f"AI 流处理异常中断：{exc}",
                    "confidence": "low",
                    "counter_reasons": [f"未预期异常：{type(exc).__name__}"],
                    "disclaimer": "仅供研究，不构成投资建议。",
                }
            )
            final_sse = SSEEvent(
                run_id=run_id,
                task_id=resolved_task_id,
                type="final",
                payload=fallback_payload,
            )
            self._persist_stream_event(state, final_sse)
            yield final_sse
            turn = self._build_turn_summary(
                intent=state.intent,
                user_message=request.message,
                tool_call_events=tool_call_events,
                tool_result_events=tool_result_events,
                final_payload=None,
                error_payload={"error": str(exc)},
            )
            self._update_session_state(state.session_id, turn)
            self._update_task_step(
                resolved_task_id, "stream_crashed", 100, status="failed"
            )
            self._upsert_run_log(
                run_id,
                status="failed",
                error_category=categorize_error(exc),
                runtime_error=str(exc),
                latency_ms=(time.monotonic() - _start_time) * 1000,
            )
        self._runs.pop(run_id, None)

    @staticmethod
    def _capture_tool_result(
        event: dict[str, Any], captured: dict[str, dict[str, Any] | None]
    ) -> None:
        """Record the latest meaningful tool_result into ``captured`` for final enrichment.

        Replaces three hardcoded per-tool if-blocks in stream_run. Behavior is
        preserved exactly: report is only captured when not pending confirmation;
        draft/review are captured whenever the result is a dict.
        """
        if event.get("type") != "tool_result":
            return
        payload = event.get("payload") or {}
        result = payload.get("result")
        if not isinstance(result, dict):
            return
        tool = payload.get("tool")
        if tool == "generate_report":
            if result.get("status") != "needs_confirmation":
                captured["report"] = result
        elif tool in ("generate_draft_order", "confirm_rebalance_draft"):
            captured["draft"] = result
        elif tool == "create_pre_trade_review":
            captured["review"] = result

    def _ensure_session(self, request: CopilotRequest) -> CopilotSession:
        if request.session_id:
            session = self.repo.get_copilot_session(request.session_id)
            if not session:
                raise KeyError(request.session_id)
            return session
        return self.create_session(
            CopilotSessionCreateRequest(
                title=self._derive_title(
                    anchor_symbol=request.symbol, message=request.message
                ),
                current_page=request.page,
                anchor_symbol=request.symbol,
                authority_level=request.authority_level,
            )
        )

    def _refresh_session_title(
        self, session: CopilotSession, request: CopilotRequest
    ) -> CopilotSession:
        derived = self._derive_title(
            anchor_symbol=request.symbol, message=request.message
        )
        if session.title and session.title != "新会话":
            return session
        updated = session.model_copy(
            update={
                "title": derived,
                "current_page": request.page,
                "anchor_symbol": request.symbol or session.anchor_symbol,
                "authority_level": request.authority_level,
                "updated_at": now_iso(),
            }
        )
        return self.repo.save_copilot_session(updated)

    def _recover_run_state(
        self, run_id: str, session_id: str | None
    ) -> CopilotRunState | None:
        user_message = self.repo.get_copilot_user_message_by_run_id(run_id)
        task = self.repo.get_task_by_run_id(run_id)
        if not user_message or not task:
            return None
        if session_id and user_message.session_id != session_id:
            return None
        session = self.repo.get_copilot_session(user_message.session_id)
        if not session:
            return None
        request = CopilotRequest(
            message=user_message.text,
            page=(user_message.payload.get("request") or {}).get("page")
            or user_message.page
            or session.current_page,
            symbol=(user_message.payload.get("request") or {}).get("symbol")
            or user_message.symbol
            or session.anchor_symbol,
            authority_level=AuthorityLevel(
                (user_message.payload.get("request") or {}).get("authority_level")
                or session.authority_level
            ),
            session_id=session.session_id,
            client_message_id=user_message.client_message_id,
        )
        intent_name = (
            str(user_message.payload.get("intent") or "")
            or self.intent_router.route(
                request.message, request.page, request.symbol
            ).name
        )
        skill_name = str(user_message.payload.get("skill") or "") or task.source
        skill_trace = task.skill_trace or self._build_skill_trace(intent_name, request)
        return CopilotRunState(
            request=request,
            session_id=session.session_id,
            message_id=user_message.message_id,
            task_id=task.task_id,
            intent=intent_name,
            skill=skill_name,
            skill_trace=skill_trace,
        )

    def _persist_stream_event(self, state: CopilotRunState, event: SSEEvent) -> None:
        role, kind, text, payload = self._serialize_event(event.type, event.payload)
        self.repo.save_copilot_message(
            CopilotMessage(
                message_id=f"message_{uuid4().hex[:12]}",
                session_id=state.session_id,
                role=role,
                kind=kind,
                text=text,
                page=state.request.page,
                symbol=state.request.symbol,
                run_id=event.run_id,
                task_id=event.task_id,
                payload=payload,
                created_at=event.created_at,
            )
        )

    def _message_to_event(self, message: CopilotMessage) -> SSEEvent:
        return SSEEvent(
            run_id=message.run_id or "run_none",
            task_id=message.task_id or "task_none",
            type=self._event_type_for_kind(message.kind),
            payload=message.payload,
            created_at=message.created_at,
        )

    def _serialize_event(
        self, event_type: str, payload: dict[str, Any]
    ) -> tuple[str, str, str, dict[str, Any]]:
        if event_type == "skill_trace":
            data = {
                "phase": payload.get("phase"),
                "items": payload.get("items") or [],
                "note": payload.get("note"),
            }
            return "system", "skill_trace", payload.get("note") or "skill trace", data
        if event_type == "tool_call":
            args = payload.get("arguments") or {}
            preview = {
                key: value
                for key, value in args.items()
                if key
                in {
                    "symbol",
                    "report_type",
                    "source_type",
                    "source_id",
                    "strategy_id",
                    "limit",
                    "priority",
                    "status",
                }
            }
            data = {
                "tool": payload.get("tool"),
                "call_id": payload.get("call_id"),
                "authority_level": payload.get("authority_level"),
                "argument_keys": sorted(args.keys()),
                "arguments_preview": preview,
            }
            return (
                "assistant",
                "tool_call",
                str(payload.get("tool") or "tool_call"),
                data,
            )
        if event_type == "tool_result":
            result = payload.get("result")
            data = {
                "tool": payload.get("tool"),
                "call_id": payload.get("call_id"),
                "execution_mode": payload.get("execution_mode"),
                "risk": payload.get("risk"),
                "result_preview": self._tool_result_preview(
                    str(payload.get("tool") or ""), result
                ),
            }
            return (
                "tool",
                "tool_result",
                str(payload.get("tool") or "tool_result"),
                data,
            )
        if event_type == "partial_answer":
            data = {"text": payload.get("text", "")}
            return "assistant", "partial_answer", data["text"], data
        if event_type == "reasoning":
            data = {
                "text": payload.get("text"),
                "phase": payload.get("phase"),
                "status": payload.get("status"),
                "latest_text": payload.get("latest_text"),
            }
            return (
                "system",
                "reasoning",
                data.get("text") or data.get("phase") or "reasoning",
                data,
            )
        if event_type == "error":
            data = {
                "tool": payload.get("tool"),
                "call_id": payload.get("call_id"),
                "error": payload.get("error"),
                "authority_level": payload.get("authority_level"),
                "stage": payload.get("stage"),
            }
            return "system", "error", str(payload.get("error") or "error"), data
        data = {
            "conclusion": payload.get("conclusion"),
            "confidence": payload.get("confidence"),
            "disclaimer": payload.get("disclaimer"),
            "evidence_refs": payload.get("evidence_refs")
            or payload.get("tool_evidence_refs")
            or [],
            "report_id": payload.get("report_id"),
            "quality_status": payload.get("quality_status"),
            "draft_id": payload.get("draft_id"),
            "draft_status": payload.get("draft_status"),
            "review_id": payload.get("review_id"),
            "review_status": payload.get("review_status"),
            "blocker_codes": payload.get("blocker_codes") or [],
            "next_actions": payload.get("next_actions") or [],
        }
        return (
            "assistant",
            "final_answer",
            str(payload.get("conclusion") or ""),
            data,
        )

    def _tool_result_preview(self, tool: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"value": result}
        if result.get("status") == "needs_confirmation":
            return {
                "status": result.get("status"),
                "reason": result.get("reason"),
                "next_action": result.get("next_action"),
            }
        preview_keys = {
            "run_id",
            "strategy_id",
            "report_id",
            "quality_status",
            "valid_until",
            "draft_id",
            "draft_status",
            "review_id",
            "status",
            "summary",
            "open_count",
            "high_count",
            "overdue_count",
            "snoozed_count",
            "snapshot_id",
            "market_value",
            "cash_estimate",
            "equity_estimate",
            "pnl_estimate",
            "risk_count",
        }
        preview = {key: value for key, value in result.items() if key in preview_keys}
        if tool == "generate_report":
            preview["candidate_action_count"] = len(
                result.get("candidate_actions") or []
            )
        return preview

    def _event_type_for_kind(self, kind: str) -> str:
        return {
            "skill_trace": "skill_trace",
            "tool_call": "tool_call",
            "tool_result": "tool_result",
            "partial_answer": "partial_answer",
            "reasoning": "reasoning",
            "error": "error",
            "final_answer": "final",
        }.get(kind, "reasoning")

    def _derive_title(self, *, anchor_symbol: str | None, message: str | None) -> str:
        if message:
            trimmed = message.strip()
            if trimmed:
                return trimmed[:24]
        if anchor_symbol:
            return f"{anchor_symbol.upper()} 会话"
        return "新会话"

    def _build_turn_summary(
        self,
        *,
        intent: str,
        user_message: str,
        tool_call_events: list[dict[str, Any]],
        tool_result_events: list[dict[str, Any]],
        final_payload: dict[str, Any] | None,
        error_payload: dict[str, Any] | None,
    ) -> TurnSummary:
        outcome = classify_outcome(error_payload)
        hint = error_hint(error_payload) if error_payload else None
        state_changes = self._extract_state_changes(tool_call_events, tool_result_events)
        summary = self._build_summary_text(outcome, tool_result_events, hint)
        return TurnSummary(
            question=user_message[:100],
            intent=intent,
            outcome=outcome,
            summary=summary,
            state_changes=state_changes,
            error_hint=hint,
        )

    @staticmethod
    def _build_summary_text(
        outcome: str,
        tool_results: list[dict[str, Any]],
        error_hint: str | None,
    ) -> str:
        parts: list[str] = []
        for t in tool_results:
            tool_name = t.get("tool", "")
            if tool_name == "generate_draft_order":
                preview = t.get("result_preview") or {}
                draft_id = preview.get("draft_id", "")
                parts.append(f"生成了草案 {draft_id}" if draft_id else "生成了草案")
            elif tool_name == "confirm_rebalance_draft":
                parts.append("确认了草案")
            elif tool_name == "create_pre_trade_review":
                preview = t.get("result_preview") or {}
                review_id = preview.get("review_id", "")
                parts.append(f"创建了审查 {review_id}" if review_id else "创建了交易前审查")
            elif tool_name == "generate_report":
                preview = t.get("result_preview") or {}
                report_id = preview.get("report_id", "")
                parts.append(f"生成了报告 {report_id}" if report_id else "生成了报告")
        if outcome != "success" and error_hint:
            hints: dict[str, str] = {
                "DRAFT_NOT_CONFIRMED": "草案需先在持仓页确认后才能审查",
                "MISSING_DRAFT_ID": "请先生成草案再操作",
                "DRAFT_ALREADY_CONFIRMED": "草案已是已确认状态，无需重复操作",
                "DRAFT_EXPIRED": "草案已过期，需要重新生成",
                "PERMISSION_DENIED": "权限不足，该操作仅限页面显式触发",
            }
            parts.append(hints.get(error_hint, "操作未完成"))
        elif outcome != "success":
            parts.append("操作未完成")
        return "。".join(parts) if parts else "无具体操作。"

    @staticmethod
    def _extract_state_changes(
        tool_calls: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result_by_call = {
            r.get("call_id", ""): r
            for r in tool_results
            if r.get("call_id")
        }
        state: dict[str, list[dict[str, Any]]] = {
            "generated_drafts": [],
            "confirmed_drafts": [],
            "created_reviews": [],
            "generated_reports": [],
        }
        for tc in tool_calls:
            tool = tc.get("tool", "")
            args = tc.get("arguments_preview") or {}
            call_id = tc.get("call_id", "")
            tr = result_by_call.get(call_id, {})
            preview = tr.get("result_preview") or {}
            if tool == "generate_draft_order":
                draft_id = preview.get("draft_id") or ""
                symbol = args.get("symbol") or tr.get("symbol") or ""
                state["generated_drafts"].append({"id": draft_id, "symbol": symbol})
            elif tool == "confirm_rebalance_draft":
                draft_id = preview.get("draft_id") or args.get("draft_id") or ""
                state["confirmed_drafts"].append({"id": draft_id})
            elif tool == "create_pre_trade_review":
                review_id = preview.get("review_id") or ""
                draft_id = preview.get("draft_id") or args.get("draft_id") or ""
                state["created_reviews"].append({"id": review_id, "draft_id": draft_id})
            elif tool == "generate_report":
                report_id = preview.get("report_id") or ""
                state["generated_reports"].append({"id": report_id})
        return state

    def _get_or_create_session_state(self, session_id: str) -> SessionStateData:
        # session_state 只是内存里的轮次记忆。原实现的 dict 只增不删，单进程长跑会无限膨胀。
        # 这里做 LRU 上限淘汰：命中则移到末尾，新建超限则丢弃最久未用的会话。
        state = self._session_states.pop(session_id, None)
        if state is None:
            state = SessionStateData(active_drafts={}, active_reviews={})
            while len(self._session_states) >= MAX_SESSION_STATES:
                self._session_states.pop(next(iter(self._session_states)))
        self._session_states[session_id] = state
        return state

    def _update_session_state(self, session_id: str, turn: TurnSummary) -> None:
        state = self._get_or_create_session_state(session_id)
        state.apply_turn(turn)

    def _build_skill_trace(
        self, intent_name: str, request: CopilotRequest
    ) -> list[dict[str, Any]]:
        # Single source of truth: intent→skill plans + per-skill authority come
        # from skill_specs (same table that drives subagents/registry).
        from backend.agent_runtime import skill_specs

        plans = skill_specs.intent_plans()
        authority = skill_specs.skill_authority()
        trace = []
        plan = self._resolve_plan(intent_name, request, plans)
        for index, skill_name in enumerate(plan, start=1):
            spec = self.skill_registry.skills[skill_name]
            blocked_reason = (
                "real order execution is disabled in V1"
                if spec.locked or not spec.enabled
                else None
            )
            trace.append(
                {
                    "step": index,
                    "skill": spec.name,
                    "label": spec.label,
                    "tools": spec.tools,
                    "authority_level": authority[skill_name],
                    "status": "blocked"
                    if spec.locked or not spec.enabled
                    else "planned",
                    "purpose": self._skill_purpose(skill_name),
                    "handoff": self._handoff(plan[index - 2], skill_name)
                    if index > 1
                    else "start",
                    "blocked_reason": blocked_reason,
                }
            )
        return trace

    def _resolve_plan(
        self,
        intent_name: str,
        request: CopilotRequest,
        plans: dict[str, list[str]],
    ) -> list[str]:
        if intent_name != "report_write":
            return plans.get(intent_name, plans["copilot_chat"])
        message = request.message
        lower = message.lower()
        if (
            any(word in message for word in ["盯盘", "异动", "提醒"])
            or "monitor" in lower
        ):
            return ["stock-monitor", "report-writer"]
        if any(word in message for word in ["回测", "策略"]) or any(
            word in lower for word in ["backtest", "strategy"]
        ):
            return ["strategy-analyst", "report-writer"]
        if any(word in message for word in ["风险", "风控", "集中度"]):
            return ["stock-researcher", "risk-officer", "report-writer"]
        return ["stock-researcher", "report-writer"]

    def _suggest_actions(
        self,
        *,
        page: str,
        symbol: str | None,
        context: dict[str, Any],
        skill_trace: list[dict[str, Any]],
        last_report_result: dict[str, Any] | None,
        last_draft_result: dict[str, Any] | None,
        last_review_result: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []

        if symbol:
            summary = context.get("symbol_summary") or {}
            relation = summary.get("relation") or {}
            in_watchlist = relation.get("in_watchlist", False)
            in_holdings = relation.get("in_holdings", False)

            if not in_watchlist:
                actions.append(
                    {
                        "label": "加入自选",
                        "icon": "⭐",
                        "action_type": "api",
                        "endpoint": "watchlist",
                        "symbol": symbol,
                    }
                )
            else:
                actions.append(
                    {
                        "label": "移除自选",
                        "icon": "✕",
                        "action_type": "api",
                        "endpoint": "watchlist_remove",
                        "symbol": symbol,
                    }
                )
            if not in_holdings:
                actions.append(
                    {
                        "label": "加仓",
                        "icon": "💰",
                        "action_type": "navigate",
                        "screen": "research",
                        "stock": symbol,
                    }
                )
            actions.append(
                {
                    "label": "深度研究",
                    "icon": "🔍",
                    "action_type": "navigate",
                    "screen": "research",
                    "stock": symbol,
                }
            )

        if page != "holdings":
            actions.append(
                {
                    "label": "持仓",
                    "icon": "💼",
                    "action_type": "navigate",
                    "screen": "holdings",
                }
            )
        if page != "monitor":
            actions.append(
                {
                    "label": "盯盘",
                    "icon": "👁",
                    "action_type": "navigate",
                    "screen": "monitor",
                }
            )

        if last_report_result:
            actions.append(
                {
                    "label": "查看报告",
                    "icon": "📄",
                    "action_type": "navigate",
                    "screen": "reports",
                }
            )
        if last_draft_result:
            actions.append(
                {
                    "label": "查看草案",
                    "icon": "📝",
                    "action_type": "navigate",
                    "screen": "holdings",
                }
            )
        if last_review_result:
            actions.append(
                {
                    "label": "查看审查",
                    "icon": "🛡",
                    "action_type": "navigate",
                    "screen": "holdings",
                }
            )

        seen: set[tuple[str, str]] = set()
        deduped = [
            a
            for a in actions
            if (key := (a["label"], a.get("screen", "") or a.get("endpoint", "")))
            not in seen
            and not seen.add(key)
        ]
        return deduped[:5]

    def _skill_purpose(self, skill_name: str) -> str:
        return {
            "stock-researcher": "读取个股上下文、行情、历史和情报证据",
            "stock-monitor": "解释盯盘事件和规则触发原因",
            "risk-officer": "评估持仓集中度和组合风险",
            "strategy-analyst": "读取策略库并执行只读回测，输出策略快照和研究结论",
            "rebalance-planner": "生成调仓方案和拟单草案，不执行真实交易",
            "report-writer": "汇总结论、证据、反对理由和风险提示",
            "execution-agent-disabled": "V1 真实交易执行关闭，仅保留阻断占位",
        }[skill_name]

    def _handoff(self, previous: str, current: str) -> str:
        return f"{previous} -> {current}"

    def _evidence_refs(
        self, skill_trace: list[dict[str, Any]], context: Dict[str, Any]
    ) -> list[str]:
        refs = ["intent_router", "skill_registry"]
        if context:
            refs.extend(["copilot_context_builder", "provider_router"])
        risk_only = len(skill_trace) == 1 and skill_trace[0]["skill"] == "risk-officer"
        if risk_only:
            refs.extend(
                ["decision_journal_entry", "paper_order", "paper_portfolio_snapshot"]
            )
        elif any(item["skill"] == "risk-officer" for item in skill_trace):
            refs.append("portfolio_risk")
        if any(item["skill"] == "strategy-analyst" for item in skill_trace):
            refs.extend(["strategy_spec", "backtest_run", "research_only"])
        if any(item["skill"] == "rebalance-planner" for item in skill_trace):
            refs.extend(
                [
                    "draft_order_guard:auto_trade_false",
                    "auto_trade_false",
                    "pre_trade_review",
                ]
            )
        if (
            skill_trace
            and skill_trace[0]["skill"] == "risk-officer"
            and len(skill_trace) == 1
        ):
            refs.append("review_inbox_state")
        return refs

    def _update_task_step(
        self, task_id: str, current_step: str, progress: int, status: str | None = None
    ) -> None:
        try:
            self.task_service.update(
                task_id, status=status, progress=progress, current_step=current_step
            )
        except KeyError:
            return

    def _upsert_run_log(
        self,
        run_id: str,
        *,
        status: str,
        error_category: str | None = None,
        runtime_error: str | None = None,
        tool_call_count: int | None = None,
        usage_input_tokens: int | None = None,
        usage_output_tokens: int | None = None,
        cost: float | None = None,
        latency_ms: float | None = None,
    ) -> None:
        existing = self.runtime_observer.get_copilot_run_log(run_id)
        if not existing:
            return
        cost_val = cost if cost is not None else existing.cost
        if cost_val is None and (
            usage_input_tokens is not None or existing.usage_input_tokens is not None
        ):
            inp = (
                usage_input_tokens
                if usage_input_tokens is not None
                else existing.usage_input_tokens
            )
            out = (
                usage_output_tokens
                if usage_output_tokens is not None
                else existing.usage_output_tokens
            )
            cost_val = _estimate_cost(inp or 0, out or 0, existing.model_name)
        updated = existing.model_copy(
            update={
                "status": status,
                "error_category": error_category,
                "runtime_error": runtime_error,
                "tool_call_count": tool_call_count
                if tool_call_count is not None
                else existing.tool_call_count,
                "usage_input_tokens": usage_input_tokens
                if usage_input_tokens is not None
                else existing.usage_input_tokens,
                "usage_output_tokens": usage_output_tokens
                if usage_output_tokens is not None
                else existing.usage_output_tokens,
                "cost": cost_val,
                "latency_ms": latency_ms
                if latency_ms is not None
                else existing.latency_ms,
                "updated_at": now_iso(),
            }
        )
        self.runtime_observer.save_copilot_run_log(updated)
