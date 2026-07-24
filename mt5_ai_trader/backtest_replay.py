"""RuleBasedAIEngineのスコアロジックを過去のローソク足に対してオフラインで
再生し、REQUIRED_SCOREごとの成績(取引数・勝率・期待値・最大DD)を比較する
バックテストツール(2026-07、Fable5との相談を踏まえて追加)。

`ai_decisions.jsonl`(ai_status.append_decision_log参照)は「今日から先」
しか貯まらないため、M15足だと閾値Nごとの勝率を統計的に比較できる量が
貯まるまで数週間〜数ヶ月かかる。同じスコアロジックを過去データに対して
オフラインで回せば、その期間分を今日手に入れられる。

## データの入手方法

Python側はMT5 APIを直接使わない設計(mt5.initialize()のIPCハングを避ける
ため)のため、過去足はMT5側でエクスポートする必要がある。
`ea/ARTEMIS_HistoryExport.mq5`というスクリプト(常駐EAとは別、チャートに
1回ドラッグして実行する使い切りのスクリプト)が、指定した本数のローソク足を
JSON(このモジュールがそのまま読み込める形式)でCommon\\Filesへ書き出す。
そのファイルをこのツールを実行する環境へコピーし、`--candles-file`で渡す。

## 本番との整合性(重要)

本番(main.py)は毎サイクル、直近`config.BARS_COUNT`本(既定100本)の
ローリングウィンドウだけをEAから受け取り、そのウィンドウに対して指標を
計算し直す(indicators.add_indicators)。全履歴に対して指標を1回だけ計算して
スライスする方式だと、EMA/RSI等の値が本番と異なってしまう(ewm/rollingは
系列の起点に依存するため)。そのためcompute_bar_scores()は、本番と全く同じ
ように「直近bars_count本のウィンドウ」を1バーごとに切り出し、毎回
indicators.add_indicators()し直してからRuleBasedAIEngine.decide()を呼ぶ
(計算コストは高くなるが、本番の判断を忠実に再現することを優先する)。

## 決済判定の簡略化(既知の制限)

- `config.STOP_MODE=fixed`(SL_POINTS/TP_POINTS固定)のみ対応。atrモードの
  動的SL/TPは再現していない。
- risk_manager.py(クールダウン・同時保有数上限・連敗停止等)は再現して
  いない。このツールが検証するのはあくまでRuleBasedAIEngineのスコア
  ロジック単体の期待値であり、本番の発注頻度そのものではない。
- 1本のローソク足の中でSL/TPの両方に価格が触れた場合、実際にどちらが
  先だったかはローソク足データだけでは分からない(tickデータが無いため)。
  安全側に倒すため既定ではSLを優先する(perp_grid_backtest.py[Phantom]が
  逆にTPを優先する楽観的な見積もりを採用しているのとは意図的に違う選択。
  実際のトレード判断への影響が大きいツールのため、ここでは保守的な
  見積もりを優先する。--optimistic-fillで逆にできる)。
- 常に新規1建玉のみ(MAX_CONCURRENT_POSITIONSは考慮しない)。

使い方:
  .venv/bin/python backtest_replay.py --candles-file artemis_history_USDJPY_M15.json
  .venv/bin/python backtest_replay.py --candles-file artemis_history_USDJPY_M15.json \
      --required-scores 5,6,7,8,9,10 --sl-points 200 --tp-points 400
  .venv/bin/python backtest_replay.py --candles-file artemis_history_USDJPY_M15.json \
      --decision-log-out replay_decisions.jsonl
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

import config
import indicators
from ai_engine import RuleBasedAIEngine, Signal


@dataclass
class BarScore:
    """1バー分の、本番と同一ロジックによる判断結果(全て記録、閾値の
    判定はsimulate()側で行う)。"""

    index: int
    time: pd.Timestamp
    signal: Signal

    @property
    def close(self) -> float:
        return float(self.signal.details["close"])

    @property
    def high(self) -> float:
        return float(self.signal.details["high"])

    @property
    def low(self) -> float:
        return float(self.signal.details["low"])

    @property
    def buy_score(self) -> int:
        return int(self.signal.details.get("buy_score") or 0)

    @property
    def sell_score(self) -> int:
        return int(self.signal.details.get("sell_score") or 0)


@dataclass
class ReplayTrade:
    direction: str  # "BUY" | "SELL"
    entry_index: int
    entry_time: pd.Timestamp
    entry_price: float
    exit_index: int | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    reason: str = "still_open"  # "take_profit" | "stop_loss" | "still_open"
    pnl_points: float = 0.0


@dataclass
class ReplayResult:
    required_score: int
    trades: list[ReplayTrade] = field(default_factory=list)

    @property
    def closed_trades(self) -> list[ReplayTrade]:
        return [t for t in self.trades if t.reason != "still_open"]

    @property
    def still_open_count(self) -> int:
        return len(self.trades) - len(self.closed_trades)

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.pnl_points > 0)
        return wins / len(closed) * 100

    @property
    def expectancy_points(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        return statistics.fmean(t.pnl_points for t in closed)

    @property
    def total_pnl_points(self) -> float:
        return sum(t.pnl_points for t in self.closed_trades)

    @property
    def max_drawdown_points(self) -> float:
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.closed_trades:
            cumulative += t.pnl_points
            peak = max(peak, cumulative)
            max_dd = min(max_dd, cumulative - peak)
        return max_dd


def load_candles(path: str | Path) -> pd.DataFrame:
    """ARTEMIS_HistoryExport.mq5(または同じ最小限のスキーマを持つ
    ファイル、market data出力とも互換)が書き出したJSONを読み込み、
    indicators.add_indicators()にそのまま渡せるDataFrameへ変換する。

    market_feed.pyのFileMarketFeed.read_snapshot()と同じ変換
    (pd.to_datetime(..., unit="s"))を使う。config.EA_TIMESTAMP_
    CORRECTION_SECONDSはライブ運用時の壁時計との比較(鮮度チェック)専用
    のため、ここでは適用しない(過去データの相対的な時系列だけが必要)。
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    candles = payload["candles"]
    if not candles:
        raise ValueError(f"{path} にローソク足データがありません")

    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.sort_values("time").reset_index(drop=True)


