"""日次サマリー通知(Phase 6)。

1日1回(config.DAILY_SUMMARY_HOURで指定した時刻(UTC)以降の最初の
サイクル)、その日(UTC暦日)に決済された取引の損益をDiscordへ送信する。
main.pyのrun_once()から毎サイクル呼び出されるが、実際に送信するのは
1日1回だけ(送信済みかどうかをconfig.DAILY_SUMMARY_STATE_FILE_PATHに
保存し、プロセス再起動をまたいでも重複送信しない)。

BOT_RUN_STATEがRUNNING以外(STOPPED/EMERGENCY_STOPPED)でも送信対象に
含める(売買を止めていても、その日の結果は知りたいはずのため)。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import config
import discord_notifier
from trade_history_feed import FileTradeHistoryFeed, TradeHistoryError

logger = logging.getLogger("mt5_ai_trader")


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _load_last_sent_date() -> str | None:
    path = config.DAILY_SUMMARY_STATE_FILE_PATH
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("last_sent_date")
    except (OSError, json.JSONDecodeError):
        return None


def _save_last_sent_date(date_str: str) -> None:
    path = config.DAILY_SUMMARY_STATE_FILE_PATH
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump({"last_sent_date": date_str}, f)
        tmp_path.replace(path)
    except OSError:
        logger.exception("daily_summary: 送信状態の保存に失敗しました")


def maybe_send_daily_summary(feed: FileTradeHistoryFeed, now: datetime | None = None) -> None:
    """条件が揃っていれば、その日の損益サマリーをDiscordへ送信する。"""
    if not config.DISCORD_ENABLED or not config.DISCORD_NOTIFY_DAILY_SUMMARY:
        return

    now = now or datetime.now(timezone.utc)
    if now.hour < config.DAILY_SUMMARY_HOUR:
        return

    today = _date_str(now)
    if _load_last_sent_date() == today:
        return

    try:
        trades = feed.read_history()
    except TradeHistoryError:
        logger.warning("daily_summary: 取引履歴を取得できなかったため送信をスキップします")
        return

    todays_trades = [t for t in trades if _date_str(datetime.fromtimestamp(t.close_time, tz=timezone.utc)) == today]
    total_profit = sum(t.profit for t in todays_trades)
    win_count = sum(1 for t in todays_trades if t.profit > 0)
    win_rate = (win_count / len(todays_trades) * 100) if todays_trades else 0.0

    discord_notifier.notify_daily_summary(today, total_profit, len(todays_trades), win_rate)
    _save_last_sent_date(today)
    logger.info(
        "daily_summary: %sのサマリーを送信しました(取引数=%d, 損益=%.2f, 勝率=%.0f%%)",
        today,
        len(todays_trades),
        total_profit,
        win_rate,
    )
