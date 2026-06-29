# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single-user, locally-run AI investment workbench. A FastAPI backend exposes an AI Copilot (built on ByteDance's DeerFlow agent runtime) plus stock research, watchlist/holdings, monitoring/alerts, strategy backtesting, risk control, paper trading, and reporting. A React 19 + Vite frontend (a fixed-rail multi-page SPA) consumes the REST API and an SSE stream. Persistence is a single local SQLite file. Most of the docs and product surface are in Chinese.

## Commands

```bash
# Single entry point — runs backend on :6666 + frontend on :8888 (loads .env, sets AI defaults).
# Flags: --dev (backend hot reload), --backend-only, --frontend-only, --port PORT. Safe under `sh start.sh` (re-execs with bash).
./start.sh
./scripts/dev.sh   # thin shim, equivalent to `./start.sh --dev`

# Backend only (manual)
uv run uvicorn backend.app:app --host 0.0.0.0 --port 6666

# Frontend only (manual) — Vite proxies /api -> 127.0.0.1:6666
cd frontend && npm run dev

# Backend tests (pytest is configured with --assert=plain; testpaths=tests)
uv run pytest
uv run pytest tests/test_copilot_context_builder.py            # single file
uv run pytest tests/test_services.py::test_name                # single test
uv run pytest -m ai_regression                                 # marked deterministic AI checks
uv run pytest -m deerflow                                       # optional real embedded DeerFlow smoke

# Frontend
cd frontend && npm run lint        # eslint
cd frontend && npm test            # vitest run
cd frontend && npm run test:e2e    # playwright
cd frontend && npm run build       # tsc -b && vite build -> frontend/dist

# AI regression / smoke scripts
python scripts/run_ai_regression.py
python scripts/deerflow_smoke.py
python scripts/closed_loop_smoke.py
```

Frontend is **8888** (matching `vite.config.ts`), backend is **6666** — for both `./start.sh` and the `./scripts/dev.sh` shim. When `frontend/dist` exists the backend serves the built SPA at `/app` and mounts it at `/`.

## Architecture

Request flow: **React pages → REST `/api/*` + SSE → FastAPI routers (`backend/api/routes_*.py`) → app services (`backend/app_services/`) → either the stock domain layer or the agent runtime → SQLite via `WorkbenchRepository`.**

### Dependency injection / wiring
- `backend/bootstrap.py::create_services()` is the single composition root. It constructs every service in dependency order, wires the `WorkbenchToolBridge`, builds the `CopilotService`, and returns an `AppServices` dataclass. **Add new services and their dependencies here.**
- `backend/app.py::create_app()` calls `create_services()`, stores it on `app.state.services`, registers all routers, and serves the SPA. Routers reach services via `backend/api/deps.py`.
- Bootstrap also performs first-run data seeding: auto-imports A-share / HK / US stock master lists from AKShare when the master table is empty, and kicks off background cache warmups. This only runs when the primary provider is available. The network-dependent seeding/warmup is isolated in `bootstrap._seed_market_data()`; set `WORKBENCH_SKIP_SEED=1` to skip it for a fast, offline boot (recommended for tests/CI).