def compute_bar_scores(candles: pd.DataFrame, bars_count: int) -> list[BarScore]:
    """本番と同じローリングウィンドウ方式で、各バー時点でのBUY/SELLスコア
    内訳を計算する(モジュールdocstring「本番との整合性」参照)。
    """
    engine = RuleBasedAIEngine()
    results: list[BarScore] = []
    n = len(candles)
    for i in range(bars_count - 1, n):
        window = candles.iloc[i - bars_count + 1 : i + 1].reset_index(drop=True)
        enriched = indicators.add_indicators(window)
        signal = engine.decide(enriched)
        if "close" not in signal.details:
            # 指標が未計算(データ不足)だった場合はスキップする
            # (ウィンドウの先頭付近でRSI/EMA等がまだNaNのケース)。
            continue
        results.append(BarScore(index=i, time=candles.iloc[i]["time"], signal=signal))
    return results


def _decide_action(bar: BarScore, required_score: int) -> str:
    """ai_engine.RuleBasedAIEngine.decide()と全く同じ閾値・同点タイブレーク
    ロジック(BUY優先)で、指定したrequired_scoreにおける方向を決める。
    """
    buy_qualifies = bar.buy_score >= required_score
    sell_qualifies = bar.sell_score >= required_score
    if buy_qualifies and (not sell_qualifies or bar.buy_score >= bar.sell_score):
        return "BUY"
    if sell_qualifies:
        return "SELL"
    return "WAIT"


def _resolve_exit(
    is_buy: bool,
    entry_price: float,
    high: float,
    low: float,
    sl_points: float,
    tp_points: float,
    point_size: float,
    optimistic_fill: bool,
) -> tuple[float, str] | None:
    """1本のバーのhigh/lowに対して、SL/TPどちらかに触れたかを判定する
    (触れていなければNone)。simulate()とgemini_shadow_report.pyの両方から
    共通で使う(決済判定の簡略化はモジュールdocstring参照)。
    """
    tp_price = entry_price + tp_points * point_size if is_buy else entry_price - tp_points * point_size
    sl_price = entry_price - sl_points * point_size if is_buy else entry_price + sl_points * point_size
    hit_tp = high >= tp_price if is_buy else low <= tp_price
    hit_sl = low <= sl_price if is_buy else high >= sl_price

    if hit_tp and hit_sl:
        return (tp_price, "take_profit") if optimistic_fill else (sl_price, "stop_loss")
    if hit_sl:
        return sl_price, "stop_loss"
    if hit_tp:
        return tp_price, "take_profit"
    return None


