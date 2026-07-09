import type { BotRunState } from "../types";
import { StatusPill } from "./StatusPill";

export function Header({ botState }: { botState?: BotRunState }) {
  return (
    <div className="mb-5 flex items-center justify-between">
      <div>
        <p className="text-lg font-bold leading-tight tracking-tight text-ink">ARTEMIS X</p>
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">AI Command Center</p>
      </div>
      {botState ? <StatusPill state={botState} /> : null}
    </div>
  );
}
