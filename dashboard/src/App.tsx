import { useState } from "react";
import { BottomNav } from "./components/BottomNav";
import type { TabKey } from "./components/BottomNav";
import { HomePage } from "./pages/Home";
import { TradePage } from "./pages/Trade";
import { AnalyticsPage } from "./pages/Analytics";
import { SettingsPage } from "./pages/Settings";

const PAGES: Record<TabKey, () => React.JSX.Element> = {
  home: HomePage,
  trade: TradePage,
  analytics: AnalyticsPage,
  settings: SettingsPage,
};

function App() {
  const [tab, setTab] = useState<TabKey>("home");
  const ActivePage = PAGES[tab];

  return (
    <div className="min-h-dvh bg-page">
      <ActivePage />
      <BottomNav active={tab} onChange={setTab} />
    </div>
  );
}

export default App;
