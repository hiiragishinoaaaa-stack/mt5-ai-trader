import { useEffect, useState } from "react";
import { emergencyStopBot, getAiStatus, getHomeSummary, startBot, stopBot } from "../api/client";
import type { AiStatus, HomeSummary } from "../types";
import { AiStatusHero } from "../components/AiStatusHero";
import { Header } from "../components/Header";
import { StatCard } from "../components/StatCard";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { PageShell } from "../components/PageShell";
import { AlertIcon, PlayIcon, StopIcon } from "../components/icons";
import { formatCurrencyJPY, formatPercent, formatSignedCurrencyJPY } from "../lib/format";

const AI_STATE_LABEL: Record<HomeSummary["aiState"], string> = {
  IDLE: "Idle",
  ANALYZING: "Analyzing",
  MONITORING: "Monitoring",
  TRADING: "Trading",
};

export function HomePage() {
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);

  async function refresh() {
    const [s, a] = await Promise.all([getHomeSummary(), getAiStatus()]);
    setSummary(s);
    setAiStatus(a);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runAction(action: () => Promise<unknown>) {
    setActionPending(true);
    await action();
    await refresh();
    setActionPending(false);
  }

  const position = summary?.position ?? null;
  const todaysProfit = summary?.todaysProfit ?? 0;

  return (
    <PageShell>
      <Header botState={summary?.botState} />

      <AiStatusHero status={aiStatus} loading={loading} />

      <div className="mt-4 grid grid-cols-2 gap-3">
        <StatCard
          label="Today's Profit"
          value={loading ? <Skeleton className="h-6 w-20" /> : formatSignedCurrencyJPY(todaysProfit)}
          valueClassName={loading ? "" : todaysProfit >= 0 ? "text-profit" : "text-loss"}
        />
        <StatCard
          label="Balance"
          value={loading ? <Skeleton className="h-6 w-24" /> : formatCurrencyJPY(summary?.balance ?? 0)}
        />
        <StatCard
          label="Current Position"
          value={
            loading ? (
              <Skeleton className="h-6 w-16" />
            ) : position ? (
              <span className={position.side === "BUY" ? "text-profit" : "text-loss"}>
                {position.side} {position.volume}
              </span>
            ) : (
              <span className="text-ink-dim">None</span>
            )
          }
          sub={position ? formatSignedCurrencyJPY(position.profit) : undefined}
        />
        <StatCard
          label="Current Symbol"
          value={loading ? <Skeleton className="h-6 w-20" /> : (summary?.currentSymbol ?? "—")}
        />
        <StatCard label="Win Rate" value={loading ? <Skeleton className="h-6 w-14" /> : formatPercent(summary?.winRate ?? 0)} />
        <StatCard
          label="AI State"
          value={loading ? <Skeleton className="h-6 w-20" /> : AI_STATE_LABEL[summary?.aiState ?? "IDLE"]}
        />
      </div>

      <div className="mt-6 space-y-2.5">
        <Button
          variant="primary"
          className="w-full"
          disabled={actionPending || loading || summary?.botState === "RUNNING"}
          onClick={() => runAction(startBot)}
        >
          <PlayIcon className="h-4 w-4" />
          START
        </Button>
        <Button
          variant="secondary"
          className="w-full"
          disabled={actionPending || loading || summary?.botState !== "RUNNING"}
          onClick={() => runAction(stopBot)}
        >
          <StopIcon className="h-4 w-4" />
          STOP
        </Button>
        <Button
          variant="danger"
          className="w-full"
          disabled={actionPending || loading || summary?.botState === "EMERGENCY_STOPPED"}
          onClick={() => runAction(emergencyStopBot)}
        >
          <AlertIcon className="h-4 w-4" />
          EMERGENCY STOP
        </Button>
      </div>
    </PageShell>
  );
}
