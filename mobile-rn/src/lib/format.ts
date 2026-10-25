// 格式化工具。数值口径对齐 iOS（StrategyListView / StockDetailView / ScheduledTasksView）。

/** 带正负号的百分比，如 +1.23% */
export function signedPct(v: number | undefined | null, digits = 2): string {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

/** 不带正负号的百分比，如 1.23%（用于回撤等） */
export function plainPct(v: number | undefined | null, digits = 2): string {
  if (v == null) return '—';
  return `${v.toFixed(digits)}%`;
}

/** 胜率归一：后端可能是 0-1 比例，也可能是 0-100 百分数（对齐 iOS StrategyListView.swift:119） */
export function normalizeWinRate(v: number | undefined | null): number | null {
  if (v == null) return null;
  return v * (Math.abs(v) <= 1 ? 100 : 1);
}

export function winRateText(v: number | undefined | null): string {
  const n = normalizeWinRate(v);
  return n == null ? '—' : `${n.toFixed(1)}%`;
}

/** 金额 亿/万 缩写 */
export function formatMoney(v: number | undefined | null): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

export function formatVolume(v: number | undefined | null): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(1)}万`;
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

export function formatPrice(v: number | undefined | null, market?: string): string {
  if (v == null) return '—';
  const prefix = market === 'HK' ? 'HK$' : market === 'US' ? '$' : '¥';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${prefix}${(v / 10000).toFixed(2)}万`;
  if (abs >= 1000) return `${prefix}${v.toFixed(1)}`;
  if (abs >= 100) return `${prefix}${v.toFixed(2)}`;
  return `${prefix}${v.toFixed(3)}`;
}

/** 中文相对时间（对齐 iOS RelativeDateTimeFormatter zh_CN） */
export function relativeTime(iso?: string | null): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  const diff = Date.now() - t;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return '刚刚';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  const day = Math.floor(hour / 24);
  if (day < 7) return `${day} 天前`;
  return String(iso).slice(0, 10);
}

export function shortDate(iso?: string | null): string {
  if (!iso) return '—';
  const s = String(iso).slice(0, 10);
  const parts = s.split('-');
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : s;
}


/** 币种符号：持仓可能是原币计价（加密常见 USD/USDT） */
export function currencySign(currency?: string | null): string {
  const c = String(currency ?? 'CNY').toUpperCase();
  switch (c) {
    case 'USD':
    case 'USDT':
    case 'USDC':
      return '$';
    case 'HKD':
      return 'HK$';
    case 'EUR':
      return '€';
    case 'JPY':
      return 'JP¥';
    case 'BTC':
      return '₿';
    default:
      return '¥';
  }
}

/** 原币金额：带币种符号 */
export function currencyMoney(value: number | undefined | null, currency?: string | null): string {
  if (value == null) return '—';
  return `${currencySign(currency)}${formatMoney(value)}`;
}

/** 市场的中文名（持仓/自选行用；后端 market 是 CN/HK/US/CRYPTO） */
export function marketLabel(market?: string | null): string {
  const m = String(market ?? '').toUpperCase();
  switch (m) {
    case 'CN':
      return 'A股';
    case 'HK':
      return '港股';
    case 'US':
      return '美股';
    case 'CRYPTO':
      return '加密';
    default:
      return m || '';
  }
}

/** 持仓数量单位：币按「枚」，股按「股」 */
export function quantityUnit(market?: string | null): string {
  return String(market ?? '').toUpperCase() === 'CRYPTO' ? '枚' : '股';
}
