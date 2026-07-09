import { useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { ProfitPoint } from "../../types";
import { formatCurrencyJPY, formatDateShort } from "../../lib/format";

const WIDTH = 320;
const HEIGHT = 140;
const PAD_X = 4;
const PAD_TOP = 12;
const PAD_BOTTOM = 4;

/**
 * A single-series cumulative balance line. One series needs no legend box
 * (the card title already says what is plotted) per the dataviz skill's
 * mark spec: 2px line, ~10% opacity area wash, hairline crosshair, a single
 * hover tooltip rather than a value on every point.
 */
export function ProfitLineChart({ points }: { points: ProfitPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const { linePath, areaPath, coords, trendPositive } = useMemo(() => {
    if (points.length === 0) {
      return { linePath: "", areaPath: "", coords: [] as { x: number; y: number }[], trendPositive: true };
    }
    const values = points.map((p) => p.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const stepX = (WIDTH - PAD_X * 2) / Math.max(points.length - 1, 1);
    const coords = points.map((p, i) => ({
      x: PAD_X + i * stepX,
      y: PAD_TOP + (1 - (p.value - min) / range) * (HEIGHT - PAD_TOP - PAD_BOTTOM),
    }));
    const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(" ");
    const last = coords[coords.length - 1];
    const first = coords[0];
    const areaPath = `${linePath} L${last.x.toFixed(2)},${HEIGHT} L${first.x.toFixed(2)},${HEIGHT} Z`;
    return { linePath, areaPath, coords, trendPositive: values[values.length - 1] >= values[0] };
  }, [points]);

  const color = trendPositive ? "var(--color-profit)" : "var(--color-loss)";

  function handleMove(event: PointerEvent<SVGSVGElement>) {
    if (!svgRef.current || coords.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    let nearest = 0;
    let nearestDist = Infinity;
    coords.forEach((c, i) => {
      const dist = Math.abs(c.x - relX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIndex(nearest);
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;
  const hoveredCoord = hoverIndex !== null ? coords[hoverIndex] : null;
  const leftPct = hoveredCoord ? Math.min(88, Math.max(12, (hoveredCoord.x / WIDTH) * 100)) : 50;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-36 w-full touch-none"
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverIndex(null)}
        role="img"
        aria-label="累計損益の推移"
      >
        <defs>
          <linearGradient id="profit-area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#profit-area-fill)" stroke="none" />
        <path d={linePath} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {hoveredCoord ? (
          <>
            <line
              x1={hoveredCoord.x}
              x2={hoveredCoord.x}
              y1={PAD_TOP}
              y2={HEIGHT - PAD_BOTTOM}
              stroke="var(--color-border-strong)"
              strokeWidth="1"
            />
            <circle cx={hoveredCoord.x} cy={hoveredCoord.y} r="4" fill={color} stroke="var(--color-surface)" strokeWidth="2" />
          </>
        ) : null}
      </svg>
      {hovered ? (
        <div
          className="pointer-events-none absolute top-0 -translate-x-1/2 whitespace-nowrap rounded-lg border border-border-strong bg-surface-2 px-2.5 py-1.5 text-xs shadow-lg"
          style={{ left: `${leftPct}%` }}
        >
          <div className="font-semibold text-ink">{formatCurrencyJPY(hovered.value)}</div>
          <div className="text-ink-faint">{formatDateShort(hovered.date)}</div>
        </div>
      ) : null}
    </div>
  );
}
