/**
 * settings_server.py(Python)への実際のHTTPクライアント。
 *
 * dashboard/src/api/client.ts の他の関数(Home/Trade/Analytics)とは異なり、
 * ここだけはモックではなく本物のfetch()でPythonの設定API(GET/POST
 * /api/settings)と通信する。ARTEMIS X DashboardのSettings画面のうち、
 * 「売買設定(TradingSettings)」だけが現時点でPython側と実際に繋がっている。
 *
 * 接続先は Vite の環境変数で指定する(dashboard/.env.local等):
 *   VITE_SETTINGS_API_URL=http://<PCのLAN IP>:8787
 * 未設定の場合は http://localhost:8787 を使う(PC上のブラウザから開く場合のみ
 * 有効。スマホから開く場合は必ずPCのLAN IPを設定すること。README参照)。
 */
import type { TradingSettings } from "../types";

const DEFAULT_API_URL = "http://localhost:8787";

function apiBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_SETTINGS_API_URL;
  return fromEnv && fromEnv.trim() !== "" ? fromEnv.replace(/\/+$/, "") : DEFAULT_API_URL;
}

function authHeaders(): Record<string, string> {
  const token = import.meta.env.VITE_SETTINGS_API_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class SettingsApiError extends Error {}

/** 現在Pythonが使っている売買設定を取得する。 */
export async function fetchTradingSettings(): Promise<TradingSettings> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/settings`, {
      headers: { ...authHeaders() },
    });
  } catch (err) {
    throw new SettingsApiError(
      `設定サーバーに接続できません(${apiBaseUrl()})。settings_server.pyが起動しているか確認してください。`,
      { cause: err },
    );
  }

  if (!res.ok) {
    throw new SettingsApiError(`設定の取得に失敗しました(HTTP ${res.status})`);
  }

  const body = (await res.json()) as { settings: TradingSettings };
  return body.settings;
}

export interface SaveTradingSettingsResult {
  success: boolean;
  settings?: TradingSettings;
  errors?: Record<string, string>;
  message?: string;
}

/** 変更された項目だけを送信する。範囲外の値はPython側(settings_schema.py)で拒否される。 */
export async function saveTradingSettings(payload: Partial<TradingSettings>): Promise<SaveTradingSettingsResult> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      success: false,
      message: `設定サーバーに接続できません(${apiBaseUrl()})。settings_server.pyが起動しているか確認してください。`,
    };
  }

  let body: { success?: boolean; settings?: TradingSettings; errors?: Record<string, string> } = {};
  try {
    body = await res.json();
  } catch {
    // レスポンスボディが無い/JSONでない場合はステータスコードだけで判断する。
  }

  if (!res.ok) {
    return {
      success: false,
      errors: body.errors,
      message: body.errors?._ ?? `保存に失敗しました(HTTP ${res.status})`,
    };
  }

  return { success: true, settings: body.settings };
}
