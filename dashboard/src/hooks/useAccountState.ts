import { useCallback, useEffect, useState } from "react";
import { AccountApiError, AccountDataUnavailableError, fetchAccountState } from "../api/accountApi";
import type { AccountState } from "../types";

export type AccountStateStatus = "loading" | "ready" | "connection_error" | "data_unavailable";

const DEFAULT_POLL_INTERVAL_MS = 5000;

/**
 * settings_server.pyの GET /api/account を定期的にポーリングする。
 *
 * - connection_error: settings_server.py自体に接続できない(未起動等)
 * - data_unavailable: settings_server.pyは動いているが、MT5/EA側がまだ
 *   口座情報を書き出していない(EA未起動・市場クローズ直後等)
 */
export function useAccountState(pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS) {
  const [status, setStatus] = useState<AccountStateStatus>("loading");
  const [state, setState] = useState<AccountState | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    fetchAccountState()
      .then((s) => {
        setState(s);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (err instanceof AccountDataUnavailableError) {
          setMessage(err.message);
          setStatus("data_unavailable");
        } else {
          setMessage(err instanceof AccountApiError ? err.message : "口座情報の取得に失敗しました");
          setStatus("connection_error");
        }
      });
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, pollIntervalMs]);

  return { status, state, message, reload: load };
}
