import type { ReactNode } from "react";
import { Card } from "../Card";

export function SettingsSection({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card className="flex flex-col gap-1">
      <div className="mb-1 flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 text-ink-dim">{icon}</span>
        <span className="text-sm font-semibold text-ink">{title}</span>
      </div>
      <div className="divide-y divide-border">{children}</div>
    </Card>
  );
}

export function Toggle({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-10 shrink-0 rounded-full transition-colors ${checked ? "bg-ink" : "border border-border-strong bg-surface-2"}`}
    >
      <span
        className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full transition-transform ${
          checked ? "translate-x-[18px] bg-page" : "translate-x-0 bg-ink-faint"
        }`}
      />
    </button>
  );
}

export function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
      <div>
        <p className="text-sm font-medium text-ink">{label}</p>
        {description ? <p className="mt-0.5 text-xs text-ink-faint">{description}</p> : null}
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  mono = false,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  mono?: boolean;
  placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
      <span className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={`w-full rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-sm text-ink outline-none focus:border-ink-faint ${
          mono ? "font-mono text-xs" : ""
        }`}
      />
    </label>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  step = 1,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  suffix?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
      <span className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2.5">
        <input
          type="number"
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="w-full bg-transparent text-sm text-ink outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
        {suffix ? <span className="shrink-0 text-xs text-ink-faint">{suffix}</span> : null}
      </div>
    </label>
  );
}

export function PillGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
      <span className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <div className="flex gap-2">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            disabled={opt.disabled}
            onClick={() => onChange(opt.value)}
            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-semibold transition-colors disabled:opacity-40 ${
              value === opt.value ? "border-ink bg-ink text-page" : "border-border-strong bg-surface-2 text-ink-dim"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
