import type { ReactNode } from "react";

export function PageShell({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-md px-4 pb-28 pt-[max(env(safe-area-inset-top),20px)] sm:max-w-lg">{children}</div>;
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-5">
      <h1 className="text-2xl font-bold tracking-tight text-ink">{children}</h1>
      {sub ? <p className="mt-1 text-sm text-ink-dim">{sub}</p> : null}
    </div>
  );
}
