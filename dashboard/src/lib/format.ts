export function formatCurrencyJPY(value: number): string {
  const sign = value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(Math.round(value)).toLocaleString("ja-JP")}`;
}

export function formatSignedCurrencyJPY(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(Math.round(value)).toLocaleString("ja-JP")}`;
}

export function formatCurrency(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("ja-JP", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    const sign = value < 0 ? "-" : "";
    return `${sign}${Math.abs(value).toLocaleString("ja-JP")} ${currency}`;
  }
}

export function formatSignedCurrency(value: number, currency: string): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatCurrency(Math.abs(value), currency)}`;
}

export function formatPercent(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

export function formatPrice(value: number, digits = 3): string {
  return value.toFixed(digits);
}

export function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "たった今";
  if (diffSec < 60) return `${diffSec}秒前`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}分前`;
  const diffHour = Math.round(diffMin / 60);
  if (diffHour < 24) return `${diffHour}時間前`;
  const diffDay = Math.round(diffHour / 24);
  return `${diffDay}日前`;
}

export function formatDateShort(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ja-JP", { month: "short", day: "numeric" });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatMonthLabel(month: string): string {
  const [, m] = month.split("-");
  return `${Number(m)}月`;
}
