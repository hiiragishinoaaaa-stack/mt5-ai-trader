"""backtest_audit.py の単体テスト。MT5/EA不要、合成データのみで実行できる。"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import backtest_audit as audit
from backtest_audit import (
    AuditBar,
    _quarter_key,
    assign_periods,
    baseline_result,
    breakeven_win_rate,
    quantile_results,
    single_condition_results,
)
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


def test_breakeven_win_rate_includes_spread():
    """pnlからスプレッドを引く以上、分岐点もスプレッド込みでなければならない。
    SL=100/TP=200/s=15 なら 33.3%ではなく 115/300 = 38.3%。
    """
    assert breakeven_win_rate(100, 200, 15) == pytest.approx(38.333, abs=0.01)


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


# --- 期間別(by-period)モード ---------------------------------------------------


def test_quarter_key_maps_month_to_quarter():
    assert _quarter_key(pd.Timestamp("2024-01-15")) == "2024-Q1"
    assert _quarter_key(pd.Timestamp("2024-04-01")) == "2024-Q2"
    assert _quarter_key(pd.Timestamp("2024-09-30")) == "2024-Q3"
    assert _quarter_key(pd.Timestamp("2024-12-31")) == "2024-Q4"


def test_assign_periods_separates_discovery_window():
    """直近discovery_days日は四半期側から分離され "[発見]" になる。"""
    base = pd.Timestamp("2024-06-30")
    bars = [
        _audit_bar(0, "BUY", [], []),  # 古い(四半期側)
        _audit_bar(1, "BUY", [], []),  # 直近(発見側)
    ]
    bars[0].time = pd.Timestamp("2024-01-10")  # cutoffより前
    bars[1].time = base  # 最新

    groups = assign_periods(bars, discovery_days=30)

    assert "[発見]" in groups
    assert len(groups["[発見]"]) == 1
    assert groups["[発見]"][0].index == 1
    # 古いバーは四半期キーへ
    quarter_keys = [k for k in groups if k != "[発見]"]
    assert quarter_keys == ["2024-Q1"]
    assert groups["2024-Q1"][0].index == 0


def test_compute_period_bars_computes_metrics_without_conditions():
    candles = _synthetic_candles(300)
    bars = audit.compute_period_bars(candles, bars_count=100)

    assert bars
    bar = bars[-1]
    # 軽量版なので条件別成否は計算しない(空)
    assert bar.buy_conditions == []
    assert bar.sell_conditions == []
    # だが分位・レジームに必要な指標は入っている
    assert bar.rsi is not None
    assert bar.macd_hist is not None
    assert bar.regime in ("TRENDING", "RANGING", None)


# --- ジオメトリ掃引(--geometry)モード -----------------------------------------


def test_geometry_sweep_returns_row_per_combination():
    candles = _synthetic_candles(600)
    bars = audit.compute_period_bars(candles, bars_count=100, point_size=0.001)

    rows, atr_median, spread_median = audit.geometry_sweep(
        candles, bars, 0.001, [1.0, 2.0], [1.0, 2.0], sample_step=3, max_horizon=64
    )

    assert len(rows) == 4  # 2つのSL幅 × 2つのRR
    assert atr_median > 0
    assert spread_median == 2.0  # _synthetic_candlesはspread=2
    for row in rows:
        assert row.trades > 0
        assert 0.0 <= row.win_rate <= 100.0


def test_geometry_sweep_required_delta_shrinks_as_targets_widen():
    """必要Δp = スプレッド/(SL+TP)。狙いを広げるほど必要なエッジは小さくなる
    ——これがこの監査の核心。
    """
    candles = _synthetic_candles(600)
    bars = audit.compute_period_bars(candles, bars_count=100, point_size=0.001)

    rows, _, _ = audit.geometry_sweep(
        candles, bars, 0.001, [0.5, 3.0], [2.0], sample_step=3, max_horizon=64
    )
    narrow = next(r for r in rows if r.sl_atr_mult == 0.5)
    wide = next(r for r in rows if r.sl_atr_mult == 3.0)

    assert wide.required_delta_pp < narrow.required_delta_pp
    # SL幅を6倍にすれば必要Δpはおよそ1/6になる
    assert wide.required_delta_pp == pytest.approx(narrow.required_delta_pp / 6, rel=0.1)


def test_geometry_sweep_spread_override_beats_candle_spread():
    candles = _synthetic_candles(400)
    bars = audit.compute_period_bars(candles, bars_count=100, point_size=0.001)

    _, _, spread_median = audit.geometry_sweep(
        candles, bars, 0.001, [1.0], [2.0], spread_points_override=30.0, sample_step=5, max_horizon=64
    )

    assert spread_median == 30.0


def test_main_geometry_runs_end_to_end(tmp_path, monkeypatch, capsys):
    candles = _synthetic_candles(600)
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
        [
            "backtest_audit.py",
            "--candles-file", str(candles_file),
            "--bars-count", "100",
            "--geometry",
            "--sl-atr-mults", "1", "2",
            "--rr-ratios", "2",
            "--sample-step", "5",
        ],
    )

    audit.main()

    out = capsys.readouterr().out
    assert "出口ジオメトリ検証" in out
    assert "必要Δp" in out
    assert "現行設定" in out


def test_main_by_period_runs_end_to_end(tmp_path, monkeypatch, capsys):
    candles = _synthetic_candles(400)
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
        [
            "backtest_audit.py",
            "--candles-file", str(candles_file),
            "--bars-count", "100",
            "--by-period",
            "--discovery-days", "1",
        ],
    )

    audit.main()

    out = capsys.readouterr().out
    assert "期間別の概況" in out
    assert "単調性の方向" in out
    assert "ADX<25%" in out


# --- 時間帯別(--by-hour)モード ------------------------------------------------


def test_hour_of_day_analysis_splits_halves_and_covers_hours():
    candles = _synthetic_candles(2000)
    bars = audit.compute_period_bars(candles, bars_count=100, point_size=0.001)

    rows = audit.hour_of_day_analysis(
        candles, bars, 0.001, sl_atr_mult=2.0, rr=1.5, sample_step=2, max_horizon=128
    )

    assert rows
    for row in rows:
        # 前半・後半の両方に取引がある時間帯だけが返る(再現性を見るため)
        assert row.trades_first > 0
        assert row.trades_second > 0
        assert 0 <= row.hour <= 23


def _fade_stalls_candles(n: int) -> pd.DataFrame:
    """追従は必ず決着し、逆張りはほぼ決着しない相場を人工的に作る。

    終値は常に100.00。安値99.88は BUY追従のSL(99.90)を毎バー割るので、
    追従は必ず「負け」で決着する。一方 SELL逆張りが決着するには
    99.85以下(TP)か100.10以上(SL)が必要で、10本に1本だけ現れる
    安値99.80のバーまで届かない限り決着しない。
    """
    rows = []
    t = 1700000000
    for i in range(n):
        low = 99.80 if i % 10 == 0 else 99.88
        rows.append({"time": t, "open": 100.0, "high": 100.02, "low": low, "close": 100.0, "spread": 0})
        t += 900
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def test_hour_of_day_counts_follow_independently_of_fade():
    """追従と逆張りは別々の分母で数える(生存バイアスの回帰テスト)。

    旧実装は逆張りが期限内に決着しないとそのバーを丸ごと捨てていた。追従が
    勝つときは価格がTPまで進む過程で必ず逆張りのSLを通過するため逆張りも
    決着するが、追従が負けるとき(価格がSLに触れただけ)は逆張りが未決着で
    残りうる。結果として「勝ちは必ず残り、負けの一部だけ消える」形になり、
    勝率とEVが実際より良く出てしまっていた。

    ここでは追従だけが必ず決着する相場を用意する。両者を巻き込んで捨てる
    実装では追従件数と逆張り件数が必ず一致するので、一致しないことが
    独立に数えている証拠になる。
    """
    candles = _fade_stalls_candles(400)
    bars = [
        AuditBar(
            index=i,
            time=candles.iloc[i]["time"],
            close=100.0,
            h1_direction="BUY",
            adx=None,
            regime=None,
            rsi=None,
            ema_dist_atr=None,
            atr_points=100.0,
            macd_hist=None,
        )
        for i in range(len(candles) - 5)
    ]

    rows = audit.hour_of_day_analysis(
        candles, bars, 0.001, sl_atr_mult=1.0, rr=1.5, sample_step=1, max_horizon=2
    )

    assert rows
    follow_total = sum(r.trades_first + r.trades_second for r in rows)
    fade_total = sum(r.fade_trades_first + r.fade_trades_second for r in rows)
    assert follow_total > 0
    # 追従は毎バー決着し、逆張りは安値99.80が2本以内に来たときだけ決着する
    assert follow_total > fade_total
    # 追従は全て負けなので、EVはコスト無しでも -1R でなければならない
    for r in rows:
        assert r.ev_follow_first == pytest.approx(-1.0)
        assert r.ev_follow_second == pytest.approx(-1.0)


def test_hour_of_day_analysis_empty_without_usable_bars():
    candles = _synthetic_candles(300)
    assert audit.hour_of_day_analysis(candles, [], 0.001, 2.0, 1.5) == []


def test_main_by_hour_runs_end_to_end(tmp_path, monkeypatch, capsys):
    candles = _synthetic_candles(2000)
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
        [
            "backtest_audit.py",
            "--candles-file", str(candles_file),
            "--bars-count", "100",
            "--by-hour",
            "--hour-sl-mult", "2",
            "--sample-step", "4",
        ],
    )

    audit.main()

    out = capsys.readouterr().out
    assert "時間帯別の期待値" in out
    assert "UTC時" in out