def simulate_trade_forward(
    bars_after: list[tuple[int, pd.Timestamp, float, float]],
    direction: str,
    entry_index: int,
    entry_time: pd.Timestamp,
    entry_price: float,
    sl_points: float,
    tp_points: float,
    point_size: float,
    optimistic_fill: bool = False,
    spread_points: float = 0.0,
) -> ReplayTrade:
    """directionでentry_priceに1件エントリーしたと仮定し、bars_after
    (エントリー後のバー、(index, time, high, low)のタプル列、古い順)に
    沿ってSL/TP先着方式で決済まで進める。決済に至らなければ
    reason="still_open"のまま返す。

    spread_points(往復スプレッド、既定0)は決済したトレードのpnl_pointsから
    差し引く(エントリーはask、決済はbidという往復のスプレッドコストの
    近似。ローソク足はmid/bid基準の1系列しか無いため、往復1回分を一律に
    引く簡略化)。決済に至らなかった建玉(still_open)には適用しない。

    simulate()(スコア閾値に基づく連続エントリーのシミュレーション)と
    gemini_shadow_report.py/backtest_audit.py(個別の1判断に対する仮想損益の
    計算)の共通処理。
    """
    is_buy = direction == "BUY"
    trade = ReplayTrade(direction=direction, entry_index=entry_index, entry_time=entry_time, entry_price=entry_price)
    for index, time, high, low in bars_after:
        exit_info = _resolve_exit(is_buy, entry_price, high, low, sl_points, tp_points, point_size, optimistic_fill)
        if exit_info is None:
            continue
        exit_price, reason = exit_info
        pnl_price = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
        trade.exit_index = index
        trade.exit_time = time
        trade.exit_price = exit_price
        trade.reason = reason
        trade.pnl_points = pnl_price / point_size - spread_points
        break
    return trade


def simulate(
    bar_scores: list[BarScore],
    required_score: int,
    sl_points: float,
    tp_points: float,
    point_size: float,
    optimistic_fill: bool = False,
    spread_points: float = 0.0,
) -> ReplayResult:
    """事前計算済みのバーごとのスコア(compute_bar_scores)に対して、
    指定したrequired_scoreでエントリーし、SL_POINTS/TP_POINTSの固定幅・
    先着方式で決済する(モジュールdocstring「決済判定の簡略化」参照)。

    optimistic_fill=Falseが既定(SL優先、保守的な見積もり)。spread_pointsは
    決済したトレードのpnlから往復スプレッド分を引く(simulate_trade_forward
    参照、既定0=未考慮)。
    """
    result = ReplayResult(required_score=required_score)
    open_trade: ReplayTrade | None = None

    for bar in bar_scores:
        if open_trade is not None:
            is_buy = open_trade.direction == "BUY"
            exit_info = _resolve_exit(
                is_buy, open_trade.entry_price, bar.high, bar.low, sl_points, tp_points, point_size, optimistic_fill
            )
            if exit_info is not None:
                exit_price, reason = exit_info
                pnl_price = (exit_price - open_trade.entry_price) if is_buy else (open_trade.entry_price - exit_price)
                open_trade.exit_index = bar.index
                open_trade.exit_time = bar.time
                open_trade.exit_price = exit_price
                open_trade.reason = reason
                open_trade.pnl_points = pnl_price / point_size - spread_points
                open_trade = None
                continue  # このバーでは決済を優先し、新規エントリーはしない

        if open_trade is None:
            action = _decide_action(bar, required_score)
            if action in ("BUY", "SELL"):
                open_trade = ReplayTrade(
                    direction=action,
                    entry_index=bar.index,
                    entry_time=bar.time,
                    entry_price=bar.close,
                )
                result.trades.append(open_trade)

    return result


def _print_report(results: list[ReplayResult]) -> None:
    print(f"{'閾値N':>6} {'件数':>5} {'勝率%':>7} {'期待値pt':>9} {'合計pt':>9} {'最大DD pt':>10} {'未決済':>6}")
    for r in sorted(results, key=lambda r: r.win_rate, reverse=True):
        print(
            f"{r.required_score:>6} {len(r.closed_trades):>5} {r.win_rate:>7.1f} "
            f"{r.expectancy_points:>+9.1f} {r.total_pnl_points:>+9.1f} "
            f"{r.max_drawdown_points:>10.1f} {r.still_open_count:>6}"
        )


