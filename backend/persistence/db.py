from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


SCHEMA: Iterable[str] = (
    """
    CREATE TABLE IF NOT EXISTS watchlist_item (
      symbol TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      group_name TEXT NOT NULL,
      tags TEXT NOT NULL,
      monitored INTEGER NOT NULL,
      position INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist_group (
      name TEXT PRIMARY KEY,
      color TEXT NOT NULL DEFAULT '#6366f1',
      sort_order INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS holding_position (
      symbol TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      quantity REAL NOT NULL,
      market_value REAL NOT NULL,
      weight_pct REAL NOT NULL,
      cost REAL,
      pnl_pct REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monitor_event (
      event_id TEXT PRIMARY KEY,
      rule_id TEXT,
      rule_type TEXT,
      symbol TEXT,
      source TEXT,
      severity TEXT,
      title TEXT,
      trigger_rule TEXT,
      dedupe_key TEXT,
      triggered_at TEXT,
      cooldown_until TEXT,
      evidence_json TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monitor_rule (
      rule_id TEXT PRIMARY KEY,
      symbol TEXT,
      rule_type TEXT NOT NULL,
      severity TEXT NOT NULL,
      title TEXT,
      trigger_rule TEXT,
      cooldown_seconds INTEGER NOT NULL,
      enabled INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monitor_status (
      status_key TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_task (
      task_id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report (
      report_id TEXT PRIMARY KEY,
      report_type TEXT NOT NULL DEFAULT '',
      source_type TEXT NOT NULL DEFAULT '',
      source_id TEXT NOT NULL DEFAULT '',
      symbol TEXT NOT NULL DEFAULT '',
      quality_status TEXT,
      latest_quality_check_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_template (
      template_id TEXT PRIMARY KEY,
      report_type TEXT NOT NULL,
      visible INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_quality_check (
      check_id TEXT PRIMARY KEY,
      report_id TEXT NOT NULL,
      template_id TEXT,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
      audit_id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_execution (
      execution_id TEXT PRIMARY KEY,
      task_id TEXT,
      run_id TEXT,
      call_id TEXT,
      tool TEXT NOT NULL,
      domain TEXT NOT NULL,
      status TEXT NOT NULL,
      authority_level TEXT NOT NULL,
      arguments TEXT NOT NULL,
      source_mode TEXT NOT NULL,
      evidence_refs TEXT NOT NULL,
      result_summary TEXT NOT NULL,
      error TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_call_log (
      call_id TEXT PRIMARY KEY,
      capability TEXT NOT NULL,
      market TEXT,
      symbol TEXT,
      provider TEXT NOT NULL,
      fallback_provider TEXT NOT NULL,
      status TEXT NOT NULL,
      degraded_reason TEXT,
      duration_ms REAL NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS copilot_run_log (
      run_id TEXT PRIMARY KEY,
      session_id TEXT,
      task_id TEXT,
      mode TEXT NOT NULL,
      active_client TEXT NOT NULL,
      model_name TEXT,
      status TEXT NOT NULL,
      error_category TEXT,
      runtime_error TEXT,
      tool_call_count INTEGER NOT NULL,
      usage_input_tokens INTEGER,
      usage_output_tokens INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_metric_snapshot (
      snapshot_id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rebalance_draft (
      draft_id TEXT PRIMARY KEY,
      symbol TEXT NOT NULL,
      status TEXT NOT NULL,
      authority_level TEXT NOT NULL,
      target_weight_pct REAL NOT NULL,
      valid_until TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pre_trade_review (
      review_id TEXT PRIMARY KEY,
      source_draft_id TEXT NOT NULL,
      symbol TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_order (
      order_id TEXT PRIMARY KEY,
      review_id TEXT NOT NULL,
      source_draft_id TEXT NOT NULL,
      symbol TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_portfolio_snapshot (
      snapshot_id TEXT PRIMARY KEY,
      baseline_id TEXT NOT NULL,
      as_of TEXT NOT NULL,
      degraded INTEGER NOT NULL,
      market_value REAL NOT NULL,
      cash_estimate REAL NOT NULL,
      equity_estimate REAL NOT NULL,
      pnl_estimate REAL NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_journal_entry (
      entry_id TEXT PRIMARY KEY,
      decision_id TEXT NOT NULL,
      draft_id TEXT,
      review_id TEXT,
      paper_order_id TEXT,
      snapshot_id TEXT,
      report_id TEXT,
      symbol TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT '',
      source_type TEXT NOT NULL DEFAULT '',
      closed_at TEXT,
      close_note TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS strategy_spec (
      strategy_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      strategy_type TEXT NOT NULL,
      enabled INTEGER NOT NULL,
      risk_level TEXT NOT NULL,
      tags TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_run (
      run_id TEXT PRIMARY KEY,
      strategy_id TEXT NOT NULL,
      strategy_name TEXT NOT NULL,
      strategy_type TEXT NOT NULL,
      degraded INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_policy (
      policy_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      is_active INTEGER NOT NULL,
      is_default INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_config (
      key TEXT PRIMARY KEY,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_inbox_state (
      item_key TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      snoozed_until TEXT,
      note TEXT,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS copilot_session (
      session_id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      current_page TEXT NOT NULL,
      anchor_symbol TEXT,
      authority_level TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      last_message_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS copilot_message (
      message_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      role TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      page TEXT,
      symbol TEXT,
      run_id TEXT,
      task_id TEXT,
      client_message_id TEXT,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES copilot_session(session_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_master (
      symbol TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      market TEXT NOT NULL,
      industry TEXT DEFAULT '',
      sector TEXT DEFAULT '',
      aliases TEXT DEFAULT '[]',
      is_active INTEGER DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_daily (
      symbol TEXT NOT NULL,
      trade_date TEXT NOT NULL,
      open REAL DEFAULT 0.0,
      high REAL DEFAULT 0.0,
      low REAL DEFAULT 0.0,
      close REAL DEFAULT 0.0,
      volume REAL DEFAULT 0.0,
      amount REAL DEFAULT 0.0,
      source TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      PRIMARY KEY (symbol, trade_date)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol ON stock_daily(symbol)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_stock_daily_trade_date ON stock_daily(trade_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_quote (
      symbol TEXT PRIMARY KEY,
      last REAL DEFAULT 0.0,
      change_pct REAL DEFAULT 0.0,
      volume REAL DEFAULT 0.0,
      amount REAL DEFAULT 0.0,
      source TEXT DEFAULT '',
      provider TEXT DEFAULT '',
      hit_count INTEGER DEFAULT 0,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_financial (
      symbol TEXT NOT NULL,
      report_date TEXT NOT NULL,
      report_type TEXT NOT NULL DEFAULT 'annual',
      revenue REAL DEFAULT 0.0,
      profit REAL DEFAULT 0.0,
      total_assets REAL DEFAULT 0.0,
      total_liabilities REAL DEFAULT 0.0,
      payload TEXT DEFAULT '{}',
      created_at TEXT NOT NULL,
      PRIMARY KEY (symbol, report_date, report_type)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_stock_financial_symbol ON stock_financial(symbol)
    """,
    """
    CREATE TABLE IF NOT EXISTS capability_cache (
      capability TEXT NOT NULL,
      symbol TEXT NOT NULL DEFAULT '',
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY (capability, symbol)
    )
    """,
)


