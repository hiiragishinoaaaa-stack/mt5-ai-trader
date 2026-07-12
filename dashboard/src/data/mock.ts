/**
 * Static mock data for the parts of the ARTEMIS X dashboard that are not yet
 * connected to a real backend (VPS/AI engine選択/MT5参考情報/日次サマリー通知)。
 * Home/Trade/Analyticsの主要な数値はすべて実データ(settings_server.py経由)
 * に置き換わっているため、ここにはそれ以外の未接続項目のみを残している。
 */
import type { SettingsState } from "../types";

export const mockSettings: SettingsState = {
  discord: {
    notifyOnDailySummary: false,
  },
  vps: {
    host: "artemis-vps-01.example.com",
    status: "disconnected",
    uptimeHours: 0,
  },
  ai: {
    engine: "rule_based",
  },
  mt5: {
    server: "XMTrading-MT53",
    accountLogin: "75575711",
    symbol: "USDJPY",
  },
};
