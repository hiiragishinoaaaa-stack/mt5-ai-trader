/**
 * settings_server.py(Python)の POST /api/close-position への実際のHTTPクライアント。
 *
 * TradeページのCLOSEボタンから呼ばれる。指定した銘柄のARTEMIS自身の
 * 全ポジションを決済するようEA(要v4.03以降)へ要求する(position_closer.py
 * を参照)。ENABLE_ORDERS/DEMO_ONLYが有効でない場合や、EAが応答しない場合は
 * success: falseで返る(例外は投げない)。
 */
import { apiBaseUrl, authHeaders } from "./botApiClient";

export class ClosePositionApiError extends Error {}

export interface ClosePositionResult {
  success: boolean;
  message: string;
  closedCount: number;
}

export async function closePosition(symbol: string): Promise<ClosePositionResult> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/close-position`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ symbol }),
    });
  } catch (err) {
    throw new ClosePositionApiError(
      `設定サーバーに接続できません(${apiBaseUrl()})。settings_server.pyが起動しているか確認してください。`,
      { cause: err },
    );
  }

  let body: { success?: boolean; message?: string; closed_count?: number } = {};
  try {
    body = await res.json();
  } catch {
    // レスポンスボディが無い/JSONでない場合はステータスコードだけで判断する。
  }

  return {
    success: Boolean(body.success),
    message: body.message ?? (res.ok ? "" : `決済に失敗しました(HTTP ${res.status})`),
    closedCount: body.closed_count ?? 0,
  };
}