def connect(db_path: str | Path = "data/workbench.sqlite3") -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    initialize(conn)
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        conn.execute(statement)
    _ensure_monitor_event_columns(conn)
    _ensure_tool_execution_columns(conn)
    _ensure_rebalance_draft_columns(conn)
    _ensure_pre_trade_review_columns(conn)
    _ensure_paper_order_columns(conn)
    _ensure_paper_portfolio_snapshot_columns(conn)
    _ensure_decision_journal_entry_columns(conn)
    _ensure_strategy_spec_columns(conn)
    _ensure_backtest_run_columns(conn)
    _ensure_risk_policy_columns(conn)
    _ensure_report_columns(conn)
    _ensure_report_template_columns(conn)
    _ensure_report_quality_check_columns(conn)
    _ensure_review_inbox_state_columns(conn)
    _ensure_copilot_run_log_columns(conn)
    _ensure_stock_quote_columns(conn)
    conn.commit()


def _ensure_monitor_event_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(monitor_event)").fetchall()
    }
    expected = {
        "rule_id": "TEXT",
        "rule_type": "TEXT",
        "symbol": "TEXT",
        "source": "TEXT",
        "severity": "TEXT",
        "title": "TEXT",
        "trigger_rule": "TEXT",
        "dedupe_key": "TEXT",
        "triggered_at": "TEXT",
        "cooldown_until": "TEXT",
        "evidence_json": "TEXT",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE monitor_event ADD COLUMN {name} {column_type}")


def _ensure_tool_execution_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(tool_execution)").fetchall()
    }
    if "domain" not in columns:
        conn.execute(
            "ALTER TABLE tool_execution ADD COLUMN domain TEXT NOT NULL DEFAULT 'unknown'"
        )
    if "arguments" not in columns:
        conn.execute(
            "ALTER TABLE tool_execution ADD COLUMN arguments TEXT NOT NULL DEFAULT '{}'"
        )


