"""market_feed.py の単体テスト。MT5/EA/実ファイルシステムのMT5パス不要。

config.MARKET_DATA_FILE_PATH を一時ファイルに差し替えてテストする。
"""
from __future__ import annotations

import json
import time

import pytest

import config
import market_feed


def _write_payload(path, **overrides):
    payload = {
        "symbol": "USDJPY",
        "timeframe": "M15",
        "updated_at": time.time(),
        "tick": {"bid": 157.123, "ask": 157.126, "time": time.time()},
        "candles": [
            {
                "time": time.time() - (10 - i) * 900,
                "open": 157.0 + i * 0.01,
                "high": 157.05 + i * 0.01,
                "low": 156.95 + i * 0.01,
                "close": 157.02 + i * 0.01,
                "tick_volume": 100,
                "spread": 1,
                "real_volume": 0,
            }
            for i in range(10)
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _patch_market_data_path(tmp_path, monkeypatch):
    file_path = tmp_path / "artemis_market_data.json"
    monkeypatch.setattr(config, "MARKET_DATA_FILE_PATH", file_path)
    return file_path


def test_read_snapshot_success(tmp_path):
    file_path = config.MARKET_DATA_FILE_PATH
    _write_payload(file_path)

    feed = market_feed.FileMarketFeed()
    snapshot = feed.read_snapshot("USDJPY", "M15")

    assert snapshot.tick.bid == 157.123
    assert snapshot.tick.ask == 157.126
    assert len(snapshot.candles) == 10
    assert list(snapshot.candles.columns) == market_feed._CANDLE_COLUMNS


def test_read_snapshot_missing_file_raises():
    feed = market_feed.FileMarketFeed()
    with pytest.raises(market_feed.MarketFeedError, match="見つかりません"):
        feed.read_snapshot("USDJPY", "M15")


def test_read_snapshot_stale_data_raises():
    file_path = config.MARKET_DATA_FILE_PATH
    _write_payload(file_path, updated_at=time.time() - 999)

    feed = market_feed.FileMarketFeed()
    with pytest.raises(market_feed.MarketFeedError, match="古すぎます"):
        feed.read_snapshot("USDJPY", "M15", max_staleness_seconds=30)


def test_read_snapshot_symbol_mismatch_raises():
    file_path = config.MARKET_DATA_FILE_PATH
    _write_payload(file_path, symbol="EURUSD")

    feed = market_feed.FileMarketFeed()
    with pytest.raises(market_feed.MarketFeedError, match="一致しません"):
        feed.read_snapshot("USDJPY", "M15")


def test_read_snapshot_corrupted_json_raises():
    file_path = config.MARKET_DATA_FILE_PATH
    file_path.write_text("{not valid json", encoding="utf-8")

    feed = market_feed.FileMarketFeed()
    with pytest.raises(market_feed.MarketFeedError):
        feed.read_snapshot("USDJPY", "M15")


def test_snapshot_feeds_indicators_and_ai_engine():
    """EAブリッジ経由のデータでも既存のindicators.py/ai_engine.pyがそのまま使えることを確認する。"""
    import indicators
    from ai_engine import RuleBasedAIEngine

    file_path = config.MARKET_DATA_FILE_PATH
    _write_payload(file_path)

    feed = market_feed.FileMarketFeed()
    snapshot = feed.read_snapshot("USDJPY", "M15")

    enriched = indicators.add_indicators(snapshot.candles)
    signal = RuleBasedAIEngine().decide(enriched)

    assert signal.action in ("BUY", "SELL", "WAIT")
