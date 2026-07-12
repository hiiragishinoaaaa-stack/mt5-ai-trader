/**
 * RealClosedTrade[](trade_history_feed.py由来の実データ)から、Analytics画面の
 * 各種集計値を計算する純粋関数群。EA(ARTEMIS_Bridge.mq5)のInpTradeHistoryDays
 * (既定30日)・InpTradeHistoryMaxCount(既定50件)の範囲内のデータのみが対象
 * になるため、長期の統計としては「直近の取引履歴」であることに留意する。
 */
import type { RealClosedTrade } from "../types";

export interface ProfitPoint {
  date: string; // ISO date (YYYY-MM-DD)
  value: number;
}

export interface MonthlyProfitPoint {
  month: string; // "2026-07"
  value: number;
}

function toDateKey(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toISOString().slice(0, 10);
}

/** close_time昇順の累積損益カーブ(取得できている範囲内での相対的な推移)。 */
export function computeProfitCurve(trades: RealClosedTrade[]): ProfitPoint[] {
  const sorted = [...trades].sort((a, b) => a.close_time - b.close_time);
  let cumulative = 0;
  return sorted.map((t) => {
    cumulative += t.profit;
    return { date: toDateKey(t.close_time), value: cumulative };
  });
}

/** 直近N日(既定14日)の日別損益。取引が無い日も0として含める。 */
export function computeDailyProfit(trades: RealClosedTrade[], days = 14): ProfitPoint[] {
  const buckets = new Map<string, number>();
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    buckets.set(d.toISOString().slice(0, 10), 0);
  }
  for (const t of trades) {
    const key = toDateKey(t.close_time);
    if (buckets.has(key)) buckets.set(key, (buckets.get(key) ?? 0) + t.profit);
  }
  return Array.from(buckets.entries()).map(([date, value]) => ({ date, value }));
}

/** 月別損益(取得できている取引履歴の範囲内のみ)。 */
export function computeMonthlyProfit(trades: RealClosedTrade[]): MonthlyProfitPoint[] {
  const buckets = new Map<string, number>();
  for (const t of trades) {
    const d = new Date(t.close_time * 1000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    buckets.set(key, (buckets.get(key) ?? 0) + t.profit);
  }
  return Array.from(buckets.entries())
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([month, value]) => ({ month, value }));
}

export function computeWinRate(trades: RealClosedTrade[]): number {
  if (trades.length === 0) return 0;
  return (trades.filter((t) => t.profit > 0).length / trades.length) * 100;
}

/** 総利益/総損失。総損失が0(負けなし)の場合はnull(無限大)を返す。 */
export function computeProfitFactor(trades: RealClosedTrade[]): number | null {
  const grossProfit = trades.filter((t) => t.profit > 0).reduce((s, t) => s + t.profit, 0);
  const grossLoss = Math.abs(trades.filter((t) => t.profit < 0).reduce((s, t) => s + t.profit, 0));
  if (grossLoss === 0) return grossProfit > 0 ? null : 0;
  return grossProfit / grossLoss;
}

/** 累積損益カーブのピークからの最大下落幅(負の値、または取引が無ければ0)。 */
export function computeMaxDrawdown(trades: RealClosedTrade[]): number {
  const sorted = [...trades].sort((a, b) => a.close_time - b.close_time);
  let cumulative = 0;
  let peak = 0;
  let maxDrawdown = 0;
  for (const t of sorted) {
    cumulative += t.profit;
    if (cumulative > peak) peak = cumulative;
    const drawdown = cumulative - peak;
    if (drawdown < maxDrawdown) maxDrawdown = drawdown;
  }
  return maxDrawdown;
}

export function computeAverageProfit(trades: RealClosedTrade[]): number {
  if (trades.length === 0) return 0;
  return trades.reduce((s, t) => s + t.profit, 0) / trades.length;
}
