"""AI判断エンジンを、保存済みの過去データに対してその場で走らせて見せるツール。

## 何のためのものか

本番ループ(main.py)はEAが書き出す「今の」ローソク足を読むため、**市場が閉じて
いる週末は判断が1件も出ない**(データが古いとサイクルごとスキップされる)。
一方でAIエンジンが実際に何をどう判断するのかは、曜日と無関係に確認したい。

このツールは`ARTEMIS_HistoryExport.mq5`が書き出した履歴JSONを読み、本番と同じ
ローリングウィンドウ(config.BARS_COUNT本)を切り出して、**ルールベースの判断と
AI(Gemini等)の判断を並べて表示する**。発注は一切行わず、MT5にもEAにも触れない。

## 使いどころ

- 週末・市場休止中でも、AIの判断とその理由を目で確認する
- LLMに実際どんな文面が渡っているのか(--show-prompt)を確認する
- APIキーの設定が正しいかを、本番ループを動かす前に確かめる

## APIコストについて

指定した件数(--count、既定3)だけAPIを呼ぶ。ウィンドウごとに最終足が変わるため
CandleThrottledEngineのキャッシュは効かず、件数分そのまま呼び出しが発生する。
Gemini Flashには無料枠があるが、大きな件数を指定しないこと。

使い方:
  .venv/bin/python ai_dry_run.py --candles-file artemis_history_USDJPY_M15.json
  .venv/bin/python ai_dry_run.py --candles-file artemis_history_USDJPY_M15.json \
      --engine gemini --count 5 --show-prompt
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

import pandas as pd

import config
import indicators
from ai_engine import RuleBasedAIEngine, Signal, describe_market_conditions, get_ai_engine
from backtest_replay import load_candles

_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def list_gemini_models() -> None:
    """このAPIキーで実際に使えるGeminiモデル名を一覧する(切り分け用)。

    generateContentが404を返すとき、原因は「キーが無効」ではなく
    「そのモデル名がこのキーから見えない」であることが多い(キーが無効なら
    401/403になる)。ここでモデル一覧が取れれば認証は通っており、あとは
    config.GEMINI_MODELを一覧にある名前へ合わせればよい。

    APIキーはクエリ文字列ではなくヘッダで送る。エラー応答の本文に
    リクエストURLが含まれてもキーが漏れないようにするため。
    表示するのはモデル名とHTTPステータスだけで、キーは決して出力しない。
    """
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY が未設定です(.env を確認してください)。")
        return

    req = urllib.request.Request(_MODELS_URL, headers={"x-goog-api-key": config.GEMINI_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"モデル一覧の取得に失敗しました: HTTP {exc.code} {exc.reason}")
        if exc.code in (401, 403):
            print("→ 認証エラー。APIキー自体が無効か、種類が違います。")
            print("   Google AI Studio (https://aistudio.google.com/apikey) で作る")
            print("   Gemini APIキーは 'AIza' で始まります。別の値なら作り直してください。")
        else:
            print("→ 認証以外の問題です。ネットワーク/プロキシ設定も確認してください。")
        return
    except urllib.error.URLError as exc:
        print(f"モデル一覧の取得に失敗しました(接続エラー): {exc.reason}")
        return

    models = payload.get("models", [])
    usable = [
        m["name"].removeprefix("models/")
        for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    if not usable:
        print("このキーで generateContent を使えるモデルが見つかりませんでした。")
        return

    print(f"認証は成功しました。generateContent を使えるモデル {len(usable)} 件:")
    for name in usable:
        mark = "  ← 現在の設定" if name == config.GEMINI_MODEL else ""
        print(f"  {name}{mark}")
    if config.GEMINI_MODEL not in usable:
        print(
            f"\n現在の GEMINI_MODEL={config.GEMINI_MODEL} は一覧にありません。これが404の原因です。"
            f"\n.env に GEMINI_MODEL=<上の一覧から選んだ名前> を追記してください。"
        )


def iter_windows(candles: pd.DataFrame, bars_count: int, count: int, step: int):
    """新しい方から順に、本番と同じ長さのウィンドウをcount個切り出す。

    stepは何本ずらして次のウィンドウを取るか。1本ずらすだけだと判断材料が
    ほぼ同じになり、AIの答えも当然似るため、既定では十分に離す。
    """
    windows = []
    end = len(candles)
    for _ in range(count):
        start = end - bars_count
        if start < 0:
            break
        windows.append(candles.iloc[start:end].reset_index(drop=True))
        end -= step
    return list(reversed(windows))


def format_signal(signal: Signal) -> str:
    return f"{signal.action:<4} (確信度 {signal.confidence:>5.1f}) {signal.reason}"


def score_line(signal: Signal) -> str | None:
    """ルールベースのスコア内訳を1行にまとめる(AIエンジンには無い情報)。"""
    d = signal.details
    if "buy_score" not in d:
        return None
    return (
        f"      スコア: BUY {d['buy_score']}/{d['buy_total']} , "
        f"SELL {d['sell_score']}/{d['sell_total']} (必要 {d['required_score']})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="保存済みの過去データでAI判断エンジンを走らせ、ルール判断と並べて表示する(発注しない)"
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="このAPIキーで使えるGeminiモデル名を一覧する(404の切り分け用)。キーは表示しない",
    )
    parser.add_argument("--candles-file", help="ARTEMIS_HistoryExport.mq5が書き出したJSON")
    parser.add_argument(
        "--engine",
        default="gemini",
        help="比較対象のAIエンジン(gemini / openai / claude / rule_based)。既定: gemini",
    )
    parser.add_argument("--count", type=int, default=3, help="判断させる件数(=API呼び出し回数)。既定3")
    parser.add_argument(
        "--step",
        type=int,
        default=96,
        help="ウィンドウをずらす本数。既定96(M15で約1日ぶん離す)",
    )
    parser.add_argument("--bars-count", type=int, default=None, help="既定: config.BARS_COUNT(本番と揃えること)")
    parser.add_argument("--show-prompt", action="store_true", help="LLMへ実際に渡している文面を表示する")
    args = parser.parse_args()

    if args.list_models:
        list_gemini_models()
        return
    if not args.candles_file:
        parser.error("--candles-file を指定してください(--list-models のときは不要)")

    bars_count = args.bars_count or config.BARS_COUNT

    print(f"{args.candles_file} を読み込んでいます...")
    candles = load_candles(args.candles_file)
    windows = iter_windows(candles, bars_count, args.count, args.step)
    if not windows:
        print(f"ウィンドウを切り出せませんでした(必要{bars_count}本に対し{len(candles)}本)。")
        return

    rule_engine = RuleBasedAIEngine()
    ai_engine = get_ai_engine(args.engine)
    print(
        f"{len(windows)}件を判断します(ウィンドウ{bars_count}本 / {args.step}本間隔)。"
        f"AIエンジン={args.engine}、発注は一切しません。\n"
    )

    agreements = 0
    for i, window in enumerate(windows, start=1):
        enriched = indicators.add_indicators(window)
        latest = enriched.iloc[-1]
        when = pd.Timestamp(latest["time"]) if "time" in enriched.columns else None

        print(f"--- {i}/{len(windows)}  {when}  終値={float(latest['close']):.3f} ---")
        if args.show_prompt:
            print("  [AIへ渡している文面]")
            for line in describe_market_conditions(enriched, config.SYMBOL, config.TIMEFRAME).splitlines():
                print(f"    {line}")
            print()

        rule_signal = rule_engine.decide(enriched)
        print(f"  ルール : {format_signal(rule_signal)}")
        breakdown = score_line(rule_signal)
        if breakdown:
            print(breakdown)

        ai_signal = ai_engine.decide(enriched)
        print(f"  AI({args.engine}) : {format_signal(ai_signal)}")

        same = rule_signal.action == ai_signal.action
        agreements += same
        print(f"  → {'一致' if same else '不一致'}\n")

    print(f"一致率: {agreements}/{len(windows)} ({agreements / len(windows) * 100:.0f}%)")
    print(
        "\n※ここでの判断は表示だけで、発注にも学習にも使われない。"
        "\n※一致/不一致は「どちらが正しいか」ではない。当否は決済結果でしか測れず、"
        "\n  その集計は本番のシャドーモード(GEMINI_SHADOW=true)とgemini_shadow_report.pyで行う。"
    )


if __name__ == "__main__":
    main()
