import type { AiStatus } from "../types";
import { formatRelativeTime } from "../lib/format";
import { Eyebrow } from "./Eyebrow";
import { Meter } from "./Meter";

const ACTION_COPY: Record<AiStatus["action"], { label: string; text: string; dot: string; meterTone: "profit" | "loss" | "neutral" }> = {
  BUY: { label: "BUY", text: "text-profit", dot: "bg-profit", meterTone: "profit" },
  SELL: { label: "SELL", text: "text-loss", dot: "bg-loss", meterTone: "loss" },
  WAIT: { label: "WAIT", text: "text-ink-dim", dot: "bg-ink-faint", meterTone: "neutral" },
};

export function AiStatusHero({ status, loading }: { status: AiStatus | null; loading?: boolean }) {
  const copy = status ? ACTION_COPY[status.action] : ACTION_COPY.WAIT;

  return (
    <div className="relative overflow-hidden rounded-3xl border border-border bg-surface p-6">
      <div className="flex items-center justify-between">
        <Eyebrow>AI Status</Eyebrow>
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-ink-faint">
          <span className="relative flex h-1.5 w-1.5">
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${copy.dot}`} />
            <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${copy.dot}`} />
          </span>
          {loading ? "分析中" : "リアルタイム監視中"}
        </div>
      </div>

      <div className={`mt-5 text-6xl font-bold leading-none tracking-tight ${copy.text}`}>
        {loading || !status ? "···" : copy.label}
      </div>

      <div className="mt-5 flex items-center justify-between text-sm">
        <span className="font-medium text-ink-dim">Confidence</span>
        <span className="font-semibold text-ink">{status ? `${status.confidence}%` : "—"}</span>
      </div>
      <Meter value={status?.confidence ?? 0} tone={copy.meterTone} className="mt-2" />

      <p className="mt-4 min-h-10 text-sm leading-relaxed text-ink-dim">
        {status?.reason ?? "価格データを待機しています"}
      </p>

      <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-ink-faint">
        <span>
          {status?.symbol ?? "—"} · {status?.timeframe ?? "—"}
        </span>
        <span>{status ? formatRelativeTime(status.updatedAt) : ""}</span>
      </div>
    </div>
  );
}
