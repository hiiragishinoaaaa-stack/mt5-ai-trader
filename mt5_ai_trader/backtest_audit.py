"""RuleBasedAIEngineの条件別エッジ監査ツール(2026-07、Fable5との相談を
踏まえて追加)。

backtest_replay.pyが「閾値(REQUIRED_SCORE)をいくつにするか」を検証するのに
対し、こちらは「そもそもどの条件にエッジがあるのか/無いのか」を切り分ける。

## なぜ必要か

backtest_replay.pyでの初回検証(USDJPY M15 5000本)で、(1)どの閾値でも
損益分岐(RR1:2なら勝率33.3%)を割り、(2)閾値を上げても勝率が改善しない
(=各閾値でエントリー件数がほぼ同じ=閾値が実質効いていない)ことが判明
した。これは「閾値の調整不足」ではなく「採点している条件そのものが、この
期間・銘柄で予測力を持っていない」可能性を示す。原因を条件レベルまで
切り分けるのがこのツール。

## 出力する監査

1. **スコア分布**: 全バーのBUY/SELL合計スコアのヒストグラム。二極化して
   いれば「スコアの段階」が幻想(条件間の強い相関)だった証拠になる。
2. **ベースライン**: 全バーでH1トレンド方向へ無条件エントリーした場合の
   成績。これがランダム基準線。戦略がこれを下回るなら、条件セットは
   「悪い瞬間」を選んでいる(除外どころか反転利用の検討対象)。
3. **単一条件バックテスト**: 各条件を唯一のエントリー根拠として個別に回し、
   どの条件に単独のエッジがあるかを序列化する。
4. **分位分析**: 連続指標(RSI/EMA乖離/ATR/MACDヒストグラム)を分位に区切り、
   各分位からのエントリー成績の単調性を見る。
5. 1〜4を**ADXレジーム(トレンド/レンジ)別**にも分けて出力する。

## 共通の前提

- 決済はbacktest_replay.pyと全く同じSL/TP先着方式(simulate_trade_forwardを
  共有)。全ての分析で「各バーからそのバーの終値でエントリーした独立試行」
  として集計する(backtest_replay.pyの連続ポジション方式とは異なり、各
  シグナルの単独のエッジを測るのが目的のため)。
- 各バーのBUY/SELL両方向のforward結果は1度だけ事前計算してキャッシュし、
  全分析がそれを引く(precompute_forward_outcomes)。
- スプレッドコストは--spread-pointsで往復スプレッド(points)を各トレードの
  損益から引ける(既定0=未考慮)。
- レジーム判定はconfig.ADX_TREND_THRESHOLD(既定25)以上をTRENDINGとする。
- 各条件の評価はai_engine.RuleBasedAIEngine.evaluate_conditions()を使い、
  本番のdecide()と完全に同じ条件計算になる。

使い方:
  .venv/bin/python backtest_audit.py --candles-file artemis_history_USDJPY_M15.json
  .venv/bin/python backtest_audit.py --candles-file artemis_history_USDJPY_M15.json \
      --spread-points 15 --all-conditions
"""
from __future__ import annotations

import argparse
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pandas as pd

import config
import indicators
from ai_engine import RuleBasedAIEngine
from backtest_replay import ReplayResult, ReplayTrade, load_candles, simulate_trade_forward

# 方向で文言が違う条件を、方向非依存の「条件ファミリー」名へまとめる
# (単一条件バックテストでBUY側・SELL側を同じエッジとして合算するため)。
# ここに無いラベル(方向非依存の文言)はそのままファミリー名になる。
_CONDITION_FAMILY = {
    "上昇トレンド(EMA)": "EMAトレンド方向",
    "下降トレンド(EMA)": "EMAトレンド方向",
    "押し目からの回復": "押し目/戻りからの回復",
    "戻りからの回復": "押し目/戻りからの回復",
    "RSI帯域内(BUY)": "RSI帯域内",
    "RSI帯域内(SELL)": "RSI帯域内",
    "直近3本の安値が切り上げ": "直近3本の高安構造",
    "直近3本の高値が切り下げ": "直近3本の高安構造",
    "直近5本の安値を更新せず": "直近5本の高安を更新せず",
    "直近5本の高値を更新せず": "直近5本の高安を更新せず",
    "上位足(H1)が方向一致": "上位足(H1)が方向一致",
    "上位足(H1)のEMAも方向一致": "上位足(H1)のEMAも方向一致",
    "MACDヒストグラムが方向一致": "MACD方向一致",
    "MACDヒストグラムが拡大方向": "MACD拡大",
    "EMAの傾きが方向一致": "EMAの傾き",
    "直近足の実体が方向一致": "直近足の実体",
    "RSIが50を方向側に超過": "RSIが50を方向側に超過",
    "ATR最低値以上": "ATR最低値以上",
    "トレンド相場(ADX)": "トレンド相場(ADX)",
}


