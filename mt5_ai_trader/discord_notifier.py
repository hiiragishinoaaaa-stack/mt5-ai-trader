"""Discord Webhook通知(取引実行時・エラー時)。

外部ライブラリを追加しないため、urllib.requestで直接Discord WebhookへPOSTする。
DISCORD_ENABLED=false、またはWebhook URL未設定の場合は何もしない(既定OFF)。
Webhook送信の失敗はログに記録するだけで、呼び出し元の処理(発注等)には
一切影響させない(通知はあくまで補助機能であり、これが失敗しても売買は
継続できなければならない)。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import config

logger = logging.getLogger("mt5_ai_trader")

_REQUEST_TIMEOUT_SECONDS = 5


def _send(content: str) -> None:
    if not config.DISCORD_ENABLED or not config.DISCORD_WEBHOOK_URL:
        return

    body = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        config.DISCORD_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("discord_notifier: Discordへの通知送信に失敗しました: %s", exc)


def notify_trade_executed(action: str, symbol: str, volume: float, ticket: int | None, message: str) -> None:
    """発注が成功した(EAがMT5への送信に成功した)ときに呼び出す。"""
    if not config.DISCORD_NOTIFY_ON_TRADE:
        return
    emoji = "\U0001f7e2" if action == "BUY" else "\U0001f534"  # green/red circle
    _send(f"{emoji} **{action} {symbol}** volume={volume}\nticket={ticket}\n{message}")


def notify_order_failed(action: str, symbol: str, message: str) -> None:
    """発注がEA側で拒否された、またはタイムアウトしたときに呼び出す。"""
    if not config.DISCORD_NOTIFY_ON_ERROR:
        return
    _send(f"⚠️ **発注失敗** {action} {symbol}\n{message}")
