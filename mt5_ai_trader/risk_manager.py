"""エントリー頻度の制御・サーキットブレーカー。

RuleBasedAIEngine(ai_engine.py)の判断(BUY/SELL)そのものは変えず、実際に
発注リクエストを送出する前に呼び出す。以下のいずれかに抵触する場合は
エントリーをブロックする(main.pyはこの結果を見て、BUY/SELLをWAITへ
差し替える。ai_status/Discordにもブロックされた理由がそのまま反映される)。

- ENTRY_COOLDOWN_SECONDS: 直近のオープンから一定時間内は新規エントリーしない
- MAX_TRADES_PER_HOUR / MAX_TRADES_PER_DAY: 直近1時間/24時間のオープン回数上限
- LOSS_STREAK_THRESHOLD連敗 → COOLDOWN_AFTER_LOSSES_MINUTES分停止
- MAX_DAILY_LOSS_PERCENT: 当日(UTC日付)の決済損益が残高に対してこの%以上の
  マイナスなら新規停止

いずれも銘柄ごと(symbol引数で絞り込んだARTEMIS自身の取引のみ)に判定する。
決済済み取引(trade_history_feed)は、手動決済(Dashboard CLOSEボタン)と
EAの自動決済(SL/TP到達)を区別する情報を持たない(EA側がclose_reasonを
記録していないため)。そのため、この制御はいずれの決済方法であっても
「損失が出た」という事実だけを見て判定する(意図的な簡略化)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import config
from account_feed import AccountFeedError, FileAccountFeed
from trade_history_feed import ClosedTrade, FileTradeHistoryFeed, TradeHistoryError

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str = ""


def _today_utc_start_epoch(now: float) -> float:
    day_seconds = int(now) // _SECONDS_PER_DAY * _SECONDS_PER_DAY
    return float(day_seconds)


def _open_times_for_symbol(
    symbol: str,
    closed_trades: list[ClosedTrade],
    account_feed: FileAccountFeed,
) -> list[float]:
    """ARTEMIS自身が(過去に決済した、または現在保有中の)その銘柄のポジションを
    開いた時刻の一覧を返す。エントリー頻度の判定に使う。
    """
    times = [float(t.open_time) for t in closed_trades]
    try:
        state = account_feed.read_state()
    except AccountFeedError:
        state = None
    if state is not None:
        times.extend(
            float(p.open_time) for p in state.positions if p.symbol == symbol and p.is_artemis
        )
    return times


def check_entry_allowed(
    symbol: str,
    history_feed: FileTradeHistoryFeed | None = None,
    account_feed: FileAccountFeed | None = None,
    now: float | None = None,
) -> RiskCheckResult:
    """指定した銘柄に新規エントリーしてよいか判定する。

    trade_history_feed/account_feedが読み取れない(EA未起動等)場合、その
    チェック項目は「判定不能」として素通しする(安全側に倒しすぎて何も
    取引できなくなるのを避けるため。他のチェックがブロックしていれば
    そちらが優先される)。
    """
    history_feed = history_feed or FileTradeHistoryFeed()
    account_feed = account_feed or FileAccountFeed()

    if now is None:
        # EAが最後にファイルを書いた時刻(account_stateのupdated_at)を「今」の
        # 基準に使う。open_time/close_timeも同じEA由来・同じ補正定数
        # (config.EA_TIMESTAMP_CORRECTION_SECONDS)で補正されているため、
        # その定数が不正確(あるいはEA側のサーバー時刻ズレが時間とともに
        # 変化する)場合でも、両者の差である経過時間は正しく計算できる
        # (定数の誤差が両辺で相殺されるため)。account_stateが読めない場合
        # のみtime.time()にフォールバックする。
        try:
            now = account_feed.read_state().updated_at
        except AccountFeedError:
            now = time.time()

    try:
        all_trades = history_feed.read_history()
    except TradeHistoryError:
        all_trades = []
    symbol_trades = [t for t in all_trades if t.symbol == symbol and t.is_artemis]

    # 1) エントリークールダウン
    if config.ENTRY_COOLDOWN_SECONDS > 0:
        open_times = _open_times_for_symbol(symbol, symbol_trades, account_feed)
        if open_times:
            last_open = max(open_times)
            elapsed = now - last_open
            if elapsed < config.ENTRY_COOLDOWN_SECONDS:
                remaining = int(config.ENTRY_COOLDOWN_SECONDS - elapsed)
                return RiskCheckResult(False, f"クールダウン中です(残り約{remaining}秒)")

    # 2) 時間/日あたりの最大取引数
    if config.MAX_TRADES_PER_HOUR > 0 or config.MAX_TRADES_PER_DAY > 0:
        open_times = _open_times_for_symbol(symbol, symbol_trades, account_feed)
        if config.MAX_TRADES_PER_HOUR > 0:
            count = sum(1 for t in open_times if now - t < _SECONDS_PER_HOUR)
            if count >= config.MAX_TRADES_PER_HOUR:
                return RiskCheckResult(
                    False, f"直近1時間の取引数が上限({config.MAX_TRADES_PER_HOUR}回)に達しています"
                )
        if config.MAX_TRADES_PER_DAY > 0:
            count = sum(1 for t in open_times if now - t < _SECONDS_PER_DAY)
            if count >= config.MAX_TRADES_PER_DAY:
                return RiskCheckResult(
                    False, f"直近24時間の取引数が上限({config.MAX_TRADES_PER_DAY}回)に達しています"
                )

    # 3) 連敗後のクールダウン
    if config.COOLDOWN_AFTER_LOSSES_MINUTES > 0 and config.LOSS_STREAK_THRESHOLD > 0:
        closed_sorted = sorted(symbol_trades, key=lambda t: t.close_time)
        recent = closed_sorted[-config.LOSS_STREAK_THRESHOLD :]
        if len(recent) == config.LOSS_STREAK_THRESHOLD and all(t.profit < 0 for t in recent):
            cooldown_until = recent[-1].close_time + config.COOLDOWN_AFTER_LOSSES_MINUTES * 60
            if now < cooldown_until:
                remaining_minutes = int((cooldown_until - now) / 60) + 1
                return RiskCheckResult(
                    False,
                    f"{config.LOSS_STREAK_THRESHOLD}連敗のため一時停止中です(残り約{remaining_minutes}分)",
                )

    # 4) 当日の最大損失(%)
    if config.MAX_DAILY_LOSS_PERCENT > 0:
        try:
            state = account_feed.read_state()
        except AccountFeedError:
            state = None
        if state is not None and state.account.balance > 0:
            today_start = _today_utc_start_epoch(now)
            today_pnl = sum(t.profit for t in symbol_trades if t.close_time >= today_start)
            if today_pnl < 0:
                loss_percent = abs(today_pnl) / state.account.balance * 100
                if loss_percent >= config.MAX_DAILY_LOSS_PERCENT:
                    return RiskCheckResult(
                        False,
                        f"本日の損失が上限({config.MAX_DAILY_LOSS_PERCENT}%)に達しています"
                        f"(現在約{loss_percent:.1f}%)",
                    )

    return RiskCheckResult(True)
