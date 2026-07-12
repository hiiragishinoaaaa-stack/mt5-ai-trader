import { useAccountState } from "../hooks/useAccountState";
import { useTradeHistory } from "../hooks/useTradeHistory";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Eyebrow } from "../components/Eyebrow";
import { StatCard } from "../components/StatCard";
import { Meter } from "../components/Meter";
import { Skeleton } from "../components/Skeleton";
import { ProfitLineChart } from "../components/charts/ProfitLineChart";
import { ProfitBarChart } from "../components/charts/ProfitBarChart";
import {
  computeAverageProfit,
  computeDailyProfit,
  computeMaxDrawdown,
  computeMonthlyProfit,
  computeProfitCurve,
  computeProfitFactor,
  computeWinRate,
} from "../lib/analytics";
import { formatDateShort, formatMonthLabel, formatPercent, formatSignedCurrency } from "../lib/format";

export function AnalyticsPage() {
  const { state: acctState } = useAccountState();
  const { status: historyStatus, trades, message: historyMessage } = useTradeHistory();
  const currency = acctState?.account.currency ?? "JPY";

  const loading = historyStatus === "loading";
  const unavailable = historyStatus === "connection_error" || historyStatus === "data_unavailable";

  const profitCurve = computeProfitCurve(trades);
  const dailyProfit = computeDailyProfit(trades);
  const monthlyProfit = computeMonthlyProfit(trades);
  const winRate = computeWinRate(trades);
  const profitFactor = computeProfitFactor(trades);
  const maxDrawdown = computeMaxDrawdown(trades);
  const averageProfit = computeAverageProfit(trades);

  return (
    <PageShell>
      <Header />
      <PageTitle sub="パフォーマンスの推移とAIの成績(直近の取引履歴に基づく)">Analytics</PageTitle>

      {unavailable ? (
        <Card className="text-sm text-ink-dim">
          {historyStatus === "connection_error"
            ? "Bot APIに接続できません。settings_server.pyが起動しているか確認してください。"
            : historyMessage || "取引履歴がまだ届いていません。"}
        </Card>
      ) : (
        <>
          <Card>
            <div className="flex items-center justify-between">
              <Eyebrow>Cumulative Profit</Eyebrow>
              {!loading ? (
                <span className="text-xs font-semibold text-ink-dim">
                  {formatSignedCurrency(profitCurve.at(-1)?.value ?? 0, currency)}
                </span>
              ) : null}
            </div>
            <div className="mt-2">{loading ? <Skeleton className="h-36 w-full" /> : <ProfitLineChart points={profitCurve} />}</div>
          </Card>

          <Card className="mt-4">
            <Eyebrow>Daily Profit (14 days)</Eyebrow>
            <div className="mt-3">
              {loading ? <Skeleton className="h-40 w-full" /> : <ProfitBarChart points={dailyProfit} labelFormatter={formatDateShort} />}
            </div>
          </Card>

          <Card className="mt-4">
            <Eyebrow>Monthly Profit</Eyebrow>
            <div className="mt-3">
              {loading ? (
                <Skeleton className="h-40 w-full" />
              ) : (
                <ProfitBarChart
                  points={monthlyProfit.map((m) => ({ date: m.month, value: m.value }))}
                  labelFormatter={formatMonthLabel}
                />
              )}
            </div>
          </Card>

          <Eyebrow className="mb-2 mt-6">Performance</Eyebrow>
          <div className="grid grid-cols-2 gap-3">
            <StatCard
              label="Win Rate"
              value={loading ? <Skeleton className="h-6 w-14" /> : formatPercent(winRate)}
              sub={!loading ? <Meter value={winRate} tone="profit" className="mt-1" /> : undefined}
            />
            <StatCard
              label="Profit Factor"
              value={loading ? <Skeleton className="h-6 w-14" /> : profitFactor === null ? "∞" : profitFactor.toFixed(2)}
            />
            <StatCard
              label="Max Drawdown"
              value={loading ? <Skeleton className="h-6 w-20" /> : formatSignedCurrency(maxDrawdown, currency)}
              valueClassName="text-loss"
            />
            <StatCard
              label="Average Profit"
              value={loading ? <Skeleton className="h-6 w-20" /> : formatSignedCurrency(averageProfit, currency)}
              valueClassName={!loading && averageProfit >= 0 ? "text-profit" : "text-loss"}
            />
            <StatCard label="Total Trades" value={loading ? <Skeleton className="h-6 w-14" /> : `${trades.length}`} />
          </div>
        </>
      )}
    </PageShell>
  );
}
