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

import config
from ai_engine import Signal


class AiStatusError(RuntimeError):
    """ステータスファイルの取得・検証に失敗した場合に送出する。"""


@dataclass
class AiStatusSnapshot:
    action: str
    confidence: float
    reason: str
    symbol: str
    timeframe: str
    updated_at: float


def write_status(signal: Signal, symbol: str, timeframe: str) -> None:
    """main.pyの各サイクルの最後に呼び出し、最新の判断を書き出す。"""
    payload = {
        "action": signal.action,
        "confidence": signal.confidence,
        "reason": signal.reason,
        "symbol": symbol,
        "timeframe": timeframe,
        "updated_at": time.time(),
    }
    tmp_path = config.AI_STATUS_FILE_PATH.with_suffix(".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp_path.replace(config.AI_STATUS_FILE_PATH)


def read_status(max_staleness_seconds: float | None = None) -> AiStatusSnapshot:
    """settings_server.pyから呼び出され、最新のAI判断を返す。"""
    max_staleness_seconds = (
        max_staleness_seconds
        if max_staleness_seconds is not None
        else config.AI_STATUS_MAX_STALENESS_SECONDS
    )
    file_path = config.AI_STATUS_FILE_PATH

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
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AiStatusError(f"AI判断ファイルの形式が不正です: {exc}") from exc
