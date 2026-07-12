import { useAccountState } from "../hooks/useAccountState";
import { useAiStatus } from "../hooks/useAiStatus";
import { useTradeHistory } from "../hooks/useTradeHistory";
import type { RealClosedTrade, RealPosition } from "../types";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { Eyebrow } from "../components/Eyebrow";
import { Skeleton } from "../components/Skeleton";
import { formatDateTime, formatPrice, formatSignedCurrency } from "../lib/format";

function unixToIso(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toISOString();
}

function RealPositionCard({ position, currency }: { position: RealPosition; currency: string }) {
  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge tone={position.type === "BUY" ? "profit" : "loss"}>{position.type}</Badge>
          <span className="text-base font-semibold text-ink">{position.symbol}</span>
          {position.is_artemis ? (
            <span className="text-[10px] uppercase tracking-wide text-ink-faint">ARTEMIS</span>
          ) : null}
        </div>
        <span className={`text-lg font-bold ${position.profit >= 0 ? "text-profit" : "text-loss"}`}>
          {formatSignedCurrency(position.profit, currency)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-y-4">
        <DetailRow label="Lot" value={position.volume.toFixed(2)} />
        <DetailRow label="Entry" value={formatPrice(position.price_open)} />
        <DetailRow label="Current" value={formatPrice(position.price_current)} />
        <DetailRow label="SL" value={position.sl > 0 ? formatPrice(position.sl) : "—"} valueClassName="text-loss" />
        <DetailRow label="TP" value={position.tp > 0 ? formatPrice(position.tp) : "—"} valueClassName="text-profit" />
        <DetailRow label="Opened" value={formatDateTime(unixToIso(position.open_time))} />
      </div>
    </Card>
  );
}

function DetailRow({ label, value, valueClassName = "" }: { label: string; value: string; valueClassName?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <span className={`text-sm font-semibold text-ink ${valueClassName}`}>{value}</span>
    </div>
  );
}

function RealHistoryItem({ trade, currency }: { trade: RealClosedTrade; currency: string }) {
  const isProfit = trade.profit >= 0;
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge tone={trade.type === "BUY" ? "profit" : "loss"}>{trade.type}</Badge>
          <span className="text-sm font-medium text-ink">{trade.symbol}</span>
          {trade.is_artemis ? <span className="text-[10px] uppercase tracking-wide text-ink-faint">ARTEMIS</span> : null}
        </div>
        <span className={`text-sm font-bold ${isProfit ? "text-profit" : "text-loss"}`}>
          {formatSignedCurrency(trade.profit, currency)}
        </span>
      </div>
      <div className="flex items-center justify-between border-t border-border pt-2.5 text-xs text-ink-faint">
        <span>
          {formatPrice(trade.price_open)} → {formatPrice(trade.price_close)}
        </span>
        <span>{formatDateTime(unixToIso(trade.close_time))}</span>
      </div>
    </Card>
  );
}

export function TradePage() {
  const { status: acctStatus, state: acctState, message: acctMessage } = useAccountState();
  const { status: aiStatusStatus, aiStatus, message: aiStatusMessage } = useAiStatus();
  const { status: historyStatus, trades, message: historyMessage } = useTradeHistory();
  const currency = acctState?.account.currency ?? "JPY";

  return (
    <PageShell>
      <Header />
      <PageTitle sub="現在のポジションと注文履歴">Trade</PageTitle>

      <Eyebrow className="mb-2">Current Position(MT5)</Eyebrow>
      {acctStatus === "loading" ? (
        <Card>
          <Skeleton className="h-24 w-full" />
        </Card>
      ) : acctStatus === "connection_error" ? (
        <Card className="text-sm text-loss">Bot APIに接続できません。settings_server.pyが起動しているか確認してください。</Card>
      ) : acctStatus === "data_unavailable" ? (
        <Card className="text-sm text-ink-dim">{acctMessage || "MT5からの口座情報がまだ届いていません。"}</Card>
      ) : acctState && acctState.positions.length > 0 ? (
        <div className="flex flex-col gap-3">
          {acctState.positions.map((p) => (
            <RealPositionCard key={p.ticket} position={p} currency={acctState.account.currency} />
          ))}
        </div>
      ) : (
        <Card className="text-sm text-ink-dim">現在保有しているポジションはありません。</Card>
      )}

      <Eyebrow className="mb-2 mt-6">AI Judgement</Eyebrow>
      {aiStatusStatus === "loading" ? (
        <Card>
          <Skeleton className="h-16 w-full" />
        </Card>
      ) : aiStatusStatus === "connection_error" ? (
        <Card className="text-sm text-loss">Bot APIに接続できません。settings_server.pyが起動しているか確認してください。</Card>
      ) : aiStatusStatus === "data_unavailable" ? (
        <Card className="text-sm text-ink-dim">{aiStatusMessage || "AIの判断がまだ届いていません。main.pyが起動しているか確認してください。"}</Card>
      ) : aiStatus ? (
        <Card className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Badge tone={aiStatus.action === "BUY" ? "profit" : aiStatus.action === "SELL" ? "loss" : "neutral"}>
              {aiStatus.action}
            </Badge>
            <span className="text-xs text-ink-faint">Confidence {aiStatus.confidence}%</span>
          </div>
          <p className="text-sm leading-relaxed text-ink-dim">{aiStatus.reason}</p>
        </Card>
      ) : null}

      <Eyebrow className="mb-2 mt-6">Order History</Eyebrow>
      {historyStatus === "loading" ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <Skeleton className="h-20 w-full" />
            </Card>
          ))}
        </div>
      ) : historyStatus === "connection_error" ? (
        <Card className="text-sm text-loss">Bot APIに接続できません。settings_server.pyが起動しているか確認してください。</Card>
      ) : historyStatus === "data_unavailable" ? (
        <Card className="text-sm text-ink-dim">{historyMessage || "取引履歴がまだ届いていません。"}</Card>
      ) : trades.length === 0 ? (
        <Card className="text-sm text-ink-dim">まだ決済された取引がありません。</Card>
      ) : (
        <div className="flex flex-col gap-3">
          {trades.map((t) => (
            <RealHistoryItem key={t.position_id} trade={t} currency={currency} />
          ))}
        </div>
      )}
    </PageShell>
  );
}
