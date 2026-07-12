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

export interface OpenPosition {
  id: string;
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  entryPrice: number;
  currentPrice: number;
  sl: number;
  tp: number;
  profit: number;
  openedAt: string;
}

export interface HomeSummary {
  botState: BotRunState;
  aiState: AiState;
  todaysProfit: number;
  balance: number;
  currentSymbol: string;
  winRate: number; // 0-100
  position: OpenPosition | null;
}

export interface OrderHistoryItem {
  id: string;
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  entryPrice: number;
  exitPrice: number;
  profit: number;
  aiReason: string;
  openedAt: string;
  closedAt: string;
}

export interface TradeSnapshot {
  position: OpenPosition | null;
  aiStatus: AiStatus;
  history: OrderHistoryItem[];
}

export interface ProfitPoint {
  date: string; // ISO date
  value: number;
}

export interface MonthlyProfitPoint {
  month: string; // "2026-06"
  value: number;
}

export interface AnalyticsSummary {
  profitCurve: ProfitPoint[];
  dailyProfit: ProfitPoint[];
  monthlyProfit: MonthlyProfitPoint[];
  winRate: number;
  profitFactor: number;
  maxDrawdown: number;
  averageProfit: number;
  totalTrades: number;
}

// --- 実際にPython側(config.json)へ反映される売買設定 -----------------------
// settings_schema.py(Python)のFIELDSと1:1で対応する。フィールドを追加・
// 変更する場合はPython側と両方直すこと。

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";

export type EntryStrictness = "conservative" | "balanced" | "aggressive";

export interface TradingSettings {
  ORDER_VOLUME: number;
  SL_POINTS: number;
  TP_POINTS: number;
  TIMEFRAME: Timeframe;
  LOOP_INTERVAL_SECONDS: number;
  RSI_OVERBOUGHT: number;
  RSI_OVERSOLD: number;
  EMA_FAST_PERIOD: number;
  EMA_SLOW_PERIOD: number;
  ENTRY_STRICTNESS: EntryStrictness;
  ENABLE_ORDERS: boolean;
  DEMO_ONLY: boolean;
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

// --- ここから下はまだUIモックの設定(バックエンドと未接続) -------------------

export interface DiscordSettings {
  enabled: boolean;
  webhookUrl: string;
  notifyOnTrade: boolean;
  notifyOnError: boolean;
  notifyOnDailySummary: boolean;
}

export interface VpsSettings {
  host: string;
  status: "connected" | "disconnected";
  uptimeHours: number;
}

export interface AiSettings {
  // riskLevel/autoTradeEnabledはTradingSettings(ENTRY_STRICTNESS/ENABLE_ORDERS)
  // に置き換わったため、ここにはまだ実バックエンドが無いエンジン選択のみ残す。
  engine: "rule_based" | "openai" | "claude";
}

export interface Mt5Settings {
  // server/accountLogin/symbolはまだ読み取り専用の参考表示(未接続)。
  // timeframe/demoOnlyはTradingSettingsへ移動した(実際に反映される)。
  server: string;
  accountLogin: string;
  symbol: string;
}

export interface SettingsState {
  discord: DiscordSettings;
  vps: VpsSettings;
  ai: AiSettings;
  mt5: Mt5Settings;
}
