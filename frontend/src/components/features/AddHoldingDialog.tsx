import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { executeHoldingTrade, parseTradeRejection, tradeRejectionMessage } from "@/api/cash";
import { currencyMoney, currencySign, inferMarket } from "@/utils/market";

/** 搜索接口返回的标的 */
interface SearchHit {
  symbol: string;
  name?: string;
  market?: string;
  instrument_type?: string;
}

interface FxRates {
  usd_cny?: number | null;
  hkd_cny?: number | null;
  usdt_usd?: number | null;
  degraded?: boolean;
}

/** 「按市场折算成人民币」的系数；拿不到汇率返回 null（**不按 1:1 硬算**） */
function toCnyRate(rates: FxRates | undefined, currency: string): number | null {
  if (!rates || rates.degraded) return null;
  const usd = rates.usd_cny;
  if (!usd) return null;
  switch (currency) {
    case "CNY": return 1;
    case "USD": return usd;
    case "USDT": return usd * (rates.usdt_usd ?? 1);
    case "HKD": return rates.hkd_cny ?? null;
    default: return null;
  }
}

function marketCurrency(market: string): string {
  if (market === "HK") return "HKD";
  if (market === "US") return "USD";
  if (market === "CRYPTO") return "USDT";
  return "CNY";
}

/**
 * 新增持仓：搜标的 → 填数量/成本 → 实时预览折算 → 保存。
 *
 * 折算必须在这里就展示出来：用户填的是原币，看到的是人民币占比，
 * 否则不知道「0.08 个 BTC」在组合里到底占多少。
 */
