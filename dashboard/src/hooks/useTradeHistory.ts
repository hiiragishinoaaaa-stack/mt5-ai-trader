import { useCallback, useEffect, useState } from "react";
import { TradeHistoryApiError, TradeHistoryUnavailableError, fetchTradeHistory } from "../api/tradeHistoryApi";
import type { RealClosedTrade } from "../types";

export type TradeHistoryStatus = "loading" | "ready" | "connection_error" | "data_unavailable";

const DEFAULT_POLL_INTERVAL_MS = 15000;

/**
 * settings_server.pyの GET /api/trade-history を定期的にポーリングする。
 * EA側もInpTradeHistoryIntervalSec(既定10秒)でしか更新しないため、
 * 口座情報/AI判断より緩めの間隔でポーリングする。
 */
export function useTradeHistory(pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS) {
  const [status, setStatus] = useState<TradeHistoryStatus>("loading");
  const [trades, setTrades] = useState<RealClosedTrade[]>([]);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    fetchTradeHistory()
      .then((t) => {
        setTrades(t);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (err instanceof TradeHistoryUnavailableError) {
          setMessage(err.message);
          setStatus("data_unavailable");
        } else {
          setMessage(err instanceof TradeHistoryApiError ? err.message : "取引履歴の取得に失敗しました");
          setStatus("connection_error");
        }
      });
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, pollIntervalMs]);

  return { status, trades, message, reload: load };
}
