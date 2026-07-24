"""backtest_audit.py の単体テスト。MT5/EA不要、合成データのみで実行できる。"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import backtest_audit as audit
from backtest_audit import AuditBar, baseline_result, breakeven_win_rate, quantile_results, single_condition_results
from backtest_replay import ReplayTrade


def _trade(direction: str, index: int, pnl: float, reason: str = "take_profit") -> ReplayTrade:
    return ReplayTrade(
        direction=direction,
        entry_index=index,
        entry_time=pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=index),
        entry_price=100.0,
        pnl_points=pnl,
        reason=reason,
    )


def _audit_bar(index: int, h1: str | None, buy_conds, sell_conds, **kw) -> AuditBar:
    defaults = dict(
        time=pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=index),
        close=100.0,
        h1_direction=h1,
        adx=kw.get("adx"),
        regime=kw.get("regime"),
        rsi=kw.get("rsi"),
        ema_dist_atr=kw.get("ema_dist_atr"),
        atr_points=kw.get("atr_points"),
        macd_hist=kw.get("macd_hist"),
        buy_conditions=buy_conds,
        sell_conditions=sell_conds,
    )
    return AuditBar(index=index, **defaults)


# --- breakeven_win_rate -------------------------------------------------------


def test_breakeven_win_rate_rr_1_to_2():
    assert breakeven_win_rate(200, 400) == pytest.approx(33.333, abs=0.01)


def test_breakeven_win_rate_rr_1_to_1():
    assert breakeven_win_rate(200, 200) == pytest.approx(50.0)


def test_breakeven_win_rate_zero_guard():
    assert breakeven_win_rate(0, 0) == 0.0


# --- baseline_result ----------------------------------------------------------


def test_baseline_result_uses_h1_direction_and_skips_none():
    bars = [
        _audit_bar(0, "BUY", [], []),
        _audit_bar(1, "SELL", [], []),
        _audit_bar(2, None, [], []),  # H1判定不能はスキップ
    ]
    outcomes = {
        (0, "BUY"): _trade("BUY", 0, 400.0),
        (0, "SELL"): _trade("SELL", 0, -200.0),
        (1, "BUY"): _trade("BUY", 1, -200.0),
        (1, "SELL"): _trade("SELL", 1, 400.0),
    }

    result = baseline_result(bars, outcomes)

    assert len(result.trades) == 2  # index2(H1=None)は除外
    assert result.trades[0].direction == "BUY"
    assert result.trades[1].direction == "SELL"
    assert result.win_rate == pytest.approx(100.0)  # 両方TP


# --- single_condition_results -------------------------------------------------


def test_single_condition_groups_buy_and_sell_into_same_family():
    """「上昇トレンド(EMA)」(BUY)と「下降トレンド(EMA)」(SELL)は同じ
    ファミリー「EMAトレンド方向」に合算される。
    """
    bars = [
        _audit_bar(0, "BUY", [("上昇トレンド(EMA)", True)], [("下降トレンド(EMA)", False)]),
        _audit_bar(1, "SELL", [("上昇トレンド(EMA)", False)], [("下降トレンド(EMA)", True)]),
    ]
    outcomes = {
        (0, "BUY"): _trade("BUY", 0, 400.0),
        (0, "SELL"): _trade("SELL", 0, -200.0),
        (1, "BUY"): _trade("BUY", 1, -200.0),
        (1, "SELL"): _trade("SELL", 1, 400.0),
    }

    results = single_condition_results(bars, outcomes)

    assert "EMAトレンド方向" in results
    family = results["EMAトレンド方向"]
    # index0はBUY条件成立→BUY結果(+400)、index1はSELL条件成立→SELL結果(+400)
    assert len(family.trades) == 2
    assert family.win_rate == pytest.approx(100.0)


def test_single_condition_only_counts_bars_where_condition_holds():
    bars = [
        _audit_bar(0, "BUY", [("ATR最低値以上", True)], [("ATR最低値以上", True)]),
        _audit_bar(1, "BUY", [("ATR最低値以上", False)], [("ATR最低値以上", False)]),
    ]
    outcomes = {
        (0, "BUY"): _trade("BUY", 0, 400.0),
        (0, "SELL"): _trade("SELL", 0, 400.0),
        (1, "BUY"): _trade("BUY", 1, -200.0),
        (1, "SELL"): _trade("SELL", 1, -200.0),
    }

    results = single_condition_results(bars, outcomes)

    # ATR最低値以上は方向非依存ラベル。index0でBUY+SELL両方成立(2件)、index1は不成立。
    assert len(results["ATR最低値以上"].trades) == 2
    assert results["ATR最低値以上"].win_rate == pytest.approx(100.0)


# --- quantile_results ---------------------------------------------------------


def test_quantile_results_splits_by_metric_and_is_ordered_low_to_high():
    bars = [
        _audit_bar(i, "BUY", [], [], rsi=float(i * 10))
        for i in range(10)
    ]
    outcomes = {(i, "BUY"): _trade("BUY", i, 400.0 if i >= 5 else -200.0) for i in range(10)}

    quantiles = quantile_results(bars, outcomes, "rsi", "BUY", n_quantiles=5)

    assert len(quantiles) == 5
    # 分位は低い順。最初の分位(RSI低)は負け、最後の分位(RSI高)は勝ち。
    first_label, first_result = quantiles[0]
    last_label, last_result = quantiles[-1]
    assert first_result.win_rate == pytest.approx(0.0)
    assert last_result.win_rate == pytest.approx(100.0)


def test_quantile_results_skips_none_metric_values():
    bars = [_audit_bar(i, "BUY", [], [], rsi=None) for i in range(10)]
    outcomes = {(i, "BUY"): _trade("BUY", i, 400.0) for i in range(10)}

    quantiles = quantile_results(bars, outcomes, "rsi", "BUY", n_quantiles=5)

    assert quantiles == []  # 全部Noneなので分位を作れない


# --- compute_audit_bars / precompute_forward_outcomes (結合) --------------------


def _synthetic_candles(n: int) -> pd.DataFrame:
    rows = []
    price = 150.0
    t = 1700000000
    for i in range(n):
        price += 0.02 if i % 3 == 0 else -0.01
        o = price
        c = price + 0.005
        h = max(o, c) + 0.02
        low = min(o, c) - 0.02
        rows.append({"time": t, "open": o, "high": h, "low": low, "close": c, "spread": 2})
        t += 900
        price = c
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def test_compute_audit_bars_produces_conditions_and_indicators():
    candles = _synthetic_candles(150)
    bars = audit.compute_audit_bars(candles, bars_count=100)

    assert len(bars) == 150 - 100 + 1
    bar = bars[-1]
    assert bar.buy_conditions  # 条件が計算されている
    assert bar.sell_conditions
    assert isinstance(bar.buy_score, int)
    assert bar.rsi is not None
    # BUY条件とSELL条件は同じdfから来るので同数
    assert len(bar.buy_conditions) == len(bar.sell_conditions)


def test_precompute_forward_outcomes_covers_both_directions():
    candles = _synthetic_candles(150)
    bars = audit.compute_audit_bars(candles, bars_count=100)
    outcomes = audit.precompute_forward_outcomes(
        candles, bars, sl_points=200, tp_points=400, point_size=0.001, spread_points=0.0, optimistic_fill=False
    )

    for bar in bars:
        assert (bar.index, "BUY") in outcomes
        assert (bar.index, "SELL") in outcomes


def test_precompute_forward_outcomes_applies_spread():
    candles = _synthetic_candles(150)
    bars = audit.compute_audit_bars(candles, bars_count=100)
    no_spread = audit.precompute_forward_outcomes(candles, bars, 200, 400, 0.001, 0.0, False)
    with_spread = audit.precompute_forward_outcomes(candles, bars, 200, 400, 0.001, 10.0, False)

    # 決済したトレードでは、スプレッド分だけpnlが小さくなっている。
    for key, trade in no_spread.items():
        if trade.reason != "still_open":
            assert with_spread[key].pnl_points == pytest.approx(trade.pnl_points - 10.0)


# --- CLI end-to-end smoke test ------------------------------------------------


def test_main_runs_end_to_end(tmp_path, monkeypatch, capsys):
    candles = _synthetic_candles(150)
    payload = {
        "symbol": "USDJPY",
        "timeframe": "M15",
        "exported_at": int(candles.iloc[-1]["time"].timestamp()),
        "candles": [
            {
                "time": int(row.time.timestamp()),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "spread": 2,
            }
            for row in candles.itertuples()
        ],
    }
    candles_file = tmp_path / "history.json"
    candles_file.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["backtest_audit.py", "--candles-file", str(candles_file), "--bars-count", "100", "--no-regime-split"],
    )

    audit.main()

    out = capsys.readouterr().out
    assert "スコア分布" in out
    assert "ベースライン" in out
    assert "単一条件" in out
    assert "損益分岐%" in out
