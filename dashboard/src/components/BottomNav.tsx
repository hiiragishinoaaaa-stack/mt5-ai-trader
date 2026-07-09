import { AnalyticsIcon, HomeIcon, SettingsIcon, TradeIcon } from "./icons";
import type { IconProps } from "./icons";

export type TabKey = "home" | "trade" | "analytics" | "settings";

const TABS: { key: TabKey; label: string; icon: (props: IconProps) => React.JSX.Element }[] = [
  { key: "home", label: "Home", icon: HomeIcon },
  { key: "trade", label: "Trade", icon: TradeIcon },
  { key: "analytics", label: "Analytics", icon: AnalyticsIcon },
  { key: "settings", label: "Settings", icon: SettingsIcon },
];

export function BottomNav({ active, onChange }: { active: TabKey; onChange: (tab: TabKey) => void }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-page/85 backdrop-blur-lg">
      <div className="mx-auto flex max-w-md items-stretch justify-between px-2 pb-[max(env(safe-area-inset-bottom),10px)] pt-1.5 sm:max-w-lg">
        {TABS.map(({ key, label, icon: Icon }) => {
          const isActive = key === active;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onChange(key)}
              className="flex flex-1 flex-col items-center gap-1 rounded-xl px-2 py-2"
              aria-current={isActive ? "page" : undefined}
            >
              <Icon className={`h-6 w-6 ${isActive ? "text-ink" : "text-ink-faint"}`} strokeWidth={isActive ? 2 : 1.75} />
              <span className={`text-[11px] font-medium ${isActive ? "text-ink" : "text-ink-faint"}`}>{label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
