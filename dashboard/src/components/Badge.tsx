import type { ReactNode } from "react";

type BadgeTone = "profit" | "loss" | "neutral";

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}

const toneClasses: Record<BadgeTone, string> = {
  profit: "bg-profit-soft text-profit",
  loss: "bg-loss-soft text-loss",
  neutral: "bg-surface-2 text-ink-dim",
};

export function Badge({ children, tone = "neutral", className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${toneClasses[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