def _ensure_rebalance_draft_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(rebalance_draft)").fetchall()
    }
    expected = {
        "symbol": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'pending_user_confirmation'",
        "authority_level": "TEXT NOT NULL DEFAULT 'A4'",
        "target_weight_pct": "REAL NOT NULL DEFAULT 0",
        "valid_until": "TEXT NOT NULL DEFAULT ''",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE rebalance_draft ADD COLUMN {name} {column_type}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rebalance_draft_symbol ON rebalance_draft(symbol)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rebalance_draft_status ON rebalance_draft(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rebalance_draft_valid_until ON rebalance_draft(valid_until)"
    )


def _ensure_pre_trade_review_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(pre_trade_review)").fetchall()
    }
    expected = {
        "source_draft_id": "TEXT NOT NULL DEFAULT ''",
        "symbol": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'blocked'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE pre_trade_review ADD COLUMN {name} {column_type}"
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pre_trade_review_draft ON pre_trade_review(source_draft_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pre_trade_review_symbol ON pre_trade_review(symbol)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pre_trade_review_status ON pre_trade_review(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pre_trade_review_created_at ON pre_trade_review(created_at)"
    )


def _ensure_paper_order_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(paper_order)").fetchall()
    }
    expected = {
        "review_id": "TEXT NOT NULL DEFAULT ''",
        "source_draft_id": "TEXT NOT NULL DEFAULT ''",
        "symbol": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'paper_submitted'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE paper_order ADD COLUMN {name} {column_type}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_order_review ON paper_order(review_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_order_draft ON paper_order(source_draft_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_order_symbol ON paper_order(symbol)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_order_status ON paper_order(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_order_created_at ON paper_order(created_at)"
    )


def _ensure_paper_portfolio_snapshot_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute(
            "PRAGMA table_info(paper_portfolio_snapshot)"
        ).fetchall()
    }
    expected = {
        "baseline_id": "TEXT NOT NULL DEFAULT ''",
        "as_of": "TEXT NOT NULL DEFAULT ''",
        "degraded": "INTEGER NOT NULL DEFAULT 0",
        "market_value": "REAL NOT NULL DEFAULT 0",
        "cash_estimate": "REAL NOT NULL DEFAULT 0",
        "equity_estimate": "REAL NOT NULL DEFAULT 0",
        "pnl_estimate": "REAL NOT NULL DEFAULT 0",
        "created_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE paper_portfolio_snapshot ADD COLUMN {name} {column_type}"
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_portfolio_snapshot_baseline "
        "ON paper_portfolio_snapshot(baseline_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_portfolio_snapshot_asof "
        "ON paper_portfolio_snapshot(as_of)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_portfolio_snapshot_created_at "
        "ON paper_portfolio_snapshot(created_at)"
    )


def _ensure_decision_journal_entry_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(decision_journal_entry)").fetchall()
    }
    expected = {
        "decision_id": "TEXT NOT NULL DEFAULT ''",
        "draft_id": "TEXT",
        "review_id": "TEXT",
        "paper_order_id": "TEXT",
        "snapshot_id": "TEXT",
        "report_id": "TEXT",
        "symbol": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT ''",
        "source_type": "TEXT NOT NULL DEFAULT ''",
        "closed_at": "TEXT",
        "close_note": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE decision_journal_entry ADD COLUMN {name} {column_type}"
            )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_journal_entry_decision_id "
        "ON decision_journal_entry(decision_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_journal_entry_draft_id "
        "ON decision_journal_entry(draft_id) WHERE draft_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_journal_entry_review_id "
        "ON decision_journal_entry(review_id) WHERE review_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_journal_entry_paper_order_id "
        "ON decision_journal_entry(paper_order_id) WHERE paper_order_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_journal_entry_snapshot_id "
        "ON decision_journal_entry(snapshot_id) WHERE snapshot_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_journal_entry_report_id "
        "ON decision_journal_entry(report_id) WHERE report_id IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_journal_entry_symbol "
        "ON decision_journal_entry(symbol)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_journal_entry_status "
        "ON decision_journal_entry(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_journal_entry_source_type "
        "ON decision_journal_entry(source_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_journal_entry_updated_at "
        "ON decision_journal_entry(updated_at)"
    )


def _ensure_strategy_spec_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(strategy_spec)").fetchall()
    }
    expected = {
        "name": "TEXT NOT NULL DEFAULT ''",
        "strategy_type": "TEXT NOT NULL DEFAULT 'concentration_control'",
        "enabled": "INTEGER NOT NULL DEFAULT 1",
        "risk_level": "TEXT NOT NULL DEFAULT 'medium'",
        "tags": "TEXT NOT NULL DEFAULT '[]'",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE strategy_spec ADD COLUMN {name} {column_type}")


def _ensure_risk_policy_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(risk_policy)").fetchall()
    }
    expected = {
        "name": "TEXT NOT NULL DEFAULT ''",
        "is_active": "INTEGER NOT NULL DEFAULT 0",
        "is_default": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE risk_policy ADD COLUMN {name} {column_type}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_policy_active ON risk_policy(is_active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_policy_default ON risk_policy(is_default)"
    )


def _ensure_backtest_run_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(backtest_run)").fetchall()
    }
    expected = {
        "strategy_id": "TEXT NOT NULL DEFAULT ''",
        "strategy_name": "TEXT NOT NULL DEFAULT ''",
        "strategy_type": "TEXT NOT NULL DEFAULT 'concentration_control'",
        "degraded": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE backtest_run ADD COLUMN {name} {column_type}")


def _ensure_report_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(report)").fetchall()
    }
    expected = {
        "report_type": "TEXT NOT NULL DEFAULT ''",
        "source_type": "TEXT NOT NULL DEFAULT ''",
        "source_id": "TEXT NOT NULL DEFAULT ''",
        "symbol": "TEXT NOT NULL DEFAULT ''",
        "quality_status": "TEXT",
        "latest_quality_check_id": "TEXT",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE report ADD COLUMN {name} {column_type}")


def _ensure_report_template_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(report_template)").fetchall()
    }
    expected = {
        "report_type": "TEXT NOT NULL DEFAULT ''",
        "visible": "INTEGER NOT NULL DEFAULT 1",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE report_template ADD COLUMN {name} {column_type}")


def _ensure_report_quality_check_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(report_quality_check)").fetchall()
    }
    expected = {
        "report_id": "TEXT NOT NULL DEFAULT ''",
        "template_id": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE report_quality_check ADD COLUMN {name} {column_type}"
            )


def _ensure_copilot_run_log_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(copilot_run_log)").fetchall()
    }
    if "cost" not in columns:
        conn.execute("ALTER TABLE copilot_run_log ADD COLUMN cost REAL")
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE copilot_run_log ADD COLUMN latency_ms REAL")
    if "started_at" not in columns:
        conn.execute("ALTER TABLE copilot_run_log ADD COLUMN started_at TEXT")


def _ensure_stock_quote_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(stock_quote)").fetchall()
    }
    if "provider" not in columns:
        conn.execute("ALTER TABLE stock_quote ADD COLUMN provider TEXT DEFAULT ''")
    if "hit_count" not in columns:
        conn.execute("ALTER TABLE stock_quote ADD COLUMN hit_count INTEGER DEFAULT 0")


def _ensure_review_inbox_state_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(review_inbox_state)").fetchall()
    }
    expected = {
        "item_key": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'open'",
        "snoozed_until": "TEXT",
        "note": "TEXT",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, column_type in expected.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE review_inbox_state ADD COLUMN {name} {column_type}"
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_inbox_state_status ON review_inbox_state(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_inbox_state_snoozed_until ON review_inbox_state(snoozed_until)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_inbox_state_updated_at ON review_inbox_state(updated_at)"
    )
