"""Industry-dimension domain tools (行业格局).

两个入口：
- ``sync_industry_mapping``：东财行业板块 → 成分股反向索引，回填 stock_master
  的 industry 列（P0-A）。bootstrap 播种在后台线程调用；TTL 内幂等跳过。
- ``get_industry_context``：行业快照 + 个股行业内分位 + Top10 成分股（P0-B），
  供 agent 工具与服务层调用。

数据源仅覆盖 A 股（东财行业板块）；港/美股一律返回 degraded 说明，由 skill
层降级为「行业标签 + web 搜索」。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.providers import AkShareMarketDataProvider

_log = logging.getLogger("industry_tools")

_SYNC_CONFIG_KEY = "industry_mapping_sync"
_SYNC_TTL_SECONDS = 7 * 24 * 3600  # 行业成分月度级变动，7 天刷新足够

# 行业成分股请求级缓存（进程内）：{industry: (fetched_at, rows)}
_CONS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_BOARDS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_LIVE_CACHE_TTL = 600.0  # 行情快照 10 分钟


def _akshare_primary() -> AkShareMarketDataProvider | None:
    primary = provider_router.primary
    return primary if isinstance(primary, AkShareMarketDataProvider) else None


def _cached_boards() -> list[dict[str, Any]]:
    hit = _BOARDS_CACHE.get("boards")
    if hit and time.time() - hit[0] < _LIVE_CACHE_TTL:
        return hit[1]
    primary = _akshare_primary()
    if primary is None:
        return []
    boards = primary.fetch_industry_boards()
    if boards:
        _BOARDS_CACHE["boards"] = (time.time(), boards)
    return boards


def _cached_constituents(industry: str) -> list[dict[str, Any]]:
    hit = _CONS_CACHE.get(industry)
    if hit and time.time() - hit[0] < _LIVE_CACHE_TTL:
        return hit[1]
    primary = _akshare_primary()
    if primary is None:
        return []
    rows = primary.fetch_industry_constituents(industry)
    if rows:
        _CONS_CACHE[industry] = (time.time(), rows)
    return rows


_INDUSTRY_SUFFIXES = ("行业", "板块", "概念", "指数")


def resolve_industry_name(requested: str, board_names: list[str]) -> str | None:
    """Map free-form industry labels onto Eastmoney board names.

    Agents often pass「化学制药」while the board list may use a near-synonym or
    a longer title. Exact match first; then suffix strip; then unique substring.
    """
    q = (requested or "").strip()
    if not q:
        return None
    names = [n for n in board_names if n]
    if q in names:
        return q
    candidates = [q]
    for suffix in _INDUSTRY_SUFFIXES:
        if q.endswith(suffix) and len(q) > len(suffix):
            candidates.append(q[: -len(suffix)])
        else:
            candidates.append(q + suffix)
    for cand in candidates:
        if cand in names:
            return cand
    hits = [n for n in names if any(c and (c in n or n in c) for c in candidates)]
    # Prefer unique tight matches; if multiple, shortest absolute length delta.
    uniq = list(dict.fromkeys(hits))
    if not uniq:
        return None
    if len(uniq) == 1:
        return uniq[0]
    uniq.sort(key=lambda n: (abs(len(n) - len(q)), len(n)))
    return uniq[0]


def sync_industry_mapping(*, force: bool = False) -> dict[str, Any]:
    """行业→成分股反向索引回填 stock_master.industry（仅 A 股）。

    约 86 个行业 × 1 次成分股请求；只在 TTL 过期或 force 时全量执行。
    """
    repo = provider_router.repo
    if repo is None:
        return {"ok": False, "error": "repository not initialized"}
    primary = _akshare_primary()
    if primary is None:
        return {"ok": False, "error": "primary provider is not AkShare"}

    state = repo.get_config(_SYNC_CONFIG_KEY, {})
    synced_at = float(state.get("synced_at") or 0)
    if not force and time.time() - synced_at < _SYNC_TTL_SECONDS:
        return {
            "ok": True,
            "skipped": True,
            "reason": "within TTL",
            "synced_at": state.get("synced_at_iso"),
            "mapped": state.get("mapped", 0),
        }

    boards = primary.fetch_industry_boards()
    if not boards:
        return {"ok": False, "error": "no industry boards returned from AKShare"}

    mapping: dict[str, str] = {}
    failed_boards: list[str] = []
    for board in boards:
        industry = board["industry"]
        rows = primary.fetch_industry_constituents(industry)
        if not rows:
            failed_boards.append(industry)
            continue
        for row in rows:
            mapping[row["symbol"]] = industry

    if not mapping:
        return {"ok": False, "error": "all constituent fetches failed", "failed_boards": len(failed_boards)}

    updated = repo.batch_update_stock_master_industry(mapping)
    from backend.schemas import now_iso

    repo.set_config(
        _SYNC_CONFIG_KEY,
        {
            "synced_at": time.time(),
            "synced_at_iso": now_iso(),
            "boards": len(boards),
            "mapped": len(mapping),
            "updated": updated,
            "failed_boards": failed_boards,
        },
    )
    _log.info(
        "industry mapping synced: %d boards, %d symbols mapped, %d rows updated, %d boards failed",
        len(boards), len(mapping), updated, len(failed_boards),
    )
    return {
        "ok": True,
        "boards": len(boards),
        "mapped": len(mapping),
        "updated": updated,
        "failed_boards": len(failed_boards),
    }


def _percentile(values: list[float], target: float) -> float | None:
    """target 在 values 中的分位（0-100，越大越靠前不预设方向，纯位置）。"""
    pool = [v for v in values if v is not None]
    if not pool or target is None:
        return None
    below = sum(1 for v in pool if v <= target)
    return round(below / len(pool) * 100, 1)


def _median(values: list[float]) -> float | None:
    pool = sorted(v for v in values if v is not None)
    if not pool:
        return None
    mid = len(pool) // 2
    return pool[mid] if len(pool) % 2 else round((pool[mid - 1] + pool[mid]) / 2, 4)


def get_industry_context(
    symbol: str | None = None, industry: str | None = None
) -> dict[str, Any]:
    """行业快照 + 个股行业内分位 + Top10 成分股。

    输入 symbol（自动解析所属行业）或 industry 名称二选一。
    A 股以外/行业未知时返回 degraded=True + 明确原因，不编数据。
    """
    repo = provider_router.repo
    resolved_symbol = (symbol or "").strip().upper() or None
    resolved_industry = (industry or "").strip() or None
    recovery_hint = (
        "请先导入 A 股主表（设置/API：POST /api/stock/import-a-share）并等待行业映射同步；"
        "或改用东财精确板块名调用 get_industry_context(industry=…)。"
    )

    if resolved_symbol and not resolved_industry:
        master = repo.get_stock_master(resolved_symbol) if repo else None
        if master is None:
            cn_count = repo.count_stock_master(market="CN") if repo else 0
            return {
                "degraded": True,
                "reason": (
                    f"{resolved_symbol} 不在股票主表中"
                    + (f"（当前 A 股主表仅 {cn_count} 条，疑似未全量导入）" if cn_count < 500 else "")
                ),
                "symbol": resolved_symbol,
                "recovery_hint": recovery_hint,
            }
        if master.market != "CN":
            return {
                "degraded": True,
                "reason": f"行业排名数据源仅覆盖 A 股（{resolved_symbol} 市场为 {master.market}）；请改用 web_search 检索行业格局",
                "symbol": resolved_symbol,
                "industry": master.industry or None,
            }
        if not master.industry:
            return {
                "degraded": True,
                "reason": "该股票行业映射尚未回填（首次同步在启动后后台执行，约需数分钟）",
                "symbol": resolved_symbol,
                "recovery_hint": "等待 industry mapping 同步完成，或显式传入 industry=东财板块名重试。",
            }
        resolved_industry = master.industry

    if not resolved_industry:
        return {"degraded": True, "reason": "需要提供 symbol 或 industry 之一"}

    boards = _cached_boards()
    board_names = [b["industry"] for b in boards if b.get("industry")]
    matched = resolve_industry_name(resolved_industry, board_names)
    if matched and matched != resolved_industry:
        _log.info("industry name resolved: %r → %r", resolved_industry, matched)
        resolved_industry = matched

    board = next((b for b in boards if b["industry"] == resolved_industry), None)
    constituents = _cached_constituents(resolved_industry) if resolved_industry else []
    if not constituents:
        sample = board_names[:20]
        # Prefer samples that share characters with the query for agent retry.
        related = [n for n in board_names if any(ch in n for ch in resolved_industry[:2])][:10]
        return {
            "degraded": True,
            "reason": (
                f"行业「{resolved_industry}」成分股数据获取失败"
                f"（数据源不可用或行业名不存在；已尝试模糊匹配）"
                + ("；当前东财行业板块列表也为空，多为网络被掐" if not board_names else "")
            ),
            "industry": resolved_industry,
            "available_industries_sample": related or sample,
            "recovery_hint": (
                "从 available_industries_sample 选精确东财板块名重试；"
                "勿用口语别名硬猜。主表过薄时先导入 A 股主表。"
                "若 sample 为空：东财行业接口暂不可用，可稍后重试或改用 web_search 并标精度有限。"
            ),
        }

    result: dict[str, Any] = {
        "degraded": False,
        "industry": resolved_industry,
        "company_count": len(constituents),
        "snapshot": {
            "change_pct": board.get("change_pct") if board else None,
            "turnover_pct": board.get("turnover_pct") if board else None,
            "total_market_cap": board.get("total_market_cap") if board else None,
            "rank_among_industries": board.get("rank") if board else None,
            "industry_total": len(boards) or None,
        },
        "valuation": {
            "pe_median": _median([c["pe"] for c in constituents]),
            "pb_median": _median([c["pb"] for c in constituents]),
        },
        # cap_est = 成交额/换手率 推算的流通市值，仅用于行业内相对排序
        "cap_note": "市值为推算口径（成交额/换手率），仅用于行业内相对排序",
        "top_constituents": [
            {k: c[k] for k in ("symbol", "name", "price", "change_pct", "pe", "pb")}
            for c in sorted(
                constituents,
                key=lambda c: c["cap_est"] or 0,
                reverse=True,
            )[:10]
        ],
    }

    if resolved_symbol:
        target = next((c for c in constituents if c["symbol"] == resolved_symbol), None)
        if target is None:
            result["target"] = {
                "symbol": resolved_symbol,
                "note": "该股票不在此行业成分股列表中（可能行业映射过期）",
            }
        else:
            ranked = sorted(
                (c for c in constituents if c["cap_est"] is not None),
                key=lambda c: c["cap_est"],
                reverse=True,
            )
            cap_rank = next(
                (i + 1 for i, c in enumerate(ranked) if c["symbol"] == resolved_symbol),
                None,
            )
            result["target"] = {
                "symbol": resolved_symbol,
                "name": target["name"],
                "price": target["price"],
                "change_pct": target["change_pct"],
                "pe": target["pe"],
                "pb": target["pb"],
                "cap_rank": cap_rank,
                "cap_rank_total": len(ranked) or None,
                "pe_percentile": _percentile([c["pe"] for c in constituents], target["pe"]),
                "pb_percentile": _percentile([c["pb"] for c in constituents], target["pb"]),
                "change_pct_percentile": _percentile(
                    [c["change_pct"] for c in constituents], target["change_pct"]
                ),
            }
    return result
