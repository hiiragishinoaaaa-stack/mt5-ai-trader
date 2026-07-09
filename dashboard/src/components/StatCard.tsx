import type { ReactNode } from "react";
import { Card } from "./Card";

interface StatCardProps {
  label: string;
  value: ReactNode;
  valueClassName?: string;
  sub?: ReactNode;
  icon?: ReactNode;
}

export function StatCard({ label, value, valueClassName = "", sub, icon }: StatCardProps) {
  return (
    <Card className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wider text-ink-faint">{label}</span>
        {icon ? <span className="text-ink-faint">{icon}</span> : null}
      </div>
      <span className={`text-xl font-semibold tracking-tight text-ink ${valueClassName}`}>{value}</span>
      {sub ? <span className="text-xs text-ink-dim">{sub}</span> : null}
    </Card>
  );
}
