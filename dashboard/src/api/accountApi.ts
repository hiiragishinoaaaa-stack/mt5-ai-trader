/**
 * settings_server.py(Python)の GET /api/account への実際のHTTPクライアント。
 * EA(ARTEMIS_Bridge.mq5)が書き出す残高・証拠金・保有ポジションを取得する。
 *
 * MT5側がまだデータを書き出していない(EA未起動・市場クローズ直後等)場合、
 * サーバーは503を返す。これは接続エラーとは区別し、「データ待ち」として扱う。
 */
import type { AccountState } from "../types";
import { apiBaseUrl, authHeaders } from "./botApiClient";

export class AccountApiError extends Error {}

/** MT5/EA側がまだ口座情報を書き出していない場合に送出される(接続エラーとは区別する)。 */
export class AccountDataUnavailableError extends Error {}

export async function fetchAccountState(): Promise<AccountState> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/account`, {
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw new AccountApiError(
      `設定サーバーに接続できません(${apiBaseUrl()})。settings_server.pyが起動しているか確認してください。`,
      { cause: err },
    );
  }

  if (res.status === 503) {
    const body = await res.json().catch(() => ({ error: "MT5からの口座情報がまだ届いていません" }));
    throw new AccountDataUnavailableError(body.error ?? "MT5からの口座情報がまだ届いていません");
  }

  if (!res.ok) {
    throw new AccountApiError(`口座情報の取得に失敗しました(HTTP ${res.status})`);
  }

  return (await res.json()) as AccountState;
}
