import type { BotRunState } from "../types";

const COPY: Record<BotRunState, { label: string; dot: string; text: string }> = {
  RUNNING: { label: "Live", dot: "bg-profit", text: "text-profit" },
  STOPPED: { label: "Stopped", dot: "bg-ink-faint", text: "text-ink-dim" },
  EMERGENCY_STOPPED: { label: "Emergency Stop", dot: "bg-loss", text: "text-loss" },
};

export function StatusPill({ state }: { state: BotRunState }) {
  const copy = COPY[state];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-2 px-2.5 py-1 text-[11px] font-semibold ${copy.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${copy.dot}`} />
      {copy.label}
    </span>
  );
}
