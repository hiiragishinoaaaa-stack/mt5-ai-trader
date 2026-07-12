"""決済通知(Phase 8)。

trade_history_feed.py(EAが書き出す決済済み取引一覧)を毎サイクル確認し、
前回確認したときより新しく決済された取引があればDiscordへ通知する。
main.pyが発注(エントリー)時に送る通知(order_executor.py経由の
discord_notifier.notify_trade_executed)とは別で、こちらは「ポジションが
閉じた(利確/損切り/手動決済等)」タイミングを知らせる。

決済そのものはMT5(ブローカーサーバー)がSL/TP到達時に自動で行うため、
Python側は一切関与しない。この通知は「決済されたことを検知して知らせる」
だけの補助機能で、決済の実行そのものには一切影響しない。

BOT_RUN_STATEがRUNNING以外(STOPPED/EMERGENCY_STOPPED)でも動作する
(daily_summary.pyと同じ考え方。売買を止めていても決済の結果は知りたいはず)。
"""
from __future__ import annotations

import json
import logging

import config
import discord_notifier
from trade_history_feed import FileTradeHistoryFeed, TradeHistoryError

logger = logging.getLogger("mt5_ai_trader")


def _load_last_notified_close_time() -> float | None:
    path = config.CLOSE_NOTIFIER_STATE_FILE_PATH
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("last_notified_close_time")
    except (OSError, json.JSONDecodeError):
        return None


def _save_last_notified_close_time(value: float) -> None:
    path = config.CLOSE_NOTIFIER_STATE_FILE_PATH
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump({"last_notified_close_time": value}, f)
        tmp_path.replace(path)
    except OSError:
        logger.exception("close_notifier: 通知状態の保存に失敗しました")


def notify_newly_closed_trades(feed: FileTradeHistoryFeed) -> None:
    """前回チェック以降に新しく決済された取引があればDiscordへ通知する。"""
    try:
        trades = feed.read_history()
    except TradeHistoryError:
        # EAが未対応(v4.00未満)・未起動などで取得できない場合は静かにスキップする。
        return

    if not trades:
        return

    watermark = _load_last_notified_close_time()

    if watermark is None:
        # 初回起動時(状態ファイルが無い)は、既存の決済済み取引をまとめて
        # 通知せず(後追いスパム防止)、現時点の最新close_timeだけを基準値
        # として記録する。以降、これより新しい決済だけを通知する。
        newest = max(t.close_time for t in trades)
        _save_last_notified_close_time(float(newest))
        return

    new_trades = sorted((t for t in trades if t.close_time > watermark), key=lambda t: t.close_time)
    if not new_trades:
        return

    for trade in new_trades:
        discord_notifier.notify_trade_closed(trade)

    _save_last_notified_close_time(float(new_trades[-1].close_time))
