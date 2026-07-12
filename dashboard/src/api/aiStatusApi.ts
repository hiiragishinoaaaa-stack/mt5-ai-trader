/**
 * settings_server.py(Python)の GET /api/ai-status への実際のHTTPクライアント。
 * main.pyが各サイクルで書き出す最新のAI判断(BUY/SELL/WAIT)を取得する。
 *
 * main.pyがまだ一度も判断を書き出していない(起動直後・停止中)場合、
 * サーバーは503を返す。これは接続エラーとは区別し、「データ待ち」として扱う。
 */
import type { RealAiStatus } from "../types";
import { apiBaseUrl, authHeaders } from "./botApiClient";

export class AiStatusApiError extends Error {}

/** main.pyがまだAI判断を書き出していない場合に送出される(接続エラーとは区別する)。 */
export class AiStatusUnavailableError extends Error {}

export async function fetchAiStatus(): Promise<RealAiStatus> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/ai-status`, {
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw new AiStatusApiError(
      `設定サーバーに接続できません(${apiBaseUrl()})。settings_server.pyが起動しているか確認してください。`,
      { cause: err },
    );
  }

  if (res.status === 503) {
    const body = await res.json().catch(() => ({ error: "AIの判断がまだ届いていません" }));
    throw new AiStatusUnavailableError(body.error ?? "AIの判断がまだ届いていません");
  }

  if (!res.ok) {
    throw new AiStatusApiError(`AI判断の取得に失敗しました(HTTP ${res.status})`);
  }

  return (await res.json()) as RealAiStatus;
}