@dataclass
class AuditBar:
    index: int
    time: pd.Timestamp
    close: float
    h1_direction: str | None
    adx: float | None
    regime: str | None
    rsi: float | None
    ema_dist_atr: float | None  # (close - ema_fast) / atr。0中心、+で上乖離
    atr_points: float | None
    macd_hist: float | None
    buy_conditions: list[tuple[str, bool]] = field(default_factory=list)
    sell_conditions: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def buy_score(self) -> int:
        return sum(1 for _, ok in self.buy_conditions if ok)

    @property
    def sell_score(self) -> int:
        return sum(1 for _, ok in self.sell_conditions if ok)


def compute_audit_bars(candles: pd.DataFrame, bars_count: int) -> list[AuditBar]:
    """本番と同じローリングウィンドウ方式(backtest_replay.compute_bar_scores
    と同一)で、各バーのBUY/SELL条件別成否・生指標・H1方向・レジームを計算する。
    """
    engine = RuleBasedAIEngine()
    threshold = config.ADX_TREND_THRESHOLD
    bars: list[AuditBar] = []
    n = len(candles)
    for i in range(bars_count - 1, n):
        window = candles.iloc[i - bars_count + 1 : i + 1].reset_index(drop=True)
        enriched = indicators.add_indicators(window)
        buy_conditions = engine.evaluate_conditions(enriched, "BUY")
        if not buy_conditions:
            continue  # 指標未計算(ウィンドウ先頭付近)
        sell_conditions = engine.evaluate_conditions(enriched, "SELL")
        h1_direction, _ = engine._h1_trend_direction(enriched)
        latest = enriched.iloc[-1]
        adx = float(latest["adx"]) if "adx" in enriched.columns and not pd.isna(latest["adx"]) else None
        regime = None if adx is None else ("TRENDING" if adx >= threshold else "RANGING")
        atr = float(latest["atr"]) if "atr" in enriched.columns and not pd.isna(latest["atr"]) else None
        ema_dist = (float(latest["close"]) - float(latest["ema_fast"])) / atr if atr and atr > 0 else None
        atr_points = atr / config.POINT_SIZE if atr and config.POINT_SIZE > 0 else None
        bars.append(
            AuditBar(
                index=i,
                time=candles.iloc[i]["time"],
                close=float(candles.iloc[i]["close"]),
                h1_direction=h1_direction,
                adx=adx,
                regime=regime,
                rsi=float(latest["rsi"]) if not pd.isna(latest["rsi"]) else None,
                ema_dist_atr=ema_dist,
                atr_points=atr_points,
                macd_hist=float(latest["macd_hist"]) if not pd.isna(latest["macd_hist"]) else None,
                buy_conditions=buy_conditions,
                sell_conditions=sell_conditions,
            )
        )
    return bars


def precompute_forward_outcomes(
    candles: pd.DataFrame,
    audit_bars: list[AuditBar],
    sl_points: float,
    tp_points: float,
    point_size: float,
    spread_points: float,
    optimistic_fill: bool,
) -> dict[tuple[int, str], ReplayTrade]:
    """各AuditBarについて、そのバーの終値でBUY/SELLそれぞれにエントリーした
    場合のforward決済結果を事前計算する(全分析がこれを引くだけで済むように
    してO(N^2)の再計算を避ける)。戻り値は{(bar_index, direction): trade}。
    """
    all_bars = [
        (int(row.Index), row.time, float(row.high), float(row.low))
        for row in candles.itertuples(index=True)
    ]
    outcomes: dict[tuple[int, str], ReplayTrade] = {}
    for bar in audit_bars:
        bars_after = all_bars[bar.index + 1 :]
        for direction in ("BUY", "SELL"):
            outcomes[(bar.index, direction)] = simulate_trade_forward(
                bars_after, direction, bar.index, bar.time, bar.close,
                sl_points, tp_points, point_size, optimistic_fill, spread_points,
            )
    return outcomes


def _result(trades: list[ReplayTrade]) -> ReplayResult:
    r = ReplayResult(required_score=0)
    r.trades = trades
    return r


def breakeven_win_rate(sl_points: float, tp_points: float) -> float:
    """SL/TP先着方式でトントンになる勝率(%)。RR=tp/sl、breakeven=1/(1+RR)。"""
    if sl_points + tp_points <= 0:
        return 0.0
    return sl_points / (sl_points + tp_points) * 100


