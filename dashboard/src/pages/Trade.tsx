import { useEffect, useState } from "react";
import { getTradeSnapshot } from "../api/client";
import { useAccountState } from "../hooks/useAccountState";
import type { OrderHistoryItem, RealPosition, TradeSnapshot } from "../types";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { Eyebrow } from "../components/Eyebrow";
import { Skeleton } from "../components/Skeleton";
import { formatDateTime, formatPrice, formatSignedCurrency, formatSignedCurrencyJPY } from "../lib/format";

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

function HistoryItem({ item }: { item: OrderHistoryItem }) {
  const isProfit = item.profit >= 0;
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge tone={item.side === "BUY" ? "profit" : "loss"}>{item.side}</Badge>
          <span className="text-sm font-medium text-ink">{item.symbol}</span>
        </div>
        <span className={`text-sm font-bold ${isProfit ? "text-profit" : "text-loss"}`}>
          {formatSignedCurrencyJPY(item.profit)}
        </span>
      </div>
      <p className="text-xs leading-relaxed text-ink-dim">{item.aiReason}</p>
      <div className="flex items-center justify-between border-t border-border pt-2.5 text-xs text-ink-faint">
        <span>
          {formatPrice(item.entryPrice)} → {formatPrice(item.exitPrice)}
        </span>
        <span>{formatDateTime(item.closedAt)}</span>
      </div>
    </Card>
  );
}

export function TradePage() {
  const [snapshot, setSnapshot] = useState<TradeSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const { status: acctStatus, state: acctState, message: acctMessage } = useAccountState();

  useEffect(() => {
    getTradeSnapshot().then((s) => {
      setSnapshot(s);
      setLoading(false);
    });
  }, []);

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

      {!loading && snapshot ? (
        <>
          <Eyebrow className="mb-2 mt-6">AI Judgement</Eyebrow>
          <Card className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <Badge
                tone={snapshot.aiStatus.action === "BUY" ? "profit" : snapshot.aiStatus.action === "SELL" ? "loss" : "neutral"}
              >
                {snapshot.aiStatus.action}
              </Badge>
              <span className="text-xs text-ink-faint">Confidence {snapshot.aiStatus.confidence}%</span>
            </div>
            <p className="text-sm leading-relaxed text-ink-dim">{snapshot.aiStatus.reason}</p>
          </Card>
        </>
      ) : null}

      <Eyebrow className="mb-2 mt-6">Order History</Eyebrow>
      <div className="flex flex-col gap-3">
        {loading
          ? [0, 1, 2].map((i) => (
              <Card key={i}>
                <Skeleton className="h-20 w-full" />
              </Card>
            ))
          : snapshot?.history.map((item) => <HistoryItem key={item.id} item={item} />)}
      </div>
    </PageShell>
  );
}
