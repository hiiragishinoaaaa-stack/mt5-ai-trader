/**
 * Static mock data for the parts of the ARTEMIS X dashboard that are not yet
 * connected to a real backend (VPS/MT5参考情報)。
 * Home/Trade/Analyticsの主要な数値、Discord通知の設定、AI判断エンジン選択は
 * すべて実データ(settings_server.py経由)に置き換わっているため、ここには
 * それ以外の未接続項目のみを残している。
 */
import type { SettingsState } from "../types";

export const mockSettings: SettingsState = {
  vps: {
    host: "artemis-vps-01.example.com",
    status: "disconnected",
    uptimeHours: 0,
  },
  mt5: {
    server: "XMTrading-MT53",
    accountLogin: "75575711",
    symbol: "USDJPY",
  },
};
