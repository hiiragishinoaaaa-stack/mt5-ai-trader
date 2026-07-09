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
  engine: "rule_based" | "openai" | "claude";
  riskLevel: "low" | "medium" | "high";
  autoTradeEnabled: boolean;
}

export interface RiskSettings {
  lotSize: number;
  maxDailyLossPercent: number;
  maxPositions: number;
  slPoints: number;
  tpPoints: number;
}

export interface Mt5Settings {
  server: string;
  accountLogin: string;
  symbol: string;
  timeframe: string;
  demoOnly: boolean;
}

export interface SettingsState {
  discord: DiscordSettings;
  vps: VpsSettings;
  ai: AiSettings;
  risk: RiskSettings;
  mt5: Mt5Settings;
}
