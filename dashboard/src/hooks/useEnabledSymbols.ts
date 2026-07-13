import { useEffect, useState } from "react";
import { fetchTradingSettings } from "../api/settingsApi";

/**
 * settings_server.pyのGET /api/settingsからENABLED_SYMBOLS(複数銘柄対応、
 * Phase 12)だけを取得する軽量フック。取得できるまでは空配列を返す
 * (呼び出し側はAI Judgementカードを未表示のまま待つ)。
 */
export function useEnabledSymbols(): string[] {
  const [symbols, setSymbols] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchTradingSettings()
      .then((settings) => {
        if (!cancelled) setSymbols(settings.ENABLED_SYMBOLS ?? []);
      })
      .catch(() => {
        if (!cancelled) setSymbols([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return symbols;
}
