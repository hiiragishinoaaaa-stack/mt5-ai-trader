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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pandas as pd

import config
import indicators
from ai_engine import RuleBasedAIEngine, Signal, describe_market_conditions, get_ai_engine
from backtest_audit import _make_forward_scanner
from backtest_replay import infer_point_size, load_candles

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


def _redact(text: str) -> str:
    """画面に出す前にAPIキーらしき文字列を伏せる(スクリーンショット対策)。

    キーはヘッダで送っているのでGoogleの応答本文には現れないはずだが、
    表示する文字列に対して最後の砦として掛けておく。
    """
    key = config.GEMINI_API_KEY
    return text.replace(key, "***") if key else text


def _try_generate(version: str, model: str) -> tuple[bool, str]:
    """最小のgenerateContentを1回投げて、成否と説明を返す。"""
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True, "OK"
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        # 応答本文の"message"だけ抜き出せれば、それが一番説明的
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            pass
        return False, _redact(f"HTTP {exc.code} {exc.reason}: {detail[:300]}")
    except urllib.error.URLError as exc:
        return False, f"接続エラー: {exc.reason}"


def probe_generate_content(max_candidates: int = 6) -> None:
    """実際に生成を通せる(バージョン, モデル)の組を探し当てる。

    --list-modelsが「有効」と言っても generateContent が404になることがある。
    モデル一覧に載っていても、そのモデルが生成の提供を終了していると、
    一覧には残ったまま生成側だけ404を返すため。ここでは一覧に頼らず、
    実際に最小リクエストを投げて通る組み合わせを確かめる。

    まず現在の設定を試し、駄目なら一覧のFlash系を新しい順に試す。
    呼び出し回数はmax_candidatesで抑える(1件あたり極小のリクエスト)。
    """
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY が未設定です(.env を確認してください)。")
        return

    print(f"現在の設定を試します: {config.GEMINI_API_VERSION} / {config.GEMINI_MODEL}")
    ok, detail = _try_generate(config.GEMINI_API_VERSION, config.GEMINI_MODEL)
    print(f"  → {'成功' if ok else '失敗: ' + detail}\n")
    if ok:
        print("現在の設定で生成できています。.env の変更は不要です。")
        return

    candidates: list[tuple[str, str]] = []
    for version in _API_VERSIONS:
        models, error = _fetch_models(version)
        if error:
            continue
        # 生成が軽く安価なFlash系を優先し、画像/音声など用途違いは除く
        flash = [m for m in models if "flash" in m and not any(x in m for x in ("image", "tts", "lite"))]
        candidates += [(version, m) for m in sorted(flash, reverse=True)]

    candidates = [c for c in candidates if c != (config.GEMINI_API_VERSION, config.GEMINI_MODEL)]
    if not candidates:
        print("試せる候補モデルが見つかりませんでした。--list-models の結果を確認してください。")
        return

    print(f"他の候補を {min(len(candidates), max_candidates)} 件試します...\n")
    for version, model in candidates[:max_candidates]:
        ok, detail = _try_generate(version, model)
        print(f"  {version} / {model}: {'成功' if ok else detail}")
        if ok:
            print(
                f"\n動く組み合わせが見つかりました。.env に次の2行を追記してください:\n"
                f"   GEMINI_API_VERSION={version}\n"
                f"   GEMINI_MODEL={model}"
            )
            return

    print("\n候補がすべて失敗しました。上のエラー本文をそのまま共有してください。")


def iter_windows(candles: pd.DataFrame, bars_count: int, count: int, step: int):
    """新しい方から順に、本番と同じ長さのウィンドウをcount個切り出す。

    返すのは(最終足の絶対インデックス, ウィンドウ)の組。絶対インデックスは、
    判断後に実際どうなったかを元データ上で前方走査するのに使う。

    stepは何本ずらして次のウィンドウを取るか。1本ずらすだけだと判断材料が
    ほぼ同じになり、AIの答えも当然似るため、既定では十分に離す。
    """
    windows = []
    end = len(candles)
    for _ in range(count):
        start = end - bars_count
        if start < 0:
            break
        windows.append((end - 1, candles.iloc[start:end].reset_index(drop=True)))
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


