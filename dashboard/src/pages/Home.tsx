import { useEffect, useState } from "react";
import { emergencyStopBot, getAiStatus, getHomeSummary, startBot, stopBot } from "../api/client";
import { useAccountState } from "../hooks/useAccountState";
import type { AiStatus, HomeSummary } from "../types";
import { AiStatusHero } from "../components/AiStatusHero";
import { Header } from "../components/Header";
import { StatCard } from "../components/StatCard";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { PageShell } from "../components/PageShell";
import { AlertIcon, PlayIcon, StopIcon } from "../components/icons";
import { formatCurrency, formatPercent, formatSignedCurrency, formatSignedCurrencyJPY } from "../lib/format";

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
  const { status: acctStatus, state: acctState } = useAccountState();

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

  const todaysProfit = summary?.todaysProfit ?? 0;

  // 残高・ポジション・シンボルはMT5(EA経由)の実データ。取得できていない間は
  // Homeの他の項目(Today's Profit/Win Rate/AI State等)と同様にモックのまま
  // 崩れないよう、スケルトン/"—"表示にフォールバックする。
  const acctLoading = acctStatus === "loading";
  const acctReady = acctStatus === "ready" && acctState !== null;
  const primaryPosition =
    acctState?.positions.find((p) => p.is_artemis) ?? acctState?.positions[0] ?? null;
  const extraPositionCount = acctState ? Math.max(0, acctState.positions.length - (primaryPosition ? 1 : 0)) : 0;

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
          value={
            acctLoading ? (
              <Skeleton className="h-6 w-24" />
            ) : acctReady ? (
              formatCurrency(acctState!.account.balance, acctState!.account.currency)
            ) : (
              <span className="text-ink-dim">—</span>
            )
          }
          sub={acctReady ? `Equity ${formatCurrency(acctState!.account.equity, acctState!.account.currency)}` : undefined}
        />
        <StatCard
          label="Current Position"
          value={
            acctLoading ? (
              <Skeleton className="h-6 w-16" />
            ) : !acctReady ? (
              <span className="text-ink-dim">—</span>
            ) : primaryPosition ? (
              <span className={primaryPosition.type === "BUY" ? "text-profit" : "text-loss"}>
                {primaryPosition.type} {primaryPosition.volume}
              </span>
            ) : (
              <span className="text-ink-dim">None</span>
            )
          }
          sub={
            primaryPosition
              ? `${formatSignedCurrency(primaryPosition.profit, acctState!.account.currency)}${
                  extraPositionCount > 0 ? ` (+${extraPositionCount} more)` : ""
                }`
              : undefined
          }
        />
        <StatCard
          label="Current Symbol"
          value={acctLoading ? <Skeleton className="h-6 w-20" /> : (acctState?.target_symbol ?? "—")}
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
