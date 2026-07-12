/**
 * Mock data seam for the parts of the ARTEMIS X dashboard not yet connected to
 * a real backend: bot process control (Start/Stop/Emergency Stop) and the
 * remaining Settings sections (VPS/AI engine選択/MT5参考情報/日次サマリー)。
 *
 * Home/Trade/AnalyticsのAI判断・残高・ポジション・取引履歴は、それぞれ
 * src/api/accountApi.ts・aiStatusApi.ts・tradeHistoryApi.ts経由で
 * settings_server.py(Python)から実データを取得しており、ここは通らない。
 */
import type { BotRunState, SettingsState } from "../types";
import { mockSettings } from "../data/mock";

const LATENCY_MS = 350;

function resolveAfterDelay<T>(value: T, ms = LATENCY_MS): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), ms);
  });
}

// In-memory mutable state so Start / Stop / Emergency Stop feel alive in the
// mock without a backend. Resets on page reload — that's expected for a UI mock.
let botState: BotRunState = "RUNNING";

export async function getBotState(): Promise<BotRunState> {
  return resolveAfterDelay(botState);
}

export async function getSettings(): Promise<SettingsState> {
  return resolveAfterDelay(mockSettings);
}

export async function updateSettings(next: SettingsState): Promise<SettingsState> {
  // UIモックのため永続化はしない(リロードするとmockSettingsに戻る)。
  return resolveAfterDelay(next, 200);
}

export async function startBot(): Promise<BotRunState> {
  botState = "RUNNING";
  return resolveAfterDelay(botState, 250);
}

export async function stopBot(): Promise<BotRunState> {
  botState = "STOPPED";
  return resolveAfterDelay(botState, 250);
}

export async function emergencyStopBot(): Promise<BotRunState> {
  botState = "EMERGENCY_STOPPED";
  return resolveAfterDelay(botState, 250);
}
