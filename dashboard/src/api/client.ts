/**
 * The single seam between the UI and its data source.
 *
 * Every function here currently resolves mock data (src/data/mock.ts) after a
 * short simulated delay, which also lets screens show a real loading state
 * instead of a permanent flash of empty content. When ARTEMIS grows a real
 * backend — most likely a small HTTP layer reading the same JSON files /
 * SQLite database the Python bot and EA bridge already write — only this
 * file needs to change. Pages and components should always import from
 * here, never from src/data/mock.ts directly.
 */
import type { AiStatus, AnalyticsSummary, BotRunState, HomeSummary, SettingsState, TradeSnapshot } from "../types";
import {
  mockAiStatus,
  mockAnalyticsSummary,
  mockHomeSummary,
  mockOrderHistory,
  mockPosition,
  mockSettings,
} from "../data/mock";

const LATENCY_MS = 350;

function resolveAfterDelay<T>(value: T, ms = LATENCY_MS): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), ms);
  });
}

// In-memory mutable state so Start / Stop / Emergency Stop feel alive in the
// mock without a backend. Resets on page reload — that's expected for a UI mock.
let botState: BotRunState = mockHomeSummary.botState;

export async function getHomeSummary(): Promise<HomeSummary> {
  const hasPosition = botState === "RUNNING";
  return resolveAfterDelay({
    ...mockHomeSummary,
    botState,
    position: hasPosition ? mockPosition : null,
  });
}

export async function getAiStatus(): Promise<AiStatus> {
  return resolveAfterDelay(mockAiStatus);
}

export async function getTradeSnapshot(): Promise<TradeSnapshot> {
  return resolveAfterDelay({
    position: botState === "RUNNING" ? mockPosition : null,
    aiStatus: mockAiStatus,
    history: mockOrderHistory,
  });
}

export async function getAnalyticsSummary(): Promise<AnalyticsSummary> {
  return resolveAfterDelay(mockAnalyticsSummary);
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