def baseline_result(audit_bars: list[AuditBar], outcomes: dict[tuple[int, str], ReplayTrade]) -> ReplayResult:
    """全バーでH1トレンド方向へ無条件エントリーした場合の結果(ランダム基準線)。"""
    trades = [outcomes[(b.index, b.h1_direction)] for b in audit_bars if b.h1_direction in ("BUY", "SELL")]
    return _result(trades)


def single_condition_results(
    audit_bars: list[AuditBar], outcomes: dict[tuple[int, str], ReplayTrade]
) -> dict[str, ReplayResult]:
    """各条件ファミリーを唯一のエントリー根拠として個別に集計する。
    BUY条件が成立したバーはBUY、対応するSELL条件が成立したバーはSELLの
    forward結果を、同じファミリーへ合算する。
    """
    families: dict[str, list[ReplayTrade]] = defaultdict(list)
    for bar in audit_bars:
        for label, ok in bar.buy_conditions:
            if ok:
                families[_CONDITION_FAMILY.get(label, label)].append(outcomes[(bar.index, "BUY")])
        for label, ok in bar.sell_conditions:
            if ok:
                families[_CONDITION_FAMILY.get(label, label)].append(outcomes[(bar.index, "SELL")])
    return {family: _result(trades) for family, trades in families.items()}


def quantile_results(
    audit_bars: list[AuditBar],
    outcomes: dict[tuple[int, str], ReplayTrade],
    metric: str,
    direction: str,
    n_quantiles: int = 5,
) -> list[tuple[str, ReplayResult]]:
    """指定した連続指標(metric)でバーをn_quantiles分位に区切り、各分位から
    directionへエントリーした場合の成績を返す。指標の単調性(低い分位ほど/
    高い分位ほど勝ちやすい等)を見るためのもの。
    """
    pairs = [(getattr(b, metric), outcomes[(b.index, direction)]) for b in audit_bars if getattr(b, metric) is not None]
    if len(pairs) < n_quantiles:
        return []
    pairs.sort(key=lambda p: p[0])
    results: list[tuple[str, ReplayResult]] = []
    size = len(pairs)
    for q in range(n_quantiles):
        lo = q * size // n_quantiles
        hi = (q + 1) * size // n_quantiles
        chunk = pairs[lo:hi]
        if not chunk:
            continue
        lo_val, hi_val = chunk[0][0], chunk[-1][0]
        label = f"Q{q + 1} [{lo_val:.2f}〜{hi_val:.2f}]"
        results.append((label, _result([t for _, t in chunk])))
    return results


# --- 出力 ----------------------------------------------------------------------


def _print_result_row(label: str, r: ReplayResult, breakeven: float, width: int = 26) -> None:
    closed = len(r.closed_trades)
    margin = r.win_rate - breakeven
    print(
        f"{label:<{width}} {closed:>6} {r.win_rate:>7.1f} {breakeven:>9.1f} {margin:>+8.1f} "
        f"{r.expectancy_points:>+9.1f} {r.total_pnl_points:>+10.1f}"
    )


def _print_header(width: int = 26) -> None:
    print(
        f"{'':<{width}} {'件数':>6} {'勝率%':>7} {'損益分岐%':>9} {'差':>8} {'期待値pt':>9} {'合計pt':>10}"
    )


def _print_score_distribution(audit_bars: list[AuditBar]) -> None:
    print("=== スコア分布(全バー、条件間相関の診断) ===")
    for direction, getter in (("BUY", lambda b: b.buy_score), ("SELL", lambda b: b.sell_score)):
        counter = Counter(getter(b) for b in audit_bars)
        total = sum(counter.values())
        if total == 0:
            continue
        max_count = max(counter.values())
        print(f"[{direction}] 満点={max((len(b.buy_conditions) if direction == 'BUY' else len(b.sell_conditions)) for b in audit_bars)}点前後")
        for score in sorted(counter):
            count = counter[score]
            bar = "#" * max(1, round(count / max_count * 40))
            print(f"  {score:>3}点: {count:>6} ({count / total * 100:>5.1f}%) {bar}")


