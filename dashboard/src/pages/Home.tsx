import { useEffect, useState } from "react";
import { emergencyStopBot, getBotState, startBot, stopBot } from "../api/client";
import { useAccountState } from "../hooks/useAccountState";
import { useAiStatus } from "../hooks/useAiStatus";
import { useTradeHistory } from "../hooks/useTradeHistory";
import type { AiState, AiStatus, BotRunState } from "../types";
import { AiStatusHero } from "../components/AiStatusHero";
import { Header } from "../components/Header";
import { StatCard } from "../components/StatCard";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { PageShell } from "../components/PageShell";
import { AlertIcon, PlayIcon, StopIcon } from "../components/icons";
import { formatCurrency, formatPercent, formatSignedCurrency } from "../lib/format";

function isToday(unixSeconds: number): boolean {
  const d = new Date(unixSeconds * 1000);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  );
}

const AI_STATE_LABEL: Record<AiState, string> = {
  IDLE: "Idle",
  ANALYZING: "Analyzing",
  MONITORING: "Monitoring",
  TRADING: "Trading",
};

export function HomePage() {
  const [botState, setBotState] = useState<BotRunState | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const { status: acctStatus, state: acctState } = useAccountState();
  const { status: aiStatusStatus, aiStatus: realAiStatus } = useAiStatus();
  const { status: historyStatus, trades } = useTradeHistory();

  async function refresh() {
    const s = await getBotState();
    setBotState(s);
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

  // 残高・ポジション・シンボル・AI判断・取引履歴はすべてMT5/main.py側の実データ。
  // 取得できていない間は"—"やスケルトンにフォールバックする(botState/START・STOP
  // ボタンだけはまだ実際のプロセス制御と繋がっていないモック)。
  const acctLoading = acctStatus === "loading";
  const acctReady = acctStatus === "ready" && acctState !== null;
  const primaryPosition =
    acctState?.positions.find((p) => p.is_artemis) ?? acctState?.positions[0] ?? null;
  const extraPositionCount = acctState ? Math.max(0, acctState.positions.length - (primaryPosition ? 1 : 0)) : 0;

  const aiStatus: AiStatus | null =
    aiStatusStatus === "ready" && realAiStatus
      ? {
          action: realAiStatus.action,
          confidence: realAiStatus.confidence,
          reason: realAiStatus.reason,
          symbol: realAiStatus.symbol,
          timeframe: realAiStatus.timeframe,
          updatedAt: new Date(realAiStatus.updated_at * 1000).toISOString(),
        }
      : null;

  const historyReady = historyStatus === "ready";
  const todaysProfit = historyReady ? trades.filter((t) => isToday(t.close_time)).reduce((sum, t) => sum + t.profit, 0) : 0;
  const winRate = historyReady && trades.length > 0 ? (trades.filter((t) => t.profit > 0).length / trades.length) * 100 : 0;

  const aiState: AiState = !acctReady && aiStatusStatus !== "ready" ? "IDLE" : primaryPosition ? "TRADING" : "MONITORING";

  return (
    <PageShell>
      <Header botState={botState ?? undefined} />

      <AiStatusHero status={aiStatus} loading={loading} />

      <div className="mt-4 grid grid-cols-2 gap-3">
        <StatCard
          label="Today's Profit"
          value={
            !historyReady ? (
              <Skeleton className="h-6 w-20" />
            ) : (
              formatSignedCurrency(todaysProfit, acctState?.account.currency ?? "JPY")
            )
          }
          valueClassName={!historyReady ? "" : todaysProfit >= 0 ? "text-profit" : "text-loss"}
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
        <StatCard
          label="Win Rate"
          value={!historyReady ? <Skeleton className="h-6 w-14" /> : formatPercent(winRate)}
        />
        <StatCard label="AI State" value={AI_STATE_LABEL[aiState]} />
      </div>

      <div className="mt-6 space-y-2.5">
        <Button
          variant="primary"
          className="w-full"
          disabled={actionPending || loading || botState === "RUNNING"}
          onClick={() => runAction(startBot)}
        >
          <PlayIcon className="h-4 w-4" />
          START
        </Button>
        <Button
          variant="secondary"
          className="w-full"
          disabled={actionPending || loading || botState !== "RUNNING"}
          onClick={() => runAction(stopBot)}
        >
          <StopIcon className="h-4 w-4" />
          STOP
        </Button>
        <Button
          variant="danger"
          className="w-full"
          disabled={actionPending || loading || botState === "EMERGENCY_STOPPED"}
          onClick={() => runAction(emergencyStopBot)}
        >
          <AlertIcon className="h-4 w-4" />
          EMERGENCY STOP
        </Button>
      </div>
    </PageShell>
  );
}
