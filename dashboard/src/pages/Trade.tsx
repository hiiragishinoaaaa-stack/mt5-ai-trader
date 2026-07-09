import { useEffect, useState } from "react";
import { getTradeSnapshot } from "../api/client";
import type { OrderHistoryItem, TradeSnapshot } from "../types";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { Eyebrow } from "../components/Eyebrow";
import { Skeleton } from "../components/Skeleton";
import { formatDateTime, formatPrice, formatSignedCurrencyJPY } from "../lib/format";

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

  useEffect(() => {
    getTradeSnapshot().then((s) => {
      setSnapshot(s);
      setLoading(false);
    });
  }, []);

  const position = snapshot?.position ?? null;

  return (
    <PageShell>
      <Header />
      <PageTitle sub="現在のポジションと注文履歴">Trade</PageTitle>

      <Eyebrow className="mb-2">Current Position</Eyebrow>
      {loading ? (
        <Card>
          <Skeleton className="h-24 w-full" />
        </Card>
      ) : position ? (
        <Card className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Badge tone={position.side === "BUY" ? "profit" : "loss"}>{position.side}</Badge>
              <span className="text-base font-semibold text-ink">{position.symbol}</span>
            </div>
            <span className={`text-lg font-bold ${position.profit >= 0 ? "text-profit" : "text-loss"}`}>
              {formatSignedCurrencyJPY(position.profit)}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-y-4">
            <DetailRow label="Lot" value={position.volume.toFixed(2)} />
            <DetailRow label="Entry" value={formatPrice(position.entryPrice)} />
            <DetailRow label="Current" value={formatPrice(position.currentPrice)} />
            <DetailRow label="SL" value={formatPrice(position.sl)} valueClassName="text-loss" />
            <DetailRow label="TP" value={formatPrice(position.tp)} valueClassName="text-profit" />
            <DetailRow label="Opened" value={formatDateTime(position.openedAt)} />
          </div>
        </Card>
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