def call_engine(engine, df: pd.DataFrame, retries: int, backoff_seconds: float) -> Signal:
    """AIエンジンを呼ぶ。レート制限(429)なら待って数回まで再試行する。

    無料枠には1分あたりの回数制限があり、まとめて投げると429で弾かれる。
    弾かれた回もWAIT扱いで返ってくるため、そのまま集計すると「AIが見送った」
    ように見えてしまう。ここで吸収して、本当に判断が取れた回だけを残す。
    """
    for attempt in range(retries + 1):
        signal = engine.decide(df)
        if signal.details.get("http_status") != 429 or attempt == retries:
            return signal
        # サーバーが待つべき秒数を教えてくれるならそれに従う(短すぎても長すぎても
        # 無駄になるため)。教えてくれない場合だけこちらの既定値を使う。
        suggested = signal.details.get("retry_after_seconds")
        wait = min(max(float(suggested) + 1.0, 1.0), 120.0) if suggested else backoff_seconds
        print(f"      (レート制限。{wait:.0f}秒待って再試行します)")
        time.sleep(wait)
    return signal


@dataclass
class Verdict:
    """1件の判断とその後の実際の結果。"""

    action: str
    outcome: int  # 1=TP先着, 0=SL先着, -1=期限内に未決着, -2=見送り(WAIT)
    ev_r: float   # リスク1R単位の損益。見送りは0

    @property
    def mark(self) -> str:
        return {1: "○ 的中", 0: "× 外れ", -1: "△ 未決着", -2: "— 見送り", -3: "! 判断できず"}[self.outcome]


def evaluate_action(
    action: str,
    scan,
    entry_index: int,
    entry_price: float,
    atr_points: float,
    point_size: float,
    spread_points: float,
    sl_atr_mult: float,
    rr: float,
    failed: bool = False,
) -> Verdict:
    """判断どおりに入っていたら、その後どうなったかを実データで採点する。

    過去データで動かしている以上「その後」は分かっているので、ルールとAIを
    一致率ではなく**実際の損益**で比べられる。WAIT(見送り)は取引をしないので
    損益0として扱い、勝敗の分母からも外す。取引しない判断を「外れ」と数えると、
    危ない場面を避ける動き(=フィルターとしての価値)が評価できなくなるため。
    """
    if failed:
        # APIエラー等でWAITに落ちた回。相場を見て見送ったわけではないので、
        # 見送りとしても外れとしても数えない(集計から完全に外す)。
        return Verdict(action, -3, 0.0)
    if action not in ("BUY", "SELL"):
        return Verdict(action, -2, 0.0)

    sl_px = sl_atr_mult * atr_points * point_size
    tp_px = rr * sl_atr_mult * atr_points * point_size
    is_buy = action == "BUY"
    outcome = scan(
        entry_index,
        entry_price + tp_px if is_buy else entry_price - tp_px,
        entry_price - sl_px if is_buy else entry_price + sl_px,
        is_buy,
    )
    if outcome < 0:
        return Verdict(action, -1, 0.0)
    cost_r = spread_points / (sl_atr_mult * atr_points)
    return Verdict(action, outcome, (rr if outcome == 1 else -1.0) - cost_r)


