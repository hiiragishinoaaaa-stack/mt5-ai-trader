/**
 * TradingSettingsのクライアント側バリデーション。
 *
 * Python側の唯一の正はmt5_ai_trader/settings_schema.pyで、ここにある
 * 範囲・選択肢はそれをUI用に写したもの(即座にエラー表示するための下見)。
 * 実際の保存の可否は必ずPython側(POST /api/settings)の判定が最終決定になる
 * ため、両者がずれても壊れることはない(サーバー側のエラーも画面に表示する)。
 */
import type {
  AiEngineChoice,
  AvailableSymbol,
  EntryStrictness,
  StopMode,
  Timeframe,
  TradingSettings,
} from "../types";

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
  RSI_PERIOD: { min: 2, max: 200 },
  ATR_PERIOD: { min: 2, max: 200 },
  RSI_BUY_MIN: { min: 0, max: 100 },
  RSI_BUY_MAX: { min: 0, max: 100 },
  RSI_SELL_MIN: { min: 0, max: 100 },
  RSI_SELL_MAX: { min: 0, max: 100 },
  REQUIRED_SCORE: { min: 0, max: 13 },
  ADX_TREND_THRESHOLD: { min: 0, max: 100 },
  MAX_SPREAD_POINTS: { min: 0, max: 100_000 },
  ATR_MIN_POINTS: { min: 0, max: 100_000 },
  ATR_SL_MULTIPLIER: { min: 0.1, max: 20 },
  ATR_TP_MULTIPLIER: { min: 0.1, max: 20 },
  BROKER_MIN_STOP_POINTS: { min: 0, max: 100_000 },
  ENTRY_COOLDOWN_SECONDS: { min: 0, max: 86_400 },
  MAX_TRADES_PER_HOUR: { min: 0, max: 1000 },
  MAX_TRADES_PER_DAY: { min: 0, max: 10_000 },
  MAX_DAILY_LOSS_PERCENT: { min: 0, max: 100 },
  LOSS_STREAK_THRESHOLD: { min: 1, max: 20 },
  COOLDOWN_AFTER_LOSSES_MINUTES: { min: 0, max: 1440 },
};

export const TIMEFRAME_OPTIONS: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export const STOP_MODE_OPTIONS: StopMode[] = ["fixed", "atr"];

export const AI_ENGINE_LABELS: Record<AiEngineChoice, string> = {
  rule_based: "Rule-based",
  openai: "OpenAI",
  claude: "Claude",
  gemini: "Gemini",
};

// Python側のsettings_schema.AVAILABLE_SYMBOLSと1:1で対応する(唯一の正は
// Python側)。新しい銘柄を追加する場合は両方に追記し、MT5側にその銘柄用の
// EAインスタンスを追加する。
export const AVAILABLE_SYMBOLS: AvailableSymbol[] = ["USDJPY", "EURUSD"];

// Python側のsettings_schema.ENTRY_STRICTNESS_PRESETSと1:1で対応する
// (唯一の正はPython側)。選択すると、これらのキーがまとめてdraftへ反映
// される(RuleBasedAIEngineが必須条件+加点スコアリング方式でBUY/SELL/WAIT
// を判断する。details/optionalKeysの説明はPython側README「複数銘柄対応」の
// 後、「M5アクティブ運用」セクションを参照)。
export const ENTRY_STRICTNESS_PRESETS: Record<
  EntryStrictness,
  {
    label: string;
    description: string;
    RSI_BUY_MIN: number;
    RSI_BUY_MAX: number;
    RSI_SELL_MIN: number;
    RSI_SELL_MAX: number;
    REQUIRED_SCORE: number;
    REQUIRE_NO_NEW_EXTREME_5BARS: boolean;
    extra?: Partial<TradingSettings>;
  }
> = {
  conservative: {
    label: "Conservative",
    description: "RSI帯域が狭く、必要スコアも高め(9点)。取引回数は少なくなる",
    RSI_BUY_MIN: 52,
    RSI_BUY_MAX: 62,
    RSI_SELL_MIN: 38,
    RSI_SELL_MAX: 48,
    REQUIRED_SCORE: 9,
    REQUIRE_NO_NEW_EXTREME_5BARS: true,
  },
  balanced: {
    label: "Balanced",
    description: "標準的な条件(既定値、必要スコア7点)",
    RSI_BUY_MIN: 50,
    RSI_BUY_MAX: 65,
    RSI_SELL_MIN: 35,
    RSI_SELL_MAX: 50,
    REQUIRED_SCORE: 7,
    REQUIRE_NO_NEW_EXTREME_5BARS: false,
  },
  aggressive: {
    label: "Aggressive",
    description: "エントリー条件が緩め(必要スコア5点)。取引回数は多くなる",
    RSI_BUY_MIN: 45,
    RSI_BUY_MAX: 75,
    RSI_SELL_MIN: 25,
    RSI_SELL_MAX: 55,
    REQUIRED_SCORE: 5,
    REQUIRE_NO_NEW_EXTREME_5BARS: false,
  },
  active_m5: {
    label: "Active M5",
    description: "USDJPY・M5での積極運用向け。TIMEFRAME/EMA/ATRベースSL・TP・クールダウン・取引数上限もまとめて切り替わる",
    RSI_BUY_MIN: 48,
    RSI_BUY_MAX: 68,
    RSI_SELL_MIN: 32,
    RSI_SELL_MAX: 52,
    REQUIRED_SCORE: 6,
    REQUIRE_NO_NEW_EXTREME_5BARS: false,
    extra: {
      TIMEFRAME: "M5",
      EMA_FAST_PERIOD: 20,
      EMA_SLOW_PERIOD: 50,
      RSI_PERIOD: 14,
      ATR_PERIOD: 14,
      LOOP_INTERVAL_SECONDS: 30,
      ENTRY_COOLDOWN_SECONDS: 600,
      MAX_CONCURRENT_POSITIONS: 1,
      MAX_TRADES_PER_HOUR: 2,
      MAX_TRADES_PER_DAY: 12,
      STOP_MODE: "atr",
      ATR_SL_MULTIPLIER: 1.2,
      ATR_TP_MULTIPLIER: 1.8,
    },
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
  if (!errors.RSI_BUY_MIN && !errors.RSI_BUY_MAX && draft.RSI_BUY_MIN >= draft.RSI_BUY_MAX) {
    errors.RSI_BUY_MIN = "RSI BUY MinはRSI BUY Maxより小さい値にしてください";
  }
  if (!errors.RSI_SELL_MIN && !errors.RSI_SELL_MAX && draft.RSI_SELL_MIN >= draft.RSI_SELL_MAX) {
    errors.RSI_SELL_MIN = "RSI SELL MinはRSI SELL Maxより小さい値にしてください";
  }

  return errors;
}
