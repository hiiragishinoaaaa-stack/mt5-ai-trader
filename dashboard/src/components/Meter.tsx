type MeterTone = "profit" | "loss" | "neutral";

const toneClasses: Record<MeterTone, string> = {
  profit: "bg-profit",
  loss: "bg-loss",
  neutral: "bg-ink",
};

export function Meter({ value, tone = "neutral", className = "" }: { value: number; tone?: MeterTone; className?: string }) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-surface-2 ${className}`}>
      <div className={`h-full rounded-full ${toneClasses[tone]} transition-[width]`} style={{ width: `${clamped}%` }} />
    </div>
  );
}
