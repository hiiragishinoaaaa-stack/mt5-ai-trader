import { useState } from "react";
import type { ProfitPoint } from "../../types";
import { formatSignedCurrencyJPY } from "../../lib/format";

interface ProfitBarChartProps {
  points: ProfitPoint[];
  labelFormatter: (key: string) => string;
}

/**
 * Bars capped at 24px thick with a 4px rounded data-end, square at the
 * baseline, colored by sign (green = profit, red = loss — the only two
 * hues this dashboard reserves for data). One hover tooltip per bar rather
 * than a label on every bar.
 */
export function ProfitBarChart({ points, labelFormatter }: ProfitBarChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const max = Math.max(...points.map((p) => Math.abs(p.value)), 1);

  return (
    <div className="flex h-40 items-end gap-1.5">
      {points.map((p, i) => {
        const heightPct = Math.max((Math.abs(p.value) / max) * 100, 4);
        const isProfit = p.value >= 0;
        const isHovered = hoverIndex === i;
        return (
          <div
            key={p.date}
            className="relative flex h-full flex-1 flex-col items-center justify-end"
            onPointerEnter={() => setHoverIndex(i)}
            onPointerLeave={() => setHoverIndex((h) => (h === i ? null : h))}
          >
            {isHovered ? (
              <div className="pointer-events-none absolute -top-1 z-10 -translate-y-full whitespace-nowrap rounded-lg border border-border-strong bg-surface-2 px-2 py-1 text-[11px] shadow-lg">
                <div className={`font-semibold ${isProfit ? "text-profit" : "text-loss"}`}>
                  {formatSignedCurrencyJPY(p.value)}
                </div>
                <div className="text-ink-faint">{labelFormatter(p.date)}</div>
              </div>
            ) : null}
            <div
              className={`w-full max-w-[20px] rounded-t-[4px] ${isProfit ? "bg-profit" : "bg-loss"}`}
              style={{ height: `${heightPct}%`, opacity: isHovered ? 1 : 0.82 }}
            />
          </div>
        );
      })}
    </div>
  );
}
