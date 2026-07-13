import { useCallback, useEffect, useState } from "react";
import { AiStatusApiError, AiStatusUnavailableError, fetchAiStatus } from "../api/aiStatusApi";
import type { RealAiStatus } from "../types";

export type AiStatusStatus = "loading" | "ready" | "connection_error" | "data_unavailable";

const DEFAULT_POLL_INTERVAL_MS = 5000;

/**
 * settings_server.pyの GET /api/ai-status を定期的にポーリングする。
 * symbolを省略するとプライマリ銘柄(config.SYMBOL)が対象になる。
 */
export function useAiStatus(symbol?: string, pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS) {
  const [status, setStatus] = useState<AiStatusStatus>("loading");
  const [aiStatus, setAiStatus] = useState<RealAiStatus | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    fetchAiStatus(symbol)
      .then((s) => {
        setAiStatus(s);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (err instanceof AiStatusUnavailableError) {
          setMessage(err.message);
          setStatus("data_unavailable");
        } else {
          setMessage(err instanceof AiStatusApiError ? err.message : "AI判断の取得に失敗しました");
          setStatus("connection_error");
        }
      });
  }, [symbol]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, pollIntervalMs]);

  return { status, aiStatus, message, reload: load };
}

export interface MultiAiStatusEntry {
  status: AiStatusStatus;
  aiStatus: RealAiStatus | null;
  message: string;
}

/**
 * 複数銘柄対応(Phase 12): config.ENABLED_SYMBOLSに含まれる銘柄それぞれの
 * AI判断を並行してポーリングする。symbolsが空配列の間は何も取得しない。
 */
export function useMultiAiStatus(
  symbols: string[],
  pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS,
): Record<string, MultiAiStatusEntry> {
  const [entries, setEntries] = useState<Record<string, MultiAiStatusEntry>>({});
  const symbolsKey = symbols.join(",");

  const load = useCallback(() => {
    symbolsKey.split(",").filter(Boolean).forEach((symbol) => {
      fetchAiStatus(symbol)
        .then((s) => {
          setEntries((prev) => ({ ...prev, [symbol]: { status: "ready", aiStatus: s, message: "" } }));
        })
        .catch((err: unknown) => {
          if (err instanceof AiStatusUnavailableError) {
            setEntries((prev) => ({
              ...prev,
              [symbol]: { status: "data_unavailable", aiStatus: null, message: err.message },
            }));
          } else {
            setEntries((prev) => ({
              ...prev,
              [symbol]: {
                status: "connection_error",
                aiStatus: null,
                message: err instanceof AiStatusApiError ? err.message : "AI判断の取得に失敗しました",
              },
            }));
          }
        });
    });
  }, [symbolsKey]);

  useEffect(() => {
    if (!symbolsKey) {
      setEntries({});
      return;
    }
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, pollIntervalMs, symbolsKey]);

  return entries;
}
