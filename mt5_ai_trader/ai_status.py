"""AIの最新判断(BUY/SELL/WAIT)をJSONファイルへ書き出し/読み込みする。

main.pyが毎サイクルの判断結果をwrite_status()で書き出し、Dashboardは
settings_server.py経由でread_status()の内容を取得する。MT5(EA)を介さない、
Python内部だけのやり取りのため、EAブリッジのCommon\\Filesフォルダは使わない
(market_feed.py/account_feed.pyとは異なり、MT5側の起動有無に依存しない)。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import config
from ai_engine import Signal


class AiStatusError(RuntimeError):
    """ステータスファイルの取得・検証に失敗した場合に送出する。"""


def _rotate_if_needed(file_path: Path) -> None:
    """file_pathのサイズがconfig.AI_LOG_MAX_BYTES以上なら世代交代
    ローテーションする(<file>.1.jsonl → .2.jsonl → ...、config.
    AI_LOG_BACKUP_COUNT世代を超えた最古の世代は削除)。

    ai_decisions.jsonl/ai_shadow_log.jsonlはどちらも無制限に追記され
    続けるため、放置するとディスクを食い潰す(2026-07、Fable5との相談を
    踏まえて追加)。append_decision_log/append_shadow_logが追記の直前に
    呼び出す。AI_LOG_MAX_BYTES<=0の場合は何もしない(無効化)。
    """
    if config.AI_LOG_MAX_BYTES <= 0:
        return
    if not file_path.exists() or file_path.stat().st_size < config.AI_LOG_MAX_BYTES:
        return

    backup_count = config.AI_LOG_BACKUP_COUNT
    if backup_count <= 0:
        file_path.unlink()
        return

    oldest = file_path.with_name(f"{file_path.stem}.{backup_count}{file_path.suffix}")
    if oldest.exists():
        oldest.unlink()
    for gen in range(backup_count - 1, 0, -1):
        src = file_path.with_name(f"{file_path.stem}.{gen}{file_path.suffix}")
        if src.exists():
            dst = file_path.with_name(f"{file_path.stem}.{gen + 1}{file_path.suffix}")
            src.rename(dst)
    file_path.rename(file_path.with_name(f"{file_path.stem}.1{file_path.suffix}"))


@dataclass
class AiStatusSnapshot:
    action: str
    confidence: float
    reason: str
    symbol: str
    timeframe: str
    updated_at: float
    score: int | None = None
    required_score: int | None = None
    failed_required: dict[str, list[str]] | None = None
    adx: float | None = None
    gemini_shadow: dict | None = None


def write_status(signal: Signal, symbol: str, timeframe: str, shadow_signal: Signal | None = None) -> None:
    """main.pyの各サイクルの最後に呼び出し、最新の判断を書き出す。

    複数銘柄対応(Phase 12)により、銘柄ごとに別ファイル(config.
    ai_status_file_path())へ書き出す(config.SYMBOLと一致する場合は
    従来通りのファイル名のまま、後方互換)。

    score/required_score/failed_required(勝率優先ロジック⑩)は
    signal.details(ai_engine.RuleBasedAIEngine参照)から取り出し、
    Dashboardが構造化して表示できるようにする。RuleBasedAIEngine以外
    (LLM系エンジン等)ではdetailsに含まれないため、その場合はnull。
    adxも同様(診断用。売買判断にはまだ使っていない、ai_engine.py参照)。

    shadow_signal(config.GEMINI_SHADOW=true時のみ、ai_engine.
    get_shadow_engine参照)を渡すと、実際の発注判断(signal)とは別に
    「Geminiならどう判断したか」もgemini_shadowとしてDashboardへ表示
    できるように書き出す(発注には一切使わない、記録のみ)。
    """
    payload = {
        "action": signal.action,
        "confidence": signal.confidence,
        "reason": signal.reason,
        "symbol": symbol,
        "timeframe": timeframe,
        "updated_at": time.time(),
        "score": signal.details.get("score"),
        "required_score": signal.details.get("required_score"),
        "failed_required": signal.details.get("failed_required") or None,
        "adx": signal.details.get("adx"),
        "gemini_shadow": (
            {
                "action": shadow_signal.action,
                "confidence": shadow_signal.confidence,
                "reason": shadow_signal.reason,
            }
            if shadow_signal is not None
            else None
        ),
    }
    file_path = config.ai_status_file_path(symbol)
    tmp_path = file_path.with_suffix(".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp_path.replace(file_path)


def append_decision_log(signal: Signal, symbol: str, timeframe: str) -> None:
    """毎サイクルの判断を追記専用ログ(JSON Lines)へ残す。

    write_status()は最新1件だけを毎回上書きするため、REQUIRED_SCOREを
    どの値にすべきかを後から実測で検証する材料が残らなかった(2026-07、
    Fable5との相談を踏まえて追加)。こちらはBUY/SELL両方向のスコア内訳
    (ai_engine.RuleBasedAIEngine.decideが常にdetailsへ含めるようになった
    buy_score/buy_total/buy_failed/sell_score/sell_total/sell_failed)を
    1行1JSONで追記していく。RuleBasedAIEngine以外(LLM系エンジン等)では
    該当キーがdetailsに無いためnullになる。

    得点内訳だけでなく、その足の生の指標値(open/close/high/low/ema_fast/
    ema_slow/rsi/macd_hist/atr/spread/H1系)も一緒に記録する(2026-07、
    Fable5との相談を踏まえて追加)。スコアだけだと「RSI帯域を変えたら
    どうなっていたか」のような条件そのものの見直しが過去ログからはできない
    ため、生値もあれば再稼働なしで再採点できる。

    書き込み失敗(ディスク容量不足等)は呼び出し元(main.py)でログに
    残すだけにとどめ、判断・発注フロー自体は止めない設計を踏襲する
    (write_status関数のdocstring参照)。
    """
    payload = {
        "timestamp": time.time(),
        "symbol": symbol,
        "timeframe": timeframe,
        "action": signal.action,
        "confidence": signal.confidence,
        "reason": signal.reason,
        "required_score": signal.details.get("required_score"),
        "buy_score": signal.details.get("buy_score"),
        "buy_total": signal.details.get("buy_total"),
        "buy_failed": signal.details.get("buy_failed"),
        "sell_score": signal.details.get("sell_score"),
        "sell_total": signal.details.get("sell_total"),
        "sell_failed": signal.details.get("sell_failed"),
        "adx": signal.details.get("adx"),
        "regime": signal.details.get("regime"),
        "open": signal.details.get("open"),
        "close": signal.details.get("close"),
        "high": signal.details.get("high"),
        "low": signal.details.get("low"),
        "ema_fast": signal.details.get("ema_fast"),
        "ema_slow": signal.details.get("ema_slow"),
        "rsi": signal.details.get("rsi"),
        "macd_hist": signal.details.get("macd_hist"),
        "atr": signal.details.get("atr"),
        "spread": signal.details.get("spread"),
        "h1_ema_fast": signal.details.get("h1_ema_fast"),
        "h1_ema_slow": signal.details.get("h1_ema_slow"),
        "h1_slope_up": signal.details.get("h1_slope_up"),
        "h1_bars": signal.details.get("h1_bars"),
    }
    file_path = config.decision_log_file_path(symbol)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(file_path)
    with file_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.write("\n")


def append_shadow_log(rule_signal: Signal, shadow_signal: Signal, symbol: str, timeframe: str, price: float | None) -> None:
    """Geminiシャドーモード(config.GEMINI_SHADOW)の「ルール判断 vs Gemini
    判断」を追記専用ログ(JSON Lines)へ残す。

    実際の発注判断(rule_signal)とGeminiの判断(shadow_signal、発注には
    一切使わない)を1行に並べて記録する。priceはその足のclose(判断時点の
    参考価格)で、後から「もしGeminiに従っていたら」の仮想損益を計算する際に
    その後の値動きと突き合わせるために残す(このログ自体は仮想損益の集計
    までは行わない、生データのみ)。
    """
    payload = {
        "timestamp": time.time(),
        "symbol": symbol,
        "timeframe": timeframe,
        "price": price,
        "rule_action": rule_signal.action,
        "rule_score": rule_signal.details.get("score"),
        "rule_required_score": rule_signal.details.get("required_score"),
        "gemini_action": shadow_signal.action,
        "gemini_confidence": shadow_signal.confidence,
        "gemini_reason": shadow_signal.reason,
        "agree": rule_signal.action == shadow_signal.action,
    }
    file_path = config.shadow_log_file_path(symbol)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(file_path)
    with file_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.write("\n")


def read_status(symbol: str, max_staleness_seconds: float | None = None) -> AiStatusSnapshot:
    """settings_server.pyから呼び出され、指定した銘柄の最新のAI判断を返す。"""
    max_staleness_seconds = (
        max_staleness_seconds
        if max_staleness_seconds is not None
        else config.AI_STATUS_MAX_STALENESS_SECONDS
    )
    file_path = config.ai_status_file_path(symbol)

    if not file_path.exists():
        raise AiStatusError(
            f"AI判断ファイルが見つかりません: {file_path}\nmain.pyが起動しているか確認してください。"
        )

    try:
        with file_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise AiStatusError(f"AI判断ファイルの読み込みに失敗しました: {file_path} ({exc})") from exc

    updated_at = payload.get("updated_at")
    if updated_at is None:
        raise AiStatusError("AI判断ファイルにupdated_atがありません(壊れている可能性があります)")

    age_seconds = time.time() - float(updated_at)
    if age_seconds > max_staleness_seconds:
        raise AiStatusError(
            f"AI判断が古すぎます(最終更新から{age_seconds:.0f}秒経過、"
            f"許容={max_staleness_seconds}秒)。main.pyが動作しているか確認してください。"
        )

    try:
        return AiStatusSnapshot(
            action=str(payload["action"]),
            confidence=float(payload["confidence"]),
            reason=str(payload["reason"]),
            symbol=str(payload["symbol"]),
            timeframe=str(payload["timeframe"]),
            updated_at=float(payload["updated_at"]),
            score=payload.get("score"),
            required_score=payload.get("required_score"),
            failed_required=payload.get("failed_required"),
            adx=payload.get("adx"),
            gemini_shadow=payload.get("gemini_shadow"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AiStatusError(f"AI判断ファイルの形式が不正です: {exc}") from exc
