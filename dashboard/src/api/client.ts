/**
 * Mock data seam for the parts of the ARTEMIS X dashboard not yet connected to
 * a real backend: the remaining Settings sections
 * (VPS/AI engine選択/MT5参考情報/日次サマリー)。
 *
 * Home/Trade/AnalyticsのAI判断・残高・ポジション・取引履歴・BOT_RUN_STATEは、
 * それぞれ src/api/accountApi.ts・aiStatusApi.ts・tradeHistoryApi.ts・
 * settingsApi.ts経由でsettings_server.py(Python)から実データを取得しており、
 * ここは通らない。
 */
import type { SettingsState } from "../types";
import { mockSettings } from "../data/mock";

const LATENCY_MS = 350;

function resolveAfterDelay<T>(value: T, ms = LATENCY_MS): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), ms);
  });
}

export async function getSettings(): Promise<SettingsState> {
  return resolveAfterDelay(mockSettings);
}

export async function updateSettings(next: SettingsState): Promise<SettingsState> {
  // UIモックのため永続化はしない(リロードするとmockSettingsに戻る)。
  return resolveAfterDelay(next, 200);
}