export function AddHoldingDialog({
  fx,
  bookCny,
  onClose,
  onSaved,
}: {
  fx?: FxRates;
  /** 当前持仓的人民币市值（作分母）；拿不到折算时为 null */
  bookCny?: number | null;
  onClose: () => void;
  onSaved: (payload: unknown) => void;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [picked, setPicked] = useState<SearchHit | null>(null);
  /** buy = 买入（扣现金、必填成交价）；correct = 修正持仓（不动现金） */
  const [mode, setMode] = useState<"buy" | "correct">("buy");
  const [quantity, setQuantity] = useState("");
  const [cost, setCost] = useState("");
  const [fee, setFee] = useState("");
  /** 该标的本轮已持有的数量（修正模式用来判断"改大/改小"） */
  const [heldQty, setHeldQty] = useState<number | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  // 搜索（防抖 300ms）
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    const q = query.trim();
    if (!q) return;
    timer.current = window.setTimeout(async () => {
      setSearching(true);
      try {
        const res = await apiGet<{ items?: SearchHit[] }>(`/api/stocks/search?q=${encodeURIComponent(q)}`);
        setHits((res.items ?? []).slice(0, 8));
      } catch {
        setHits([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [query]);

  // 选中后取现价（走后端缓存，不直连数据源）
  useEffect(() => {
    if (!picked) return;
    let alive = true;
    (async () => {
      try {
        const ctx = await apiGet<{ price?: { last?: number | null; degraded?: boolean } }>(
          `/api/stocks/${encodeURIComponent(picked.symbol)}/context`,
        );
        if (!alive) return;
        const last = ctx.price?.last;
        setPrice(ctx.price?.degraded || !last ? null : last);
      } catch {
        if (alive) setPrice(null);
      }
    })();
    return () => { alive = false; };
  }, [picked]);

  // 修正模式要提示"改数量不等于买卖"，所以先查一下当前持仓
  useEffect(() => {
    // 不要在 effect 体内同步 setState（会触发级联渲染）；只在异步回调里写
    if (!picked || mode !== "correct") return undefined;
    let alive = true;
    void (async () => {
      try {
        const data = await apiGet<{ items?: { symbol?: string; quantity?: number }[] }>("/api/holdings");
        if (!alive) return;
        const found = (data.items ?? []).find((it) => String(it.symbol || "").toUpperCase() === picked.symbol.toUpperCase());
        setHeldQty(found ? Number(found.quantity ?? 0) : 0);
      } catch {
        if (alive) setHeldQty(null);
      }
    })();
    return () => { alive = false; };
  }, [picked, mode]);

  const market = picked ? inferMarket(picked.symbol, picked.market) : "";
  const currency = market ? marketCurrency(market) : "CNY";
  const rate = toCnyRate(fx, currency);

  const qtyNum = Number(quantity);
  const unitPrice = price ?? (Number(cost) || null);
  const preview = (() => {
    if (!picked || !Number.isFinite(qtyNum) || qtyNum <= 0 || !unitPrice) return null;
    const native = unitPrice * qtyNum;
    const cny = rate == null ? null : native * rate;
    const weight = cny != null && bookCny && bookCny > 0 ? (cny / (bookCny + cny)) * 100 : null;
    return { native, cny, weight, unit: unitPrice };
  })();

  const submit = async () => {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "buy") {
        const filled = await executeHoldingTrade({
          action: "buy",
          symbol: picked.symbol,
          quantity: Number(quantity),
          fill_price: Number(cost),
          fee: fee === "" ? 0 : Number(fee),
          currency,
        });
        onSaved(filled.summary);
      } else {
        const payload = await apiPost<unknown>("/api/holdings", {
          symbol: picked.symbol,
          quantity: Number(quantity),
          cost: cost === "" ? null : Number(cost),
        });
        onSaved(payload);
      }
    } catch (err) {
      const rej = parseTradeRejection(err);
      setError(rej ? tradeRejectionMessage(rej) : err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const fillPriceOk = mode === "correct" || (cost !== "" && Number(cost) > 0);
  const canSubmit = Boolean(picked) && Number(quantity) > 0 && fillPriceOk && !busy;

  return (
    <div className="session-delete-modal" role="dialog" aria-modal="true" aria-labelledby="add-holding-title">
      <div className="holding-dialog">
        <div className="holding-dialog-title" id="add-holding-title">
          {mode === "buy" ? "买入（扣可用现金）" : "修正持仓（不动现金）"}
        </div>
        <div className="holding-modes" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "buy"}
            className={mode === "buy" ? "holding-mode on" : "holding-mode"}
            onClick={() => setMode("buy")}
          >
            买入
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "correct"}
            className={mode === "correct" ? "holding-mode on" : "holding-mode"}
            onClick={() => setMode("correct")}
          >
            修正持仓
          </button>
        </div>

        <div className="holding-field">
          <label>标的（股票代码、中文名或币种，如 600519 / 茅台 / BTC）</label>
          <input
            className="holding-input"
            value={query}
            autoFocus
            placeholder="输入代码或名称搜索…"
            onChange={(e) => { setQuery(e.target.value); setPicked(null); setHits([]); setPrice(null); }}
          />
          {searching ? <div className="holding-hint">搜索中…</div> : null}
          {!picked && hits.length > 0 ? (
            <div className="holding-hits">
              {hits.map((hit) => {
                const m = inferMarket(hit.symbol, hit.market);
                return (
                  <button
                    key={hit.symbol}
                    type="button"
                    className="holding-hit"
                    onClick={() => { setPicked(hit); setQuery(`${hit.name ?? hit.symbol}`); setHits([]); setPrice(null); }}
                  >
                    <span className="holding-hit-name">{hit.name ?? hit.symbol}</span>
                    <span className={`mkt-badge mkt-${m}`}>{m}</span>
                    <span className="holding-hit-sym">{hit.symbol}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>

        {picked ? (
          <>
            <div className="holding-row">
              <div className="holding-field">
                <label>数量（{market === "CRYPTO" ? "枚" : "股"}）</label>
                <input
                  className="holding-input"
                  inputMode="decimal"
                  value={quantity}
                  placeholder={market === "CRYPTO" ? "0.08" : "100"}
                  onChange={(e) => setQuantity(e.target.value)}
                />
              </div>
              <div className="holding-field">
                <label>
                  {mode === "buy" ? "成交价" : "成本"}（{currencySign(currency)}/{market === "CRYPTO" ? "枚" : "股"}
                  {mode === "correct" ? "，可空" : "，必填"}）
                </label>
                <input
                  className="holding-input"
                  inputMode="decimal"
                  value={cost}
                  placeholder={mode === "buy" ? "按真实成交价填" : "可留空"}
                  onChange={(e) => setCost(e.target.value)}
                />
              </div>
              {mode === "buy" ? (
                <div className="holding-field">
                  <label>手续费（{currencySign(currency)}，可空）</label>
                  <input
                    className="holding-input"
                    inputMode="decimal"
                    value={fee}
                    placeholder="0"
                    onChange={(e) => setFee(e.target.value)}
                  />
                </div>
              ) : null}
            </div>

            {mode === "correct" ? (() => {
              const next = Number(quantity);
              if (heldQty == null || !Number.isFinite(next) || next <= 0) return null;
              const delta = Number((next - heldQty).toFixed(6));
              if (delta === 0) return null;
              return (
                <div className="holding-warn-block">
                  <div>
                    当前持有 <b className="num">{heldQty}</b>，修正为 <b className="num">{next}</b>
                    （{delta > 0 ? `多 ${delta}` : `少 ${Math.abs(delta)}`}）。
                    <b>修正不会动现金</b>：{delta > 0 ? "加仓请用「买入」" : "减仓请用「卖出」"}，
                    这里只用于纠错（录错数量/成本）。
                  </div>
                  <button
                    type="button"
                    className="holding-warn-action"
                    onClick={() => setMode(delta > 0 ? "buy" : "correct")}
                    disabled={delta < 0}
                  >
                    {delta > 0 ? "切到「买入」" : "卖出请到持仓页操作"}
                  </button>
                </div>
              );
            })() : null}

            <div className="holding-preview">
              {price == null ? (
                <div className="holding-hint">现价暂不可用，市值按成本价计算</div>
              ) : (
                <div>
                  现价 <span className="num">{currencyMoney(price, currency)}</span>
                  {quantity ? <> × {quantity} = <span className="num">{currencyMoney(preview?.native ?? null, currency)}</span></> : null}
                </div>
              )}
              {mode === "buy" && Number(quantity) > 0 && Number(cost) > 0 ? (
                <div className="holding-hint">
                  将从 <b>{currency}</b> 现金扣款{" "}
                  <span className="num">
                    {currencyMoney(Number(cost) * Number(quantity) + (Number(fee) || 0), currency)}
                  </span>
                  （含手续费）· 不足会被拒绝，不允许透支
                </div>
              ) : null}
              <div>
                {rate == null ? (
                  <span className="holding-warn">汇率不可用，暂不折算 —— 市值会先按原币记</span>
                ) : preview?.cny != null ? (
                  <>折算 <span className="num">{currencyMoney(preview.cny, "CNY")}</span>
                    {preview.weight != null ? <> · 占组合 <span className="num">{preview.weight.toFixed(2)}%</span></> : null}
                  </>
                ) : (
                  <span className="holding-hint">填数量后显示折算</span>
                )}
              </div>
            </div>
          </>
        ) : null}

        {error ? <div className="holding-error">{error}</div> : null}

        <div className="holding-actions">
          <button type="button" className="session-delete-cancel" onClick={onClose} disabled={busy}>取消</button>
          <button
            type="button"
            className="session-delete-confirm"
            onClick={() => void submit()}
            disabled={!canSubmit}
          >
            {busy ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
