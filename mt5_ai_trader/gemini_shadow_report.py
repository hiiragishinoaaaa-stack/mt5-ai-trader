"""Geminiシャドーモード(config.GEMINI_SHADOW)の集計レポートツール
(2026-07、Fable5との相談を踏まえて追加)。

`ai_shadow_log.jsonl`(ai_status.append_shadow_log参照)には、毎サイクルの
「ルール判断 vs Gemini判断」と判断時点の参考価格(price)が1行1JSONで
記録されているが、その場では一致率も仮想損益も計算していない(生データの
みを残す設計)。このツールは、そのログと過去のローソク足データ
(backtest_replay.pyと同じ`ARTEMIS_HistoryExport.mq5`のエクスポート形式)を
突き合わせ、以下を計算する:

1. **一致率**: ルールとGeminiの判断が一致した割合(全体、および
   BUY/SELL/WAITそれぞれの内訳)。ローソク足データが無くても計算できる
   (ログの`agree`列を集計するだけ)。
2. **Geminiに従っていた場合の仮想損益**: Geminiの各BUY/SELL判断について、
   判断時点の価格からSL_POINTS/TP_POINTSのどちらに先に到達したかを、
   その後のローソク足で判定する(backtest_replay.simulate_trade_forward
   と同じロジックを再利用。終値同士の比較だと本番の決済方式と別物の数字に
   なってしまうため、必ずSL/TP先着判定を使う)。比較のため、同じ方式で
   「ルールの判断に従っていた場合」の仮想損益も併せて計算する(どちらも
   同一の決済シミュレーション方式で計算するため、実際の約定[スリッページ等
   を含む]とは異なる、あくまで比較用の数字であることに注意)。

一致率は数日分のログで十分読めるが、仮想損益の優劣判定には数週間分の
ログが必要になる(Fable5の指摘通り、母数が少ないうちは参考程度に留める
こと)。

使い方:
  .venv/bin/python gemini_shadow_report.py --shadow-log logs/ai_shadow_log.jsonl \
      --candles-file artemis_history_USDJPY_M15.json
  .venv/bin/python gemini_shadow_report.py --shadow-log logs/ai_shadow_log.jsonl \
      --candles-file artemis_history_USDJPY_M15.json --sl-points 200 --tp-points 400
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import config
from backtest_replay import ReplayResult, load_candles, simulate_trade_forward


def load_shadow_log(path: str | Path) -> list[dict]:
    """ai_status.append_shadow_log()が書き出したJSON Lines(および
    ai_status._rotate_if_neededによる過去世代の.1.jsonl等)を読み込む。
    壊れた行(途中で電源が落ちた場合の書きかけの最終行等)は無視する。
    """
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def agreement_stats(rows: list[dict]) -> dict:
    """一致率(全体・方向別)を計算する。ローソク足データ不要。"""
    total = len(rows)
    if total == 0:
        return {"total": 0, "agree_count": 0, "agree_rate": 0.0, "by_rule_action": {}}

    agree_count = sum(1 for r in rows if r.get("agree"))
    by_rule_action: dict[str, dict] = {}
    for action in ("BUY", "SELL", "WAIT"):
        subset = [r for r in rows if r.get("rule_action") == action]
        agree_in_subset = sum(1 for r in subset if r.get("agree"))
        by_rule_action[action] = {
            "count": len(subset),
            "agree_count": agree_in_subset,
            "agree_rate": (agree_in_subset / len(subset) * 100) if subset else 0.0,
        }

    return {
        "total": total,
        "agree_count": agree_count,
        "agree_rate": agree_count / total * 100,
        "by_rule_action": by_rule_action,
    }


def _find_bar_index(candles: pd.DataFrame, timestamp: float) -> int | None:
    """shadow_logの1エントリー(timestamp、main.pyが書き出した壁時計時刻)に
    対応する、その時点で「直近」だったローソク足のインデックスを探す。

    ローソク足の時刻(バー開始時刻)がtimestamp以下になる最後の行を返す
    (見つからない、つまりログの方が過去データより古い場合はNone)。
    """
    times = candles["time"]
    ts = pd.Timestamp(timestamp, unit="s")
    idx = times.searchsorted(ts, side="right") - 1
    if idx < 0:
        return None
    return int(idx)


def simulate_shadow_outcomes(
    rows: list[dict],
    candles: pd.DataFrame,
    sl_points: float,
    tp_points: float,
    point_size: float,
    optimistic_fill: bool = False,
) -> tuple[ReplayResult, ReplayResult]:
    """shadow_logの各エントリーについて、Geminiの判断・ルールの判断
    それぞれに従っていた場合の仮想損益を、同一の決済シミュレーション方式
    (backtest_replay.simulate_trade_forward、SL/TP先着判定)で計算する。

    戻り値は(gemini側の結果, ルール側の結果)。ローソク足データが
    ログの期間をカバーしていない行(_find_bar_indexがNoneを返す)は
    スキップする。
    """
    gemini_result = ReplayResult(required_score=0)
    rule_result = ReplayResult(required_score=0)

    for row in rows:
        bar_index = _find_bar_index(candles, row["timestamp"])
        if bar_index is None:
            continue
        price = row.get("price")
        if price is None:
            continue

        bars_after = [
            (i, candles.iloc[i]["time"], float(candles.iloc[i]["high"]), float(candles.iloc[i]["low"]))
            for i in range(bar_index + 1, len(candles))
        ]
        entry_time = candles.iloc[bar_index]["time"]

        gemini_action = row.get("gemini_action")
        if gemini_action in ("BUY", "SELL"):
            trade = simulate_trade_forward(
                bars_after, gemini_action, bar_index, entry_time, float(price),
                sl_points, tp_points, point_size, optimistic_fill,
            )
            gemini_result.trades.append(trade)

        rule_action = row.get("rule_action")
        if rule_action in ("BUY", "SELL"):
            trade = simulate_trade_forward(
                bars_after, rule_action, bar_index, entry_time, float(price),
                sl_points, tp_points, point_size, optimistic_fill,
            )
            rule_result.trades.append(trade)

    return gemini_result, rule_result


def _print_agreement(agreement: dict) -> None:
    print("=== 一致率(ルール判断 vs Gemini判断) ===")
    print(f"全体: {agreement['agree_count']}/{agreement['total']}件 ({agreement['agree_rate']:.1f}%)")
    for action, stats in agreement["by_rule_action"].items():
        if stats["count"] == 0:
            continue
        print(
            f"  ルールが{action}のとき: {stats['agree_count']}/{stats['count']}件 "
            f"({stats['agree_rate']:.1f}%がGeminiも{action})"
        )


def _print_report(agreement: dict, gemini_result: ReplayResult, rule_result: ReplayResult) -> None:
    _print_agreement(agreement)

    print("\n=== 仮想損益(SL/TP先着判定によるシミュレーション、実際の約定とは異なる参考値) ===")
    print(f"{'':>10} {'件数':>5} {'勝率%':>7} {'期待値pt':>9} {'合計pt':>9} {'最大DD pt':>10} {'未決済':>6}")
    for label, result in (("Gemini追従", gemini_result), ("ルールのまま", rule_result)):
        print(
            f"{label:>10} {len(result.closed_trades):>5} {result.win_rate:>7.1f} "
            f"{result.expectancy_points:>+9.1f} {result.total_pnl_points:>+9.1f} "
            f"{result.max_drawdown_points:>10.1f} {result.still_open_count:>6}"
        )

    print(
        "\n※ 一致率は数日分のログでも参考になるが、仮想損益の優劣判定には数週間分のログが必要。"
        "母数(上表の件数)が少ないうちは参考程度に留めること。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Geminiシャドーモードの一致率・仮想損益を集計するツール")
    parser.add_argument("--shadow-log", required=True, help="ai_status.append_shadow_logが書き出したJSON Linesファイル")
    parser.add_argument(
        "--candles-file",
        default=None,
        help="仮想損益の計算に使う過去足(backtest_replay.pyと同じARTEMIS_HistoryExport.mq5形式)。"
        "省略すると一致率のみ計算する",
    )
    parser.add_argument("--sl-points", type=float, default=None, help="既定: config.SL_POINTS")
    parser.add_argument("--tp-points", type=float, default=None, help="既定: config.TP_POINTS")
    parser.add_argument("--point-size", type=float, default=None, help="既定: config.POINT_SIZE")
    parser.add_argument(
        "--optimistic-fill",
        action="store_true",
        help="同じバーでSL/TP両方に触れた場合、TPを優先する(既定はSLを優先する保守的な見積もり)",
    )
    args = parser.parse_args()

    rows = load_shadow_log(args.shadow_log)
    if not rows:
        print(f"{args.shadow_log} にログがありませんでした。")
        return

    agreement = agreement_stats(rows)

    if args.candles_file is None:
        _print_agreement(agreement)
        print("\n(--candles-fileを指定すると仮想損益も計算できます)")
        return

    sl_points = args.sl_points if args.sl_points is not None else config.SL_POINTS
    tp_points = args.tp_points if args.tp_points is not None else config.TP_POINTS
    point_size = args.point_size if args.point_size is not None else config.POINT_SIZE

    candles = load_candles(args.candles_file)
    gemini_result, rule_result = simulate_shadow_outcomes(
        rows, candles, sl_points, tp_points, point_size, optimistic_fill=args.optimistic_fill
    )
    _print_report(agreement, gemini_result, rule_result)


if __name__ == "__main__":
    main()
