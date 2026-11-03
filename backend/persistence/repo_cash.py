"""多币种现金桶 + 资金流水。

为什么不再用「一个 config 标量」：钱要能被解释。每次变动写一条 `cash_ledger`，
`cash_bucket` 只是当前余额（写流水时同步更新），这样才能对上账、才能查"这 200 块
去哪了"。

并发/安全：`execute_trade` 在**同一把锁**里完成「校验现金 → 扣款 → 改持仓 → 写流水」，
并且扣款用带条件的 UPDATE（`amount + delta >= 0`），所以不会出现两笔并发买入都扣成功、
或者"持仓写进去了钱没扣"。
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from backend.schemas import now_iso


class InsufficientCash(ValueError):
    def __init__(self, *, currency: str, required: float, available: float):
        self.currency = currency
        self.required = required
        self.available = available
        super().__init__(f"{currency} 可用现金不足：需要 {required:.2f}，可用 {available:.2f}")


class CashNotRecorded(ValueError):
    def __init__(self, *, currency: str):
        self.currency = currency
        super().__init__(f"{currency} 现金未记录：请先设置可用现金")


class InsufficientHolding(ValueError):
    def __init__(self, *, symbol: str, held: float, requested: float):
        self.symbol = symbol
        self.held = held
        self.requested = requested
        super().__init__(f"{symbol} 持仓不足：持有 {held:g}，要卖 {requested:g}")


class CashRepoMixin:
    # ── 读 ──────────────────────────────────────────────────────────────
    def list_cash_buckets(self) -> Dict[str, float]:
        rows = self.conn.execute(
            "SELECT currency, amount FROM cash_bucket ORDER BY currency"
        ).fetchall()
        return {str(row["currency"]).upper(): round(float(row["amount"]), 2) for row in rows}

    def get_cash_bucket(self, currency: str) -> Optional[float]:
        row = self.conn.execute(
            "SELECT amount FROM cash_bucket WHERE currency = ?", (currency.upper(),)
        ).fetchone()
        return None if row is None else round(float(row["amount"]), 2)

    def list_cash_ledger(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM cash_ledger ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(0, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def find_cash_ledger_by_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM cash_ledger WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return dict(row) if row else None

    # ── 写：内部原子工具 ────────────────────────────────────────────────
    def _apply_cash_delta_locked(
        self,
        *,
        currency: str,
        delta: float,
        reason: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        idempotency_key: str | None = None,
        note: str | None = None,
        allow_missing: bool = False,
    ) -> Dict[str, Any]:
        """调用方必须已持有 self._lock。返回 {ledger_id, balance_after, delta}。"""
        ccy = currency.upper()
        amount = round(float(delta), 2)
        if amount == 0:
            balance = self.get_cash_bucket(ccy)
            return {"ledger_id": None, "balance_after": balance, "delta": 0.0}

        existing = self.conn.execute(
            "SELECT amount FROM cash_bucket WHERE currency = ?", (ccy,)
        ).fetchone()
        if existing is None and not allow_missing and amount < 0:
            raise CashNotRecorded(currency=ccy)

        updated = self.conn.execute(
            """
            UPDATE cash_bucket
               SET amount = ROUND(amount + ?, 2), updated_at = ?
             WHERE currency = ? AND amount + ? >= 0
            """,
            (amount, now_iso(), ccy, amount),
        )
        if updated.rowcount == 0:
            row = self.conn.execute(
                "SELECT amount FROM cash_bucket WHERE currency = ?", (ccy,)
            ).fetchone()
            available = round(float(row["amount"]), 2) if row else 0.0
            if row is None and not allow_missing:
                raise CashNotRecorded(currency=ccy)
            raise InsufficientCash(currency=ccy, required=abs(amount), available=available)

        balance = self.get_cash_bucket(ccy) or 0.0
        ledger_id = f"ledger_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            INSERT INTO cash_ledger(
              ledger_id, currency, delta, balance_after, reason,
              ref_type, ref_id, idempotency_key, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ledger_id, ccy, amount, balance, reason,
                ref_type, ref_id, idempotency_key, note, now_iso(),
            ),
        )
        return {"ledger_id": ledger_id, "balance_after": balance, "delta": amount}

    # ── 写：手动校准 ────────────────────────────────────────────────────
    def _write_ledger_locked(
        self, *, currency: str, delta: float, balance_after: float, reason: str,
        ref_type: str | None = None, ref_id: str | None = None,
        idempotency_key: str | None = None, note: str | None = None,
    ) -> str:
        ledger_id = f"ledger_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            INSERT INTO cash_ledger(
              ledger_id, currency, delta, balance_after, reason,
              ref_type, ref_id, idempotency_key, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ledger_id, currency.upper(), round(float(delta), 2), round(float(balance_after), 2),
                reason, ref_type, ref_id, idempotency_key, note, now_iso(),
            ),
        )
        return ledger_id

    def set_cash_bucket(self, currency: str, amount: float | None, *, note: str | None = None) -> Dict[str, Any]:
        """把某个币种的现金设为指定值（写一条 adjust 流水，可解释）。

        `amount=None` 表示"清空记录"（未记录），用于重置。
        """
        ccy = currency.upper()
        with self._lock:
            current = self.get_cash_bucket(ccy)
            if amount is None:
                self.conn.execute("DELETE FROM cash_bucket WHERE currency = ?", (ccy,))
                self.conn.commit()
                return {"currency": ccy, "amount": None, "ledger_id": None}
            target = round(float(amount), 2)
            if target < 0:
                raise ValueError("可用资金不能为负")

            if current is None:
                # 首次记录：直接写入目标值 + 一条 delta=target 的 adjust 流水。
                # 不能再走 _apply_cash_delta_locked（那会把 target 再加一遍）。
                self.conn.execute(
                    "INSERT INTO cash_bucket(currency, amount, updated_at) VALUES (?, ?, ?)",
                    (ccy, target, now_iso()),
                )
                ledger_id = self._write_ledger_locked(
                    currency=ccy, delta=target, balance_after=target,
                    reason="adjust", ref_type="manual", note=note or "set cash",
                )
                self.conn.commit()
                return {"currency": ccy, "ledger_id": ledger_id, "balance_after": target, "delta": target}

            delta = round(target - current, 2)
            if delta == 0:
                return {"currency": ccy, "ledger_id": None, "balance_after": target, "delta": 0.0}
            result = self._apply_cash_delta_locked(
                currency=ccy, delta=delta, reason="adjust",
                ref_type="manual", note=note, allow_missing=True,
            )
            self.conn.commit()
            return {"currency": ccy, **result}

    # ── 写：买入/卖出（原子） ───────────────────────────────────────────
    def execute_trade(
        self,
        *,
        symbol: str,
        name: str,
        quantity: float,
        fill_price: float,
        currency: str,
        is_buy: bool,
        fee: float = 0.0,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> Dict[str, Any]:
        """一笔买入/卖出：现金与持仓在同一事务里改动。

        现金口径：买入 cash_delta = -(fill_price*qty + fee)；卖出 = +(fill_price*qty - fee)。
        幂等：同一个 idempotency_key 重放直接返回上次结果，不会重复扣。
        """
        qty = round(float(quantity), 6)
        price = round(float(fill_price), 6)
        fee_amt = round(float(fee or 0), 2)
        ccy = currency.upper()
        if qty <= 0:
            raise ValueError("数量必须大于 0")
        if price <= 0:
            raise ValueError("成交价必须大于 0")
        if fee_amt < 0:
            raise ValueError("手续费不能为负")

        gross = round(price * qty, 2)
        cash_delta = round(-(gross + fee_amt) if is_buy else (gross - fee_amt), 2)

        with self._lock:
            if idempotency_key:
                replay = self.find_cash_ledger_by_key(idempotency_key)
                if replay:
                    return {
                        "replayed": True,
                        "ledger_id": replay["ledger_id"],
                        "balance_after": replay["balance_after"],
                        "cash_delta": replay["delta"],
                        "currency": replay["currency"],
                        "quantity": qty,
                        "amount": gross,
                        "fee": fee_amt,
                    }

            row = self.conn.execute(
                "SELECT quantity FROM holding_position WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
            held = float(row["quantity"]) if row else 0.0

            if not is_buy and held < qty:
                raise InsufficientHolding(symbol=symbol, held=held, requested=qty)

            cash = self._apply_cash_delta_locked(
                currency=ccy,
                delta=cash_delta,
                reason="buy" if is_buy else "sell",
                ref_type="holding",
                ref_id=symbol.upper(),
                idempotency_key=idempotency_key,
                note=note,
            )

            new_qty = round(held + qty if is_buy else held - qty, 6)
            if new_qty <= 0:
                self.conn.execute(
                    "DELETE FROM holding_position WHERE symbol = ?", (symbol.upper(),)
                )
                market_value = 0.0
                cost = None
            else:
                prev_cost = None
                if row is not None:
                    prev = self.conn.execute(
                        "SELECT cost FROM holding_position WHERE symbol = ?", (symbol.upper(),)
                    ).fetchone()
                    prev_cost = float(prev["cost"]) if prev and prev["cost"] is not None else None
                if is_buy:
                    # 加权平均成本；原成本缺失就用本次成交价
                    if prev_cost is not None and held > 0:
                        cost = round((prev_cost * held + price * qty) / (held + qty), 6)
                    else:
                        cost = price
                else:
                    cost = prev_cost
                market_value = round((cost or price) * new_qty, 2)
                self.conn.execute(
                    """
                    INSERT INTO holding_position(symbol, name, quantity, market_value, weight_pct, cost, pnl_pct, currency)
                    VALUES (?, ?, ?, ?, 0, ?, NULL, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      name=excluded.name, quantity=excluded.quantity,
                      market_value=excluded.market_value, cost=excluded.cost,
                      currency=excluded.currency
                    """,
                    (symbol.upper(), name, new_qty, market_value, cost, ccy),
                )
            self.conn.commit()
            return {
                "replayed": False,
                "ledger_id": cash["ledger_id"],
                "balance_after": cash["balance_after"],
                "cash_delta": cash["delta"],
                "currency": ccy,
                "quantity_after": new_qty,
                "cost": cost,
                "market_value": market_value,
                "amount": gross,
                "fee": fee_amt,
            }
