/**
 * Shared data shapes for the ARTEMIS X dashboard.
 *
 * These mirror the concepts already used on the Python/EA side of ARTEMIS
 * (ai_engine.Signal, market_feed.MarketSnapshot, order_executor.OrderResult)
 * so that swapping the mock API in src/api/client.ts for real calls against
 * a future backend does not require reshaping the UI layer.
 */

export type AiAction = "BUY" | "SELL" | "WAIT";

export type AiState = "IDLE" | "ANALYZING" | "MONITORING" | "TRADING";

export type BotRunState = "RUNNING" | "STOPPED" | "EMERGENCY_STOPPED";

export interface AiStatus {
  action: AiAction;
  confidence: number; // 0-100
  reason: string;
  symbol: string;
  timeframe: string;
  updatedAt: string; // ISO timestamp
}

export interface ProfitPoint {
  date: string; // ISO date
  value: number;
}

export interface MonthlyProfitPoint {
  month: string; // "2026-06"
  value: number;
}

// --- 実際にPython側(config.json)へ反映される売買設定 -----------------------
// settings_schema.py(Python)のFIELDSと1:1で対応する。フィールドを追加・
// 変更する場合はPython側と両方直すこと。

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";

export type EntryStrictness = "conservative" | "balanced" | "aggressive";

// rule_based(ヒューリスティック) / openai / claude(いずれもLLM API連携、
// 実際に利用ごとに料金が発生する)。APIキー自体はセキュリティ上の理由で
// Dashboardには出さず.envでのみ設定するため、ここにキーのフィールドは無い。
export type AiEngineChoice = "rule_based" | "openai" | "claude";

export interface TradingSettings {
  ORDER_VOLUME: number;
  SL_POINTS: number;
  TP_POINTS: number;
  MAX_CONCURRENT_POSITIONS: number;
  TIMEFRAME: Timeframe;
  LOOP_INTERVAL_SECONDS: number;
  RSI_OVERBOUGHT: number;
  RSI_OVERSOLD: number;
  EMA_FAST_PERIOD: number;
  EMA_SLOW_PERIOD: number;
  ENTRY_STRICTNESS: EntryStrictness;
  ENABLE_ORDERS: boolean;
  DEMO_ONLY: boolean;
  DISCORD_ENABLED: boolean;
  DISCORD_WEBHOOK_URL: string;
  DISCORD_NOTIFY_ON_TRADE: boolean;
  DISCORD_NOTIFY_ON_ERROR: boolean;
  DISCORD_NOTIFY_DAILY_SUMMARY: boolean;
  BOT_RUN_STATE: BotRunState;
  AI_ENGINE: AiEngineChoice;
}

// --- 実際にPython側(account_feed.py経由でEAが書き出すJSON)から取得する
// 残高・ポジション情報。settings_server.pyの GET /api/account のレスポンス
// (dataclasses.asdict()の出力)と1:1で対応するため、あえてキー名を
// Python側と揃えている(snake_case)。

export interface RealAccountInfo {
  login: number;
  currency: string;
  balance: number;
  equity: number;
  margin: number;
  margin_free: number;
  profit: number;
}

export interface RealPosition {
  ticket: number;
  symbol: string;
  type: "BUY" | "SELL";
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  open_time: number; // unix seconds
  magic: number;
  is_artemis: boolean;
}

export interface AccountState {
  account: RealAccountInfo;
  positions: RealPosition[];
  target_symbol: string;
}

// --- 実際にPython側(ai_status.py経由でmain.pyが書き出すJSON)から取得する
// 最新のAI判断。settings_server.pyの GET /api/ai-status のレスポンスと
// 1:1で対応する(snake_case)。

export interface RealAiStatus {
  action: AiAction;
  confidence: number;
  reason: string;
  symbol: string;
  timeframe: string;
  updated_at: number; // unix seconds
}

// --- 実際にPython側(trade_history_feed.py経由でEAが書き出すJSON)から
// 取得する決済済み取引一覧。settings_server.pyの GET /api/trade-history の
// レスポンスと1:1で対応する(snake_case)。AIの判断理由はMT5側が知らない
// ため含まれない(直近の判断理由が必要な場合はRealAiStatusを参照)。

export interface RealClosedTrade {
  position_id: number;
  symbol: string;
  type: "BUY" | "SELL";
  volume: number;
  price_open: number;
  price_close: number;
  profit: number;
  open_time: number; // unix seconds
  close_time: number; // unix seconds
  magic: number;
  is_artemis: boolean;
}

// --- ここから下はまだUIモックの設定(バックエンドと未接続) -------------------
// Discordの設定(enabled/webhookUrl/notifyOnTrade/notifyOnError/
// notifyOnDailySummary)とAI判断エンジン選択(engine)はすべて
// TradingSettings(DISCORD_*/AI_ENGINE)へ移動し実際に接続済みのため、
// ここにはもう残っていない。

export interface VpsSettings {
  host: string;
  status: "connected" | "disconnected";
  uptimeHours: number;
}

export interface Mt5Settings {
  // server/accountLogin/symbolはまだ読み取り専用の参考表示(未接続)。
  // timeframe/demoOnlyはTradingSettingsへ移動した(実際に反映される)。
  server: string;
  accountLogin: string;
  symbol: string;
}

export interface SettingsState {
  vps: VpsSettings;
  mt5: Mt5Settings;
}
