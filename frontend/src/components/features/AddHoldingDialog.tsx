import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
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
  const [quantity, setQuantity] = useState("");
  const [cost, setCost] = useState("");
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
      const payload = await apiPost<unknown>("/api/holdings", {
        symbol: picked.symbol,
        quantity: Number(quantity),
        cost: cost === "" ? null : Number(cost),
      });
      onSaved(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = Boolean(picked) && Number(quantity) > 0 && !busy;

  return (
    <div className="session-delete-modal" role="dialog" aria-modal="true" aria-labelledby="add-holding-title">
      <div className="holding-dialog">
        <div className="holding-dialog-title" id="add-holding-title">新增持仓</div>

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
                <label>成本（{currencySign(currency)}/{market === "CRYPTO" ? "枚" : "股"}，可空）</label>
                <input
                  className="holding-input"
                  inputMode="decimal"
                  value={cost}
                  placeholder="可留空"
                  onChange={(e) => setCost(e.target.value)}
                />
              </div>
            </div>

            <div className="holding-preview">
              {price == null ? (
                <div className="holding-hint">现价暂不可用，市值按成本价计算</div>
              ) : (
                <div>
                  现价 <span className="num">{currencyMoney(price, currency)}</span>
                  {quantity ? <> × {quantity} = <span className="num">{currencyMoney(preview?.native ?? null, currency)}</span></> : null}
                </div>
              )}
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