### Agent runtime (`backend/agent_runtime/`)
- `DeerFlowClientAdapter` (`deerflow_client.py`) is the boundary around DeerFlow. It is deliberately **copyright-safe**: it maps LangGraph-style stream events through `DeerFlowEventMapper` without importing DeerFlow internals, so tests can feed plain dicts/objects.
- Runtime mode is selected by `DeerFlowClientAdapter.from_env()` via env vars, with fallback **direct → embedded → stub**:
  - `WORKBENCH_AI_MODE=direct` — generates DeerFlow config on the fly from `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `WORKBENCH_AI_MODEL`. This is the default set by `start.sh` because it needs no pre-existing config files.
  - `embedded` — uses a real embedded DeerFlow graph (auto-upgrades to direct when prerequisites are met).
  - `stub` — final fallback; no real model calls. Tests run in stub mode.
  - Check `/api/health` to see the resolved `active_client` and degraded state.
- `tool_bridge.py` (`WorkbenchToolBridge`) is the seam between agent tool calls and app services. `tools.py::init_workbench_tools(bridge)` registers the LangChain `StructuredTool`s the agent can call; `get_all_workbench_tools()` lists them.
- `skill_registry.py` loads AI "skills" (multi-step agent playbooks). Skills live in `skills/custom/<name>/SKILL.md` and are enabled/disabled in `extensions_config.json`.

### Stock domain (`backend/stock_domain/`)
- `provider_router.py` (singleton `provider_router`) routes market-data requests across multiple providers with automatic degradation (AKShare/YFinance/EastMoney/Sina/Mock). It owns caching (`provider_cache.py`) and background refresh.
- `*_tools.py` modules (`backtest_tools`, `risk_tools`, `portfolio_tools`, `quote_tools`, `history_tools`, `financial_tools`, `intel_tools`, `monitor_tools`, `report_tools`, `catalog_tools`) implement the actual domain logic invoked by both services and the tool bridge.

### Persistence (`backend/persistence/`)
- `db.py::connect()` opens the SQLite file (default `data/workbench.sqlite3`); `WorkbenchRepository` (`repositories.py`) is the only data-access surface and calls `seed_defaults()` on startup. `file_store.py` handles generated report/artifact files under `data/files`.
- `WorkbenchRepository` composes per-domain mixins (`repo_catalog`, `repo_copilot`, `repo_monitor`, `repo_strategy`, `repo_risk`, `repo_trading`, `repo_reports`, `repo_config`); shared JSON helpers live in `repo_base.py`. The core class keeps only `__init__` + seeding. **Add a new query method to the matching domain mixin, not the core class.**
- Config (runtime settings, data sources, intel sources, enabled skills) is stored as JSON rows via `repo.get_config(key, default)` rather than env/files.

### Frontend (`frontend/src/`)
- `api/client.ts` is the single fetch wrapper; all calls go through `/api/*`. `api/copilot.ts` handles the SSE stream endpoint.
- Pages in `pages/` map 1:1 to the left nav. `ScreenRenderer.tsx` registers/routes screens; `components/layout/Rail.tsx` is the nav rail; screen types live in `types/`.

## Conventions

- Backend is dependency-injected throughout — **never instantiate services directly**; thread them through `bootstrap.py` and reach them via `app.state.services` / `deps.py`.
- New agent tools require three coordinated edits: define in `agent_runtime/tools.py`, expose the method on `WorkbenchToolBridge` (`tool_bridge.py`), implement domain logic in `stock_domain/` or an app service.
- New page: create in `pages/`, add the screen type in `types/`, register in `ScreenRenderer.tsx`, add nav entry in `Rail.tsx`.
- Keep the DeerFlow boundary copyright-safe: do not import DeerFlow internals outside the adapter; map events through `DeerFlowEventMapper`.
- `CopilotService` (`copilot_service.py`) is the streaming orchestrator; its self-independent helpers are factored out into `copilot_cost.py` (token-cost estimation), `copilot_session_state.py` (`TurnSummary` / `SessionStateData` multi-turn memory), and `copilot_errors.py` (error categorization/hints). Put new pure helpers there, not on the service class.

## Reference docs

Design/architecture deep-dives live in `doc/` (e.g. `ARCHITECTURE_ANALYSIS.md`, `AI_CHAT_ARCHITECTURE.md`, `SKILL_SYSTEM.md`, `TOOL_DEEP_BINDING.md`, `BACKTEST_STANDARDS.md`, `data_cache_strategy.md`). Integration how-tos are in `docs/` (`ADD_DATA_SOURCE.md`, `IM_CHANNEL_INTEGRATION.md`).