def _write_decision_log(bar_scores: list[BarScore], symbol: str, timeframe: str, out_path: str) -> None:
    """ai_status.append_decision_log()と同じスキーマでJSON Lines出力する
    (実運用ログ[ai_decisions.jsonl]と突合できるように)。"""
    with open(out_path, "w", encoding="utf-8") as f:
        for bar in bar_scores:
            d = bar.signal.details
            row = {
                "timestamp": bar.time.timestamp(),
                "symbol": symbol,
                "timeframe": timeframe,
                "action": bar.signal.action,
                "confidence": bar.signal.confidence,
                "reason": bar.signal.reason,
                "required_score": d.get("required_score"),
                "buy_score": d.get("buy_score"),
                "buy_total": d.get("buy_total"),
                "buy_failed": d.get("buy_failed"),
                "sell_score": d.get("sell_score"),
                "sell_total": d.get("sell_total"),
                "sell_failed": d.get("sell_failed"),
                "adx": d.get("adx"),
                "regime": d.get("regime"),
                "open": d.get("open"),
                "close": d.get("close"),
                "high": d.get("high"),
                "low": d.get("low"),
                "ema_fast": d.get("ema_fast"),
                "ema_slow": d.get("ema_slow"),
                "rsi": d.get("rsi"),
                "macd_hist": d.get("macd_hist"),
                "atr": d.get("atr"),
                "spread": d.get("spread"),
                "h1_ema_fast": d.get("h1_ema_fast"),
                "h1_ema_slow": d.get("h1_ema_slow"),
                "h1_slope_up": d.get("h1_slope_up"),
                "h1_bars": d.get("h1_bars"),
            }
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def _parse_int_list(raw: str) -> list[int]:
    return [int(v.strip()) for v in raw.split(",") if v.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RuleBasedAIEngineのスコアロジックを過去足に対してオフライン再生するバックテストツール"
    )
    parser.add_argument("--candles-file", required=True, help="ARTEMIS_HistoryExport.mq5が書き出したJSONファイル")
    parser.add_argument("--symbol", default=None, help="ログ出力用のシンボル名(既定: config.SYMBOL)")
    parser.add_argument("--timeframe", default=None, help="ログ出力用の時間足名(既定: config.TIMEFRAME)")
    parser.add_argument(
        "--bars-count",
        type=int,
        default=None,
        help="各バーの判断に使うローリングウィンドウ本数(既定: config.BARS_COUNT、本番と揃えること)",
    )
    parser.add_argument(
        "--required-scores",
        type=_parse_int_list,
        default=[3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        help="比較するREQUIRED_SCOREの一覧(カンマ区切り、既定3〜12)",
    )
    parser.add_argument("--sl-points", type=float, default=None, help="既定: config.SL_POINTS")
    parser.add_argument("--tp-points", type=float, default=None, help="既定: config.TP_POINTS")
    parser.add_argument("--point-size", type=float, default=None, help="既定: config.POINT_SIZE")
    parser.add_argument(
        "--spread-points",
        type=float,
        default=0.0,
        help="往復スプレッド(points)。決済したトレードのpnlから差し引く(既定0=未考慮。"
        "実運用ではスプレッド分だけ成績が悪化するため、実態に近づけたい場合に指定する)",
    )
    parser.add_argument(
        "--optimistic-fill",
        action="store_true",
        help="同じバーでSL/TP両方に触れた場合、TPを優先する(既定はSLを優先する保守的な見積もり)",
    )
    parser.add_argument(
        "--decision-log-out",
        default=None,
        help="指定すると、ai_decisions.jsonlと同じスキーマで全バーの判断をJSON Linesへ書き出す"
        "(--required-scoresの最初の値をREQUIRED_SCOREとして使う)",
    )
    args = parser.parse_args()

    symbol = args.symbol or config.SYMBOL
    timeframe = args.timeframe or config.TIMEFRAME
    bars_count = args.bars_count or config.BARS_COUNT
    sl_points = args.sl_points if args.sl_points is not None else config.SL_POINTS
    tp_points = args.tp_points if args.tp_points is not None else config.TP_POINTS
    point_size = args.point_size if args.point_size is not None else config.POINT_SIZE

    print(f"{args.candles_file} を読み込んでいます...")
    candles = load_candles(args.candles_file)
    print(f"{len(candles)}本のローソク足を読み込みました。ウィンドウ本数={bars_count}本でスコアを計算しています"
          "(本数が多いと数分かかることがあります)...")

    original_required_score = config.REQUIRED_SCORE
    try:
        config.REQUIRED_SCORE = args.required_scores[0]
        bar_scores = compute_bar_scores(candles, bars_count)
    finally:
        config.REQUIRED_SCORE = original_required_score

    if not bar_scores:
        print("スコアを計算できるバーがありませんでした(ローソク足の本数がbars_countに対して不足している可能性があります)。")
        return

    print(f"{len(bar_scores)}バー分のスコアを計算しました。REQUIRED_SCOREごとに決済シミュレーションしています...\n")

    results = [
        simulate(
            bar_scores, n, sl_points, tp_points, point_size,
            optimistic_fill=args.optimistic_fill, spread_points=args.spread_points,
        )
        for n in args.required_scores
    ]
    _print_report(results)

    if args.decision_log_out:
        _write_decision_log(bar_scores, symbol, timeframe, args.decision_log_out)
        print(f"\n{args.decision_log_out} へ全バーの判断内訳(ai_decisions.jsonlと同じスキーマ)を書き出しました。")

    print(
        "\n※ risk_manager.py(クールダウン・同時保有数上限・連敗停止等)は再現していません。"
        "STOP_MODE=atrの動的SL/TPも未対応(fixedのみ)。実際の運用成績を保証するものではありません。"
    )


if __name__ == "__main__":
    main()
