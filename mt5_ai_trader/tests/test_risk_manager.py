"""risk_manager.py の単体テスト。MT5/EA不要(フェイクのfeedを使う)。"""
from __future__ import annotations

import time

import pytest

import config
import risk_manager
from account_feed import AccountFeedError, AccountInfo, AccountState, Position
from trade_history_feed import ClosedTrade, TradeHistoryError


def _trade(**overrides) -> ClosedTrade:
    base = dict(
        position_id=1,
        symbol="USDJPY",
        type="BUY",
        volume=0.1,
        price_open=157.0,
        price_close=157.1,
        profit=1000.0,
        open_time=int(time.time()) - 3600,
        close_time=int(time.time()) - 3000,
        magic=990101,
        is_artemis=True,
    )
    base.update(overrides)
    return ClosedTrade(**base)


def _position(**overrides) -> Position:
    base = dict(
        ticket=1,
        symbol="USDJPY",
        type="BUY",
        volume=0.1,
        price_open=157.0,
        price_current=157.05,
        sl=156.0,
        tp=158.0,
        profit=50.0,
        open_time=int(time.time()) - 100,
        magic=990101,
        is_artemis=True,
    )
    base.update(overrides)
    return Position(**base)


class _FakeHistoryFeed:
    def __init__(self, trades: list[ClosedTrade] | None = None, error: bool = False):
        self._trades = trades or []
        self._error = error

    def read_history(self, max_staleness_seconds=None):
        if self._error:
            raise TradeHistoryError("no data")
        return list(self._trades)


class _FakeAccountFeed:
    def __init__(self, positions: list[Position] | None = None, balance: float = 10_000.0, error: bool = False):
        self._positions = positions or []
        self._balance = balance
        self._error = error

    def read_state(self, max_staleness_seconds=None):
        if self._error:
            raise AccountFeedError("no data")
        account = AccountInfo(
            login=1, currency="JPY", balance=self._balance, equity=self._balance, margin=0.0, margin_free=self._balance, profit=0.0
        )
        return AccountState(account=account, positions=list(self._positions))


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(config, "MAX_TRADES_PER_HOUR", 0)
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 0)
    monkeypatch.setattr(config, "LOSS_STREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "COOLDOWN_AFTER_LOSSES_MINUTES", 0)
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_PERCENT", 0.0)


def test_allowed_when_all_checks_disabled():
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(), _FakeAccountFeed())
    assert result.allowed is True


def test_cooldown_blocks_entry_shortly_after_open(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_COOLDOWN_SECONDS", 600)
    now = time.time()
    positions = [_position(open_time=int(now) - 60)]  # 1分前にオープン
    result = risk_manager.check_entry_allowed(
        "USDJPY", _FakeHistoryFeed(), _FakeAccountFeed(positions=positions), now=now
    )
    assert result.allowed is False
    assert "クールダウン中" in result.reason


def test_cooldown_allows_entry_after_elapsed(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_COOLDOWN_SECONDS", 600)
    now = time.time()
    positions = [_position(open_time=int(now) - 700)]  # 十分前にオープン
    result = risk_manager.check_entry_allowed(
        "USDJPY", _FakeHistoryFeed(), _FakeAccountFeed(positions=positions), now=now
    )
    assert result.allowed is True


def test_cooldown_ignores_other_symbol(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_COOLDOWN_SECONDS", 600)
    now = time.time()
    positions = [_position(symbol="EURUSD", open_time=int(now) - 10)]
    result = risk_manager.check_entry_allowed(
        "USDJPY", _FakeHistoryFeed(), _FakeAccountFeed(positions=positions), now=now
    )
    assert result.allowed is True


def test_max_trades_per_hour_blocks_when_reached(monkeypatch):
    monkeypatch.setattr(config, "MAX_TRADES_PER_HOUR", 2)
    now = time.time()
    trades = [_trade(open_time=int(now) - 600), _trade(open_time=int(now) - 1200)]
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(), now=now)
    assert result.allowed is False
    assert "1時間" in result.reason


def test_max_trades_per_hour_ignores_trades_outside_window(monkeypatch):
    monkeypatch.setattr(config, "MAX_TRADES_PER_HOUR", 2)
    now = time.time()
    trades = [_trade(open_time=int(now) - 7200), _trade(open_time=int(now) - 7300)]
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(), now=now)
    assert result.allowed is True


def test_max_trades_per_day_blocks_when_reached(monkeypatch):
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 3)
    now = time.time()
    trades = [_trade(open_time=int(now) - 3600 * h) for h in (1, 5, 10)]
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(), now=now)
    assert result.allowed is False
    assert "24時間" in result.reason


def test_loss_streak_blocks_entry(monkeypatch):
    monkeypatch.setattr(config, "LOSS_STREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "COOLDOWN_AFTER_LOSSES_MINUTES", 30)
    now = time.time()
    trades = [
        _trade(close_time=int(now) - 300, profit=-500.0),
        _trade(close_time=int(now) - 200, profit=-300.0),
        _trade(close_time=int(now) - 100, profit=-200.0),
    ]
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(), now=now)
    assert result.allowed is False
    assert "連敗" in result.reason


def test_loss_streak_allows_entry_after_cooldown_elapsed(monkeypatch):
    monkeypatch.setattr(config, "LOSS_STREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "COOLDOWN_AFTER_LOSSES_MINUTES", 30)
    now = time.time()
    trades = [
        _trade(close_time=int(now) - 3000, profit=-500.0),
        _trade(close_time=int(now) - 2900, profit=-300.0),
        _trade(close_time=int(now) - 2800, profit=-200.0),  # 30分以上前に3連敗完了
    ]
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(), now=now)
    assert result.allowed is True


