/**
 * Static mock data for the UI-only ARTEMIS X dashboard.
 *
 * Nothing here talks to MT5, the EA bridge, or the Python bot — it exists so
 * every screen has something believable to render. See src/api/client.ts for
 * the seam where this gets swapped for real data later.
 */
import type {
  AiStatus,
  AnalyticsSummary,
  HomeSummary,
  MonthlyProfitPoint,
  OpenPosition,
  OrderHistoryItem,
  ProfitPoint,
  SettingsState,
} from "../types";

const isoDaysAgo = (days: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
};

const dateDaysAgo = (days: number): string => isoDaysAgo(days).slice(0, 10);

export const mockAiStatus: AiStatus = {
  action: "BUY",
  confidence: 94,
  reason: "上昇トレンド + MACD陽転 + RSI過熱なし",
  symbol: "USDJPY",
  timeframe: "M15",
  updatedAt: new Date().toISOString(),
};

export const mockPosition: OpenPosition = {
  id: "pos-8841",
  symbol: "USDJPY",
  side: "BUY",
  volume: 0.01,
  entryPrice: 157.123,
  currentPrice: 157.412,
  sl: 155.123,
  tp: 159.123,
  profit: 2890,
  openedAt: isoDaysAgo(0),
};

export const mockHomeSummary: HomeSummary = {
  botState: "RUNNING",
  aiState: "ANALYZING",
  todaysProfit: 12480,
  balance: 1284650,
  currentSymbol: "USDJPY",
  winRate: 68,
  position: mockPosition,
};

const REASONS = [
  "上昇トレンド + MACD陽転 + RSI過熱なし",
  "下降トレンド + MACD陰転 + RSI売られすぎなし",
  "トレンド・モメンタムの条件が揃っていません",
  "上昇トレンド継続 + 出来高増加を確認",
  "レンジ相場のためポジション見送り",
];

export const mockOrderHistory: OrderHistoryItem[] = [
  {
    id: "ord-1042",
    symbol: "USDJPY",
    side: "BUY",
    volume: 0.01,
    entryPrice: 156.812,
    exitPrice: 157.244,
    profit: 4320,
    aiReason: REASONS[0],
    openedAt: isoDaysAgo(0.4),
    closedAt: isoDaysAgo(0.2),
  },
  {
    id: "ord-1041",
    symbol: "USDJPY",
    side: "SELL",
    volume: 0.01,
    entryPrice: 157.55,
    exitPrice: 157.21,
    profit: 3400,
    aiReason: REASONS[1],
    openedAt: isoDaysAgo(1.1),
    closedAt: isoDaysAgo(0.9),
  },
  {
    id: "ord-1040",
    symbol: "USDJPY",
    side: "BUY",
    volume: 0.01,
    entryPrice: 156.98,
    exitPrice: 156.71,
    profit: -2700,
    aiReason: REASONS[3],
    openedAt: isoDaysAgo(1.8),
    closedAt: isoDaysAgo(1.6),
  },
  {
    id: "ord-1039",
    symbol: "USDJPY",
    side: "BUY",
    volume: 0.01,
    entryPrice: 156.4,
    exitPrice: 156.9,
    profit: 5000,
    aiReason: REASONS[0],
    openedAt: isoDaysAgo(2.5),
    closedAt: isoDaysAgo(2.3),
  },
  {
    id: "ord-1038",
    symbol: "USDJPY",
    side: "SELL",
    volume: 0.01,
    entryPrice: 156.9,
    exitPrice: 157.05,
    profit: -1500,
    aiReason: REASONS[4],
    openedAt: isoDaysAgo(3.2),
    closedAt: isoDaysAgo(3.0),
  },
];

const DAILY_PROFIT_SEQUENCE = [
  1200, -800, 2400, 3100, -500, 1800, 4200, 900, -1200, 2600, 3400, -700, 1600, 2100,
];

export const mockDailyProfit: ProfitPoint[] = DAILY_PROFIT_SEQUENCE.map((value, index) => ({
  date: dateDaysAgo(DAILY_PROFIT_SEQUENCE.length - 1 - index),
  value,
}));

export const mockProfitCurve: ProfitPoint[] = (() => {
  let cumulative = 980000;
  const points: ProfitPoint[] = [];
  const sequence = [
    600, 1200, -400, 2100, 1800, -900, 2600, 3200, -600, 1400, 2200, 800, -1100, 2900, 3400,
    -500, 1600, 2100, 2800, -1300, 900, 3600, 2200, -700, 1800, 2400, 3100, -900, 2000, 2480,
  ];
  sequence.forEach((delta, index) => {
    cumulative += delta;
    points.push({ date: dateDaysAgo(sequence.length - 1 - index), value: cumulative });
  });
  return points;
})();

export const mockMonthlyProfit: MonthlyProfitPoint[] = [
  { month: "2026-02", value: 38400 },
  { month: "2026-03", value: -6200 },
  { month: "2026-04", value: 52100 },
  { month: "2026-05", value: 41800 },
  { month: "2026-06", value: 60200 },
  { month: "2026-07", value: 24480 },
];

export const mockAnalyticsSummary: AnalyticsSummary = {
  profitCurve: mockProfitCurve,
  dailyProfit: mockDailyProfit,
  monthlyProfit: mockMonthlyProfit,
  winRate: 68,
  profitFactor: 1.82,
  maxDrawdown: -18400,
  averageProfit: 1640,
  totalTrades: 142,
};

export const mockSettings: SettingsState = {
  discord: {
    enabled: true,
    webhookUrl: "https://discord.com/api/webhooks/••••••••/••••••••",
    notifyOnTrade: true,
    notifyOnError: true,
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
