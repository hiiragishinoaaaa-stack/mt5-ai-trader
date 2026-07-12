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
# discord.com手前のCloudflareが、urllib標準のUser-Agent(例: "Python-urllib/3.12")
# を自動化されたアクセスとみなして403(error code: 1010)で拒否するため、
# 一般的なブラウザのUser-Agentを明示的に指定する。
_USER_AGENT = "Mozilla/5.0 (compatible; ARTEMIS-Bot/1.0)"


def _send(content: str) -> None:
    if not config.DISCORD_ENABLED or not config.DISCORD_WEBHOOK_URL:
        return

    body = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        config.DISCORD_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
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


def notify_daily_summary(date_str: str, total_profit: float, trade_count: int, win_rate: float) -> None:
    """1日1回、その日の損益サマリーを送信する(daily_summary.pyから呼び出す)。"""
    if not config.DISCORD_NOTIFY_DAILY_SUMMARY:
        return
    emoji = "\U0001f4c8" if total_profit >= 0 else "\U0001f4c9"  # chart up/down
    _send(
        f"{emoji} **{date_str} 日次サマリー**\n"
        f"損益: {total_profit:+.2f}\n"
        f"取引数: {trade_count}件 / 勝率: {win_rate:.0f}%"
    )
