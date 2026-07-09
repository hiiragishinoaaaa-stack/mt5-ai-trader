import { useEffect, useState } from "react";
import { getAnalyticsSummary } from "../api/client";
import type { AnalyticsSummary } from "../types";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Eyebrow } from "../components/Eyebrow";
import { StatCard } from "../components/StatCard";
import { Meter } from "../components/Meter";
import { Skeleton } from "../components/Skeleton";
import { ProfitLineChart } from "../components/charts/ProfitLineChart";
import { ProfitBarChart } from "../components/charts/ProfitBarChart";
import { formatCurrencyJPY, formatDateShort, formatMonthLabel, formatPercent, formatSignedCurrencyJPY } from "../lib/format";

export function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAnalyticsSummary().then((d) => {
      setData(d);
      setLoading(false);
    });
  }, []);

  return (
    <PageShell>
      <Header />
      <PageTitle sub="パフォーマンスの推移とAIの成績">Analytics</PageTitle>

      <Card>
        <div className="flex items-center justify-between">
          <Eyebrow>Cumulative Profit</Eyebrow>
          {!loading && data ? (
            <span className="text-xs font-semibold text-ink-dim">{formatCurrencyJPY(data.profitCurve.at(-1)?.value ?? 0)}</span>
          ) : null}
        </div>
        <div className="mt-2">{loading ? <Skeleton className="h-36 w-full" /> : <ProfitLineChart points={data?.profitCurve ?? []} />}</div>
      </Card>

      <Card className="mt-4">
        <Eyebrow>Daily Profit (14 days)</Eyebrow>
        <div className="mt-3">
          {loading ? <Skeleton className="h-40 w-full" /> : <ProfitBarChart points={data?.dailyProfit ?? []} labelFormatter={formatDateShort} />}
        </div>
      </Card>

      <Card className="mt-4">
        <Eyebrow>Monthly Profit</Eyebrow>
        <div className="mt-3">
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <ProfitBarChart
              points={(data?.monthlyProfit ?? []).map((m) => ({ date: m.month, value: m.value }))}
              labelFormatter={formatMonthLabel}
            />
          )}
        </div>
      </Card>

      <Eyebrow className="mb-2 mt-6">Performance</Eyebrow>
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          label="Win Rate"
          value={loading ? <Skeleton className="h-6 w-14" /> : formatPercent(data?.winRate ?? 0)}
          sub={!loading && data ? <Meter value={data.winRate} tone="profit" className="mt-1" /> : undefined}
        />
        <StatCard label="Profit Factor" value={loading ? <Skeleton className="h-6 w-14" /> : (data?.profitFactor.toFixed(2) ?? "—")} />
        <StatCard
          label="Max Drawdown"
          value={loading ? <Skeleton className="h-6 w-20" /> : formatSignedCurrencyJPY(data?.maxDrawdown ?? 0)}
          valueClassName="text-loss"
        />
        <StatCard
          label="Average Profit"
          value={loading ? <Skeleton className="h-6 w-20" /> : formatSignedCurrencyJPY(data?.averageProfit ?? 0)}
          valueClassName={!loading && (data?.averageProfit ?? 0) >= 0 ? "text-profit" : "text-loss"}
        />
        <StatCard label="Total Trades" value={loading ? <Skeleton className="h-6 w-14" /> : `${data?.totalTrades ?? 0}`} />
      </div>
    </PageShell>
  );
}
