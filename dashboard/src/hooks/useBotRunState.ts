import { useCallback, useEffect, useState } from "react";
import { fetchTradingSettings, saveTradingSettings, SettingsApiError } from "../api/settingsApi";
import type { BotRunState } from "../types";

export type BotRunStateStatus = "loading" | "ready" | "connection_error";

const DEFAULT_POLL_INTERVAL_MS = 5000;

/**
 * BOT_RUN_STATE(DashboardのSTART/STOP/EMERGENCY STOP)を settings_server.py
 * の GET/POST /api/settings 経由で取得・変更する。
 *
 * BOT_RUN_STATEはsettings_schema.pyのFIELDSの1つに過ぎないため、専用の
 * エンドポイントは追加せず、既存のTradingSettings用のAPIをそのまま使う。
 */
export function useBotRunState(pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS) {
  const [status, setStatus] = useState<BotRunStateStatus>("loading");
  const [botRunState, setBotRunStateValue] = useState<BotRunState | null>(null);
  const [message, setMessage] = useState("");
  const [actionPending, setActionPending] = useState(false);

  const load = useCallback(() => {
    fetchTradingSettings()
      .then((settings) => {
        setBotRunStateValue(settings.BOT_RUN_STATE);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        setMessage(err instanceof SettingsApiError ? err.message : "Bot状態の取得に失敗しました");
        setStatus("connection_error");
      });
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, pollIntervalMs]);

  const changeBotRunState = useCallback(async (next: BotRunState): Promise<boolean> => {
    setActionPending(true);
    const result = await saveTradingSettings({ BOT_RUN_STATE: next });
    setActionPending(false);

    if (!result.success) {
      setMessage(result.message ?? "Bot状態の変更に失敗しました");
      return false;
    }

    setBotRunStateValue(result.settings?.BOT_RUN_STATE ?? next);
    return true;
  }, []);

  return { status, botRunState, message, actionPending, reload: load, changeBotRunState };
}