def summarise(name: str, verdicts: list[Verdict]) -> str:
    traded = [v for v in verdicts if v.outcome in (0, 1)]
    skipped = sum(1 for v in verdicts if v.outcome == -2)
    failed = sum(1 for v in verdicts if v.outcome == -3)
    if not traded:
        return f"{name:<8}{'-':>8}{'-':>8}{'-':>10}{skipped:>10}{failed:>10}"
    wins = sum(1 for v in traded if v.outcome == 1)
    ev = sum(v.ev_r for v in traded) / len(traded)
    return f"{name:<8}{len(traded):>8}{wins:>8}{ev:>+10.3f}{skipped:>10}{failed:>10}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="保存済みの過去データでAI判断エンジンを走らせ、ルール判断と並べて表示する(発注しない)"
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="このAPIキーで使えるGeminiモデル名を一覧する(404の切り分け用)。キーは表示しない",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="実際に生成を通せるモデルを探し当てる(--list-modelsが有効と言うのに404になる場合)",
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
    parser.add_argument(
        "--eval-sl-mult",
        type=float,
        default=6.0,
        help="採点に使うSL幅(ATR倍率)。既定6(--geometryでコスト負けしにくかった水準)",
    )
    parser.add_argument("--eval-rr", type=float, default=1.5, help="採点に使うリスクリワード比。既定1.5")
    parser.add_argument("--no-evaluate", action="store_true", help="判断後の結果を採点しない(表示のみ)")
    parser.add_argument(
        "--sleep",
        type=float,
        default=6.0,
        help="API呼び出しの間隔(秒)。既定6(無料枠の毎分制限に当たらない程度)。0で無効",
    )
    parser.add_argument("--retries", type=int, default=2, help="レート制限(429)時の再試行回数。既定2")
    args = parser.parse_args()

    if args.list_models:
        list_gemini_models()
        return
    if args.probe:
        probe_generate_content()
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

    evaluate = not args.no_evaluate
    point_size = infer_point_size(candles)
    spreads = candles["spread"].to_numpy(dtype=float) if "spread" in candles.columns else None
    scan, _ = _make_forward_scanner(candles, max_horizon=480, optimistic_fill=False)

    agreements = comparable = 0
    rule_verdicts: list[Verdict] = []
    ai_verdicts: list[Verdict] = []

    for i, (end_index, window) in enumerate(windows, start=1):
        enriched = indicators.add_indicators(window)
        latest = enriched.iloc[-1]
        when = pd.Timestamp(latest["time"]) if "time" in enriched.columns else None
        close = float(latest["close"])

        print(f"--- {i}/{len(windows)}  {when}  終値={close:.3f} ---")
        if args.show_prompt:
            print("  [AIへ渡している文面]")
            for line in describe_market_conditions(enriched, config.SYMBOL, config.TIMEFRAME).splitlines():
                print(f"    {line}")
            print()

        atr = float(latest["atr"]) if "atr" in enriched.columns and not pd.isna(latest["atr"]) else 0.0
        atr_points = atr / point_size if point_size > 0 else 0.0
        spread = float(spreads[end_index]) if spreads is not None else 0.0

        def judge(signal: Signal) -> Verdict | None:
            if not evaluate or atr_points <= 0:
                return None
            return evaluate_action(
                signal.action, scan, end_index, close, atr_points, point_size,
                spread, args.eval_sl_mult, args.eval_rr,
                failed=bool(signal.details.get("error")),
            )

        rule_signal = rule_engine.decide(enriched)
        rule_verdict = judge(rule_signal)
        print(f"  ルール : {format_signal(rule_signal)}")
        breakdown = score_line(rule_signal)
        if breakdown:
            print(breakdown)
        if rule_verdict:
            rule_verdicts.append(rule_verdict)
            print(f"      結果: {rule_verdict.mark}")

        if args.sleep > 0 and i > 1:
            time.sleep(args.sleep)
        ai_signal = call_engine(ai_engine, enriched, args.retries, max(args.sleep, 30.0))
        ai_verdict = judge(ai_signal)
        print(f"  AI({args.engine}) : {format_signal(ai_signal)}")
        if ai_verdict:
            ai_verdicts.append(ai_verdict)
            print(f"      結果: {ai_verdict.mark}")

        if ai_signal.details.get("error"):
            print("  → AIの判断が取れなかったため、この回は集計から除外します\n")
        else:
            comparable += 1
            same = rule_signal.action == ai_signal.action
            agreements += same
            print(f"  → 判断は{'一致' if same else '不一致'}\n")

    if rule_verdicts or ai_verdicts:
        print(f"=== 採点(SL={args.eval_sl_mult:g}xATR / RR=1:{args.eval_rr:g}、実測スプレッド適用) ===")
        print(f"{'':<8}{'取引数':>8}{'的中':>8}{'EV(R)':>10}{'見送り':>10}{'判断不能':>10}")
        print(summarise("ルール", rule_verdicts))
        print(summarise(args.engine, ai_verdicts))
        print(
            "\nEV(R)は1取引あたりの期待損益(リスク1R=SL幅)。プラスなら勝ち越し。"
            "\n見送り(WAIT)は取引しないので分母から外している。危ない場面を避ける動きは"
            "\n「取引数が減り、EVが上がる」形で現れる。"
            "\n判断不能はAPIエラー等で判断自体が取れなかった回。見送りとは別に数え、"
            "\n集計には一切含めない(通信エラーを『慎重に見送った』と誤解しないため)。"
        )

    if comparable:
        print(f"\n判断の一致率: {agreements}/{comparable} ({agreements / comparable * 100:.0f}%)")
    print(
        "※一致率は成績ではない。ルール側は4年の監査でエッジ無しと確定しているので、"
        "\n  一致するほど良いわけではない(RESEARCH_FINDINGS.md 確定事項2)。見るべきはEV(R)。"
        "\n※この件数では何も結論できない。傾向を掴むには最低でも数百件が要る。"
        "\n※ここでの判断は表示だけで、発注にも学習にも使われない。"
    )


if __name__ == "__main__":
    main()
