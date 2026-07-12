import { useCallback, useEffect, useState } from "react";
import { AiStatusApiError, AiStatusUnavailableError, fetchAiStatus } from "../api/aiStatusApi";
import type { RealAiStatus } from "../types";

export type AiStatusStatus = "loading" | "ready" | "connection_error" | "data_unavailable";

const DEFAULT_POLL_INTERVAL_MS = 5000;

/** settings_server.pyの GET /api/ai-status を定期的にポーリングする。 */
export function useAiStatus(pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS) {
  const [status, setStatus] = useState<AiStatusStatus>("loading");
  const [aiStatus, setAiStatus] = useState<RealAiStatus | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    fetchAiStatus()
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
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, pollIntervalMs]);

  return { status, aiStatus, message, reload: load };
}