def _run_and_print(audit_bars: list[AuditBar], outcomes, breakeven: float, header: str) -> None:
    print(f"\n=== {header} ===")
    _print_header()

    baseline = baseline_result(audit_bars, outcomes)
    _print_result_row("ベースライン(H1方向)", baseline, breakeven)

    print("  -- 単一条件(成立時のみエントリー、その条件を唯一の根拠とした場合) --")
    singles = single_condition_results(audit_bars, outcomes)
    for family, r in sorted(singles.items(), key=lambda kv: kv[1].win_rate, reverse=True):
        _print_result_row("  " + family, r, breakeven)

    print("  -- 連続指標の分位別(BUYエントリー、単調性を見る) --")
    for metric, jp in (("rsi", "RSI"), ("ema_dist_atr", "EMA乖離/ATR"), ("atr_points", "ATR(pt)"), ("macd_hist", "MACDヒスト")):
        quantiles = quantile_results(audit_bars, outcomes, metric, "BUY")
        if not quantiles:
            continue
        print(f"  [{jp}]")
        for label, r in quantiles:
            _print_result_row("    " + label, r, breakeven)


def main() -> None:
    parser = argparse.ArgumentParser(description="RuleBasedAIEngineの条件別エッジ監査ツール")
    parser.add_argument("--candles-file", required=True, help="ARTEMIS_HistoryExport.mq5が書き出したJSONファイル")
    parser.add_argument("--bars-count", type=int, default=None, help="既定: config.BARS_COUNT(本番と揃えること)")
    parser.add_argument("--sl-points", type=float, default=None, help="既定: config.SL_POINTS")
    parser.add_argument("--tp-points", type=float, default=None, help="既定: config.TP_POINTS")
    parser.add_argument("--point-size", type=float, default=None, help="既定: config.POINT_SIZE")
    parser.add_argument("--spread-points", type=float, default=0.0, help="往復スプレッド(points、既定0=未考慮)")
    parser.add_argument("--optimistic-fill", action="store_true", help="同一バーでSL/TP両方到達時にTP優先(既定SL優先)")
    parser.add_argument(
        "--all-conditions",
        action="store_true",
        help="REQUIRE_TRENDING_REGIMEとREQUIRE_NO_NEW_EXTREME_5BARSを一時的に有効化し、"
        "現在オフの条件も監査対象に含める(それらの条件に単独エッジがあるか確認したい場合)",
    )
    parser.add_argument("--no-regime-split", action="store_true", help="ADXレジーム別の内訳を出力しない")
    args = parser.parse_args()

    bars_count = args.bars_count or config.BARS_COUNT
    sl_points = args.sl_points if args.sl_points is not None else config.SL_POINTS
    tp_points = args.tp_points if args.tp_points is not None else config.TP_POINTS
    point_size = args.point_size if args.point_size is not None else config.POINT_SIZE
    breakeven = breakeven_win_rate(sl_points, tp_points)

    if args.all_conditions:
        config.REQUIRE_TRENDING_REGIME = True
        config.REQUIRE_NO_NEW_EXTREME_5BARS = True

    print(f"{args.candles_file} を読み込んでいます...")
    candles = load_candles(args.candles_file)
    print(f"{len(candles)}本を読み込みました。ウィンドウ={bars_count}本で条件を計算しています(数分かかることがあります)...")

    audit_bars = compute_audit_bars(candles, bars_count)
    if not audit_bars:
        print("監査できるバーがありませんでした(本数不足の可能性)。")
        return

    print(f"{len(audit_bars)}バー分を計算しました。forward決済を事前計算しています...")
    outcomes = precompute_forward_outcomes(
        candles, audit_bars, sl_points, tp_points, point_size, args.spread_points, args.optimistic_fill
    )

    fee_note = f"、往復スプレッド{args.spread_points}pt考慮" if args.spread_points else "、スプレッド未考慮"
    print(
        f"\nSL={sl_points}pt / TP={tp_points}pt(損益分岐勝率={breakeven:.1f}%){fee_note}。"
        "「差」列がプラスなら損益分岐超え、マイナスなら期待値マイナス。\n"
    )

    _print_score_distribution(audit_bars)
    _run_and_print(audit_bars, outcomes, breakeven, "全体")

    if not args.no_regime_split:
        for regime in ("TRENDING", "RANGING"):
            subset = [b for b in audit_bars if b.regime == regime]
            if len(subset) < 20:
                continue
            jp = "トレンド相場" if regime == "TRENDING" else "レンジ相場"
            _run_and_print(subset, outcomes, breakeven, f"レジーム別: {jp}(ADX{'≥' if regime == 'TRENDING' else '<'}{config.ADX_TREND_THRESHOLD}、{len(subset)}バー)")

    print(
        "\n※ 各行は「その根拠でエントリーした独立試行」の成績。ベースラインを下回る条件は、"
        "その相場ではエントリーを絞るどころか悪化させている(反転利用の検討対象)。"
        "risk_manager.py・STOP_MODE=atrは未再現。1銘柄・限られた期間の結果に過ぎない点に注意。"
    )


if __name__ == "__main__":
    main()
