/**
 * settings_server.py(Python)の GET /api/trade-history への実際のHTTPクライアント。
 * EA(ARTEMIS_Bridge.mq5)が書き出す決済済み取引一覧を取得する(新しい順)。
 *
 * MT5/EA側がまだデータを書き出していない場合、サーバーは503を返す。
 * これは接続エラーとは区別し、「データ待ち」として扱う。
 */
import type { RealClosedTrade } from "../types";
import { apiBaseUrl, authHeaders } from "./botApiClient";

export class TradeHistoryApiError extends Error {}

/** MT5/EA側がまだ取引履歴を書き出していない場合に送出される(接続エラーとは区別する)。 */
export class TradeHistoryUnavailableError extends Error {}

export async function fetchTradeHistory(): Promise<RealClosedTrade[]> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/trade-history`, {
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw new TradeHistoryApiError(
      `設定サーバーに接続できません(${apiBaseUrl()})。settings_server.pyが起動しているか確認してください。`,
      { cause: err },
    );
  }

  if (res.status === 503) {
    const body = await res.json().catch(() => ({ error: "取引履歴がまだ届いていません" }));
    throw new TradeHistoryUnavailableError(body.error ?? "取引履歴がまだ届いていません");
  }

  if (!res.ok) {
    throw new TradeHistoryApiError(`取引履歴の取得に失敗しました(HTTP ${res.status})`);
  }

  const body = (await res.json()) as { trades: RealClosedTrade[] };
  return body.trades;
}
