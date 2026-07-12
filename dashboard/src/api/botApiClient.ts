/**
 * settings_server.py(Python)への接続設定を一箇所にまとめたもの。
 * settingsApi.ts / accountApi.ts の両方から共有される。
 */
const DEFAULT_API_URL = "http://localhost:8787";

export function apiBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_SETTINGS_API_URL;
  return fromEnv && fromEnv.trim() !== "" ? fromEnv.replace(/\/+$/, "") : DEFAULT_API_URL;
}

export function authHeaders(): Record<string, string> {
  const token = import.meta.env.VITE_SETTINGS_API_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
