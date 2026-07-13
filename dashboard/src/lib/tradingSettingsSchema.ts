/**
 * TradingSettingsのクライアント側バリデーション。
 *
 * Python側の唯一の正はmt5_ai_trader/settings_schema.pyで、ここにある
 * 範囲・選択肢はそれをUI用に写したもの(即座にエラー表示するための下見)。
 * 実際の保存の可否は必ずPython側(POST /api/settings)の判定が最終決定になる
 * ため、両者がずれても壊れることはない(サーバー側のエラーも画面に表示する)。
 */
import type { AiEngineChoice, AvailableSymbol, EntryStrictness, Timeframe, TradingSettings } from "../types";

interface FieldRange {
  min: number;
  max: number;
}

export const NUMERIC_RANGES: Record<string, FieldRange> = {
  ORDER_VOLUME: { min: 0.01, max: 100 },
  SL_POINTS: { min: 0, max: 100_000 },
  TP_POINTS: { min: 0, max: 100_000 },
  MAX_CONCURRENT_POSITIONS: { min: 1, max: 10 },
  LOOP_INTERVAL_SECONDS: { min: 5, max: 86_400 },
  RSI_OVERBOUGHT: { min: 50, max: 100 },
  RSI_OVERSOLD: { min: 0, max: 50 },
  EMA_FAST_PERIOD: { min: 1, max: 500 },
  EMA_SLOW_PERIOD: { min: 2, max: 1000 },
};

export const TIMEFRAME_OPTIONS: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export const AI_ENGINE_LABELS: Record<AiEngineChoice, string> = {
  rule_based: "Rule-based",
  openai: "OpenAI",
  claude: "Claude",
};

// Python側のsettings_schema.AVAILABLE_SYMBOLSと1:1で対応する(唯一の正は
// Python側)。新しい銘柄を追加する場合は両方に追記し、MT5側にその銘柄用の
// EAインスタンスを追加する。
export const AVAILABLE_SYMBOLS: AvailableSymbol[] = ["USDJPY", "EURUSD"];

export const ENTRY_STRICTNESS_PRESETS: Record<
  EntryStrictness,
  { label: string; description: string; RSI_OVERBOUGHT: number; RSI_OVERSOLD: number }
> = {
  conservative: {
    label: "Conservative",
    description: "エントリー条件が厳しめ。取引回数は少なくなる",
    RSI_OVERBOUGHT: 65,
    RSI_OVERSOLD: 35,
  },
  balanced: {
    label: "Balanced",
    description: "標準的な条件(既定値)",
    RSI_OVERBOUGHT: 70,
    RSI_OVERSOLD: 30,
  },
  aggressive: {
    label: "Aggressive",
    description: "エントリー条件が緩め。取引回数は多くなる",
    RSI_OVERBOUGHT: 80,
    RSI_OVERSOLD: 20,
  },
};

export type ValidationErrors = Partial<Record<keyof TradingSettings, string>>;

export function validateTradingSettingsDraft(draft: TradingSettings): ValidationErrors {
  const errors: ValidationErrors = {};

  for (const [key, range] of Object.entries(NUMERIC_RANGES)) {
    const value = draft[key as keyof TradingSettings] as number;
    if (typeof value !== "number" || Number.isNaN(value)) {
      errors[key as keyof TradingSettings] = "数値を入力してください";
      continue;
    }
    if (value < range.min || value > range.max) {
      errors[key as keyof TradingSettings] = `${range.min}〜${range.max}の範囲で入力してください`;
    }
  }

  if (!errors.RSI_OVERBOUGHT && !errors.RSI_OVERSOLD && draft.RSI_OVERBOUGHT <= draft.RSI_OVERSOLD) {
    errors.RSI_OVERBOUGHT = "RSI OverboughtはRSI Oversoldより大きい値にしてください";
  }
  if (!errors.EMA_FAST_PERIOD && !errors.EMA_SLOW_PERIOD && draft.EMA_FAST_PERIOD >= draft.EMA_SLOW_PERIOD) {
    errors.EMA_FAST_PERIOD = "EMA FastはEMA Slowより小さい値にしてください";
  }

  return errors;
}