def test_loss_streak_not_triggered_when_a_win_breaks_the_streak(monkeypatch):
    monkeypatch.setattr(config, "LOSS_STREAK_THRESHOLD", 3)
    monkeypatch.setattr(config, "COOLDOWN_AFTER_LOSSES_MINUTES", 30)
    now = time.time()
    trades = [
        _trade(close_time=int(now) - 400, profit=-500.0),
        _trade(close_time=int(now) - 300, profit=200.0),  # 勝ちで連敗が途切れる
        _trade(close_time=int(now) - 200, profit=-300.0),
        _trade(close_time=int(now) - 100, profit=-200.0),
    ]
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(), now=now)
    assert result.allowed is True


def test_max_daily_loss_percent_blocks_entry(monkeypatch):
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_PERCENT", 5.0)
    now = time.time()
    today_start = int(now) // 86400 * 86400
    trades = [_trade(close_time=today_start + 100, profit=-600.0)]  # 10000残高の6%
    result = risk_manager.check_entry_allowed(
        "USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(balance=10_000.0), now=now
    )
    assert result.allowed is False
    assert "損失が上限" in result.reason


def test_max_daily_loss_percent_ignores_yesterdays_losses(monkeypatch):
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_PERCENT", 5.0)
    now = time.time()
    yesterday = int(now) - 90000
    trades = [_trade(close_time=yesterday, profit=-2000.0)]
    result = risk_manager.check_entry_allowed(
        "USDJPY", _FakeHistoryFeed(trades), _FakeAccountFeed(balance=10_000.0), now=now
    )
    assert result.allowed is True


def test_same_direction_min_bars_blocks_same_direction_entry(monkeypatch):
    monkeypatch.setattr(config, "SAME_DIRECTION_MIN_BARS", 2)
    monkeypatch.setattr(config, "TIMEFRAME", "M15")  # 1本=900秒、2本=1800秒
    now = time.time()
    positions = [_position(type="BUY", open_time=int(now) - 100)]  # 1800秒未満
    result = risk_manager.check_entry_allowed(
        "USDJPY",
        _FakeHistoryFeed(),
        _FakeAccountFeed(positions=positions),
        now=now,
        direction="BUY",
    )
    assert result.allowed is False
    assert "同方向" in result.reason


def test_same_direction_min_bars_ignores_opposite_direction(monkeypatch):
    monkeypatch.setattr(config, "SAME_DIRECTION_MIN_BARS", 2)
    monkeypatch.setattr(config, "TIMEFRAME", "M15")
    now = time.time()
    positions = [_position(type="BUY", open_time=int(now) - 100)]
    result = risk_manager.check_entry_allowed(
        "USDJPY",
        _FakeHistoryFeed(),
        _FakeAccountFeed(positions=positions),
        now=now,
        direction="SELL",  # 直近のBUYとは逆方向なのでブロックされない
    )
    assert result.allowed is True


def test_same_direction_min_bars_allows_after_elapsed(monkeypatch):
    monkeypatch.setattr(config, "SAME_DIRECTION_MIN_BARS", 2)
    monkeypatch.setattr(config, "TIMEFRAME", "M15")
    now = time.time()
    positions = [_position(type="BUY", open_time=int(now) - 2000)]  # 1800秒以上経過
    result = risk_manager.check_entry_allowed(
        "USDJPY",
        _FakeHistoryFeed(),
        _FakeAccountFeed(positions=positions),
        now=now,
        direction="BUY",
    )
    assert result.allowed is True


def test_reentry_min_atr_mult_blocks_close_price(monkeypatch):
    monkeypatch.setattr(config, "REENTRY_MIN_ATR_MULT", 0.5)
    now = time.time()
    positions = [_position(type="SELL", price_open=157.0, open_time=int(now) - 5000)]
    result = risk_manager.check_entry_allowed(
        "USDJPY",
        _FakeHistoryFeed(),
        _FakeAccountFeed(positions=positions),
        now=now,
        direction="BUY",
        current_price=157.02,  # 前回エントリー価格から0.02(atr=1.0で0.02×ATR)しか離れていない
        atr_price=1.0,
    )
    assert result.allowed is False
    assert "エントリー価格" in result.reason


def test_reentry_min_atr_mult_allows_far_price(monkeypatch):
    monkeypatch.setattr(config, "REENTRY_MIN_ATR_MULT", 0.5)
    now = time.time()
    positions = [_position(type="SELL", price_open=157.0, open_time=int(now) - 5000)]
    result = risk_manager.check_entry_allowed(
        "USDJPY",
        _FakeHistoryFeed(),
        _FakeAccountFeed(positions=positions),
        now=now,
        direction="BUY",
        current_price=158.0,  # 1.0×ATR離れている
        atr_price=1.0,
    )
    assert result.allowed is True


def test_missing_history_data_does_not_block_entry():
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(error=True), _FakeAccountFeed())
    assert result.allowed is True


def test_missing_account_data_does_not_block_entry(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_COOLDOWN_SECONDS", 600)
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_PERCENT", 5.0)
    result = risk_manager.check_entry_allowed("USDJPY", _FakeHistoryFeed(), _FakeAccountFeed(error=True))
    assert result.allowed is True
