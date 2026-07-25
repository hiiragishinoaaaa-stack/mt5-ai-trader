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

_MODELS_URL_TEMPLATE = "https://generativelanguage.googleapis.com/{version}/models"
_API_VERSIONS = ("v1beta", "v1")


def _fetch_models(version: str) -> tuple[list[str], str | None]:
    """1つのAPIバージョンで、generateContentが使えるモデル名を取得する。

    戻り値は(モデル名リスト, エラー説明)。APIキーはクエリ文字列ではなく
    ヘッダで送る(エラー応答がリクエストURLを含んでもキーが漏れないように)。
    """
    req = urllib.request.Request(
        _MODELS_URL_TEMPLATE.format(version=version),
        headers={"x-goog-api-key": config.GEMINI_API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        return [], f"接続エラー: {exc.reason}"

    return (
        [
            m["name"].removeprefix("models/")
            for m in payload.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ],
        None,
    )


def list_gemini_models() -> None:
    """このAPIキーで実際に使えるモデルを、APIバージョン別に一覧する(切り分け用)。

    generateContentが404を返すとき、原因は「キーが無効」ではなく
    「そのモデル名がこのバージョンに存在しない」ことが多い(キーが無効なら
    401/403になる)。モデル名とAPIバージョンは組で決まるため、v1betaとv1の
    両方を問い合わせて、今の設定(GEMINI_MODEL / GEMINI_API_VERSION)が
    どこに当てはまるのかを示す。

    表示するのはモデル名とHTTPステータスだけで、APIキーは決して出力しない。
    """
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY が未設定です(.env を確認してください)。")
        return

    found: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for version in _API_VERSIONS:
        models, error = _fetch_models(version)
        if error:
            errors[version] = error
        elif models:
            found[version] = models

    if not found:
        print("どのAPIバージョンでもモデル一覧を取得できませんでした:")
        for version, error in errors.items():
            print(f"  {version}: {error}")
        if any("401" in e or "403" in e for e in errors.values()):
            print(
                "\n→ 認証エラーです。キーが途中で切れていないか(コピー漏れ)、"
                "\n  https://aistudio.google.com/apikey で作り直したものが .env に入っているかを確認してください。"
            )
        else:
            print("\n→ 認証以外の問題です。VPSからの外向き通信/プロキシ設定も確認してください。")
        return

    print("認証は成功しました。使えるモデル:\n")
    for version, models in found.items():
        print(f"[{version}]")
        for name in models:
            current = version == config.GEMINI_API_VERSION and name == config.GEMINI_MODEL
            print(f"  {name}{'  ← 現在の設定' if current else ''}")
        print()

    if config.GEMINI_MODEL in found.get(config.GEMINI_API_VERSION, []):
        print(
            f"現在の設定 (GEMINI_API_VERSION={config.GEMINI_API_VERSION} / "
            f"GEMINI_MODEL={config.GEMINI_MODEL}) は有効です。"
        )
        return

    print(
        f"現在の設定 (GEMINI_API_VERSION={config.GEMINI_API_VERSION} / "
        f"GEMINI_MODEL={config.GEMINI_MODEL}) はこの組み合わせに存在しません。これが404の原因です。"
    )
    for version, models in found.items():
        if config.GEMINI_MODEL in models:
            print(f"→ 同じモデルは {version} にあります。.env に GEMINI_API_VERSION={version} を追記してください。")
            return
    preferred = next(
        (m for models in found.values() for m in models if "flash" in m),
        next(iter(next(iter(found.values())))),
    )
    version = next(v for v, models in found.items() if preferred in models)
    print(f"→ 例えば .env に次の2行を入れると動きます:\n   GEMINI_API_VERSION={version}\n   GEMINI_MODEL={preferred}")


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
