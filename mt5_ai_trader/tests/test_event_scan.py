"""event_scan.py の単体テスト。ネットワーク不要で実行できる。

このツールが答えようとしているのは「決まった時刻の急変に乗れるか」だが、
**間違って『乗れる』と答えてしまう経路**が複数ある。テストの主眼はそこに置く:

- 片方の期間だけ集中しているマスを採用してしまわないか(多重比較)
- 追従と逆張りを同じ分母で数えて、負けだけを捨てていないか
- 先読み(そのバー自身の値幅で急変を判定する)をしていないか
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from event_scan import (
    Cell,
    beats,
    build_cells,
    measure_entries,
    replicated_cells,
    spike_flags,
    true_range,
)


def _candles(rows: list[tuple[str, float, float, float, float]], spread: float = 20.0) -> pd.DataFrame:
    """(時刻文字列, open, high, low, close) からDataFrameを作る。"""
    return pd.DataFrame(
        [
            {
                "time": pd.Timestamp(t),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "spread": spread,
            }
            for t, o, h, l, c in rows
        ]
    )


def _flat_series(n: int, start: str = "2024-01-01 00:00", step_min: int = 15) -> pd.DataFrame:
    """値幅が一定の静かな系列。ここへ意図的に急変を差し込んで使う。"""
    base = pd.Timestamp(start)
    rows = []
    price = 150.0
    for i in range(n):
        rows.append(
            (str(base + pd.Timedelta(minutes=step_min * i)), price, price + 0.10, price - 0.10, price)
        )
    return _candles(rows)


def test_true_range_includes_the_gap_from_the_previous_close():
    """窓を開けて飛んだ分を無視すると、急変を見逃す。"""
    df = _candles(
        [
            ("2024-01-01 00:00", 150.0, 150.1, 149.9, 150.0),
            ("2024-01-01 00:15", 152.0, 152.1, 151.9, 152.0),  # 前終値から+2.0跳んだ
        ]
    )
    tr = true_range(df)
    assert tr[1] == pytest.approx(2.1)  # 高値150.0→152.1 の幅であって、バー内の0.2ではない


def test_spike_flags_does_not_look_at_the_bar_itself():
    """基準に自分自身を含めると、どんなバーも『平常』に見えてしまう(先読み)。"""
    df = _flat_series(60)
    df.loc[59, ["high", "low"]] = [151.0, 149.0]  # 最後だけ値幅2.0(通常の10倍)

    flags = spike_flags(df, window=20, multiple=3.0)
    assert flags[59]
    assert not flags[:59].any()


def test_spike_flags_adapts_to_a_changing_volatility_level():
    """固定の閾値だと、ボラティリティが高い時期に偏る。

    後半だけ全体のボラが5倍になった系列。後半のバーは絶対値では大きいが、
    その時期の基準に対しては平常なので急変ではない。
    """
    rows = []
    base = pd.Timestamp("2024-01-01")
    for i in range(120):
        width = 0.10 if i < 60 else 0.50
        t = base + pd.Timedelta(minutes=15 * i)
        rows.append((str(t), 150.0, 150.0 + width, 150.0 - width, 150.0))
    df = _candles(rows)

    flags = spike_flags(df, window=20, multiple=3.0)
    assert not flags[80:].any()  # 基準が追いついた後は急変扱いしない


def test_build_cells_splits_counts_into_halves():
    df = _flat_series(8)
    spikes = np.array([True, False, False, False, True, True, False, False])
    cells = build_cells(df, spikes)

    total_bars = sum(c.bars for c in cells)
    total_spikes = sum(c.spikes for c in cells)
    assert total_bars == 8
    assert total_spikes == 3
    assert sum(c.spikes_first for c in cells) == 1  # 前半4本のうち1本
    assert sum(c.spikes_second for c in cells) == 2


def _cell(spikes_first: int, bars_first: int, spikes_second: int, bars_second: int) -> Cell:
    return Cell(
        weekday=0, hour=13, minute=30,
        bars=bars_first + bars_second, spikes=spikes_first + spikes_second,
        spikes_first=spikes_first, bars_first=bars_first,
        spikes_second=spikes_second, bars_second=bars_second,
    )


def test_replicated_cells_accepts_a_cell_that_is_hot_in_both_halves():
    cell = _cell(spikes_first=10, bars_first=50, spikes_second=9, bars_second=50)  # 20% / 18%
    kept = replicated_cells([cell], baseline_rate=5.0, factor=2.0, min_spikes=5)
    assert kept == [cell]


def test_replicated_cells_rejects_a_cell_carried_by_one_half():
    """これがこのツールの存在理由。

    合計では基準の4倍に見えるが、集中しているのは前半だけ。480マスも
    総当たりすれば、この形は必ず出る。
    """
    cell = _cell(spikes_first=20, bars_first=50, spikes_second=0, bars_second=50)
    assert replicated_cells([cell], baseline_rate=5.0, factor=2.0, min_spikes=5) == []


def test_replicated_cells_rejects_a_cell_with_too_few_spikes():
    cell = _cell(spikes_first=2, bars_first=3, spikes_second=2, bars_second=3)
    assert replicated_cells([cell], baseline_rate=5.0, factor=2.0, min_spikes=5) == []


def _trending_after(n: int, event_index: int, direction: int) -> pd.DataFrame:
    """event_index のバーで急変し、その後 direction 方向へ走り続ける系列。"""
    rows = []
    base = pd.Timestamp("2024-01-01")
    price = 150.0
    for i in range(n):
        t = base + pd.Timedelta(minutes=15 * i)
        if i == event_index:
            close = price + direction * 1.0
            rows.append((str(t), price, max(price, close) + 0.05, min(price, close) - 0.05, close))
            price = close
        elif i > event_index:
            close = price + direction * 0.30  # 走り続ける
            rows.append((str(t), price, max(price, close) + 0.05, min(price, close) - 0.05, close))
            price = close
        else:
            rows.append((str(t), price, price + 0.10, price - 0.10, price))
    return _candles(rows)


def test_measure_entries_scores_follow_positive_when_the_move_continues():
    df = _trending_after(120, event_index=40, direction=1)
    follow, fade = measure_entries(
        df, [40], sl_atr_mult=2.0, rr=1.5, point_size=0.001,
        spreads=np.full(len(df), 20.0), extra_spread=0.0,
        ref_window=20, max_horizon=60,
    )
    assert follow.trades == 1 and follow.wins == 1
    assert follow.ev_r > 0
    assert fade.trades == 1 and fade.wins == 0


def test_measure_entries_scores_follow_negative_when_the_move_reverts():
    """急変の後すぐ戻る系列。ストップを両側に置く戦略が死ぬ形。"""
    df = _trending_after(120, event_index=40, direction=1)
    # 急変の直後から逆走させる
    for i in range(41, 120):
        prev = float(df.loc[i - 1, "close"])
        close = prev - 0.30
        df.loc[i, ["open", "high", "low", "close"]] = [prev, max(prev, close) + 0.05, min(prev, close) - 0.05, close]

    follow, fade = measure_entries(
        df, [40], sl_atr_mult=2.0, rr=1.5, point_size=0.001,
        spreads=np.full(len(df), 20.0), extra_spread=0.0,
        ref_window=20, max_horizon=60,
    )
    assert follow.wins == 0
    assert follow.ev_r < 0
    assert fade.wins == 1


def test_follow_and_fade_are_counted_on_independent_denominators():
    """片方が未決着でも、もう片方を巻き添えで捨ててはいけない。

    脱落は必ず**負けの側**で起きる。追従が勝つときは、価格がTP(+1.5×SL幅)
    へ向かう途中で必ず逆張りのSL(+1×SL幅)を通過するので、逆張りも必ず決着
    する。逆に追従が**負ける**ときは、価格は-1×SL幅に触れただけで、逆張りの
    TP(-1.5×SL幅)には届かないことがある=逆張りだけ未決着で残る。

    ここで両者の件数が一致したら、未決着の逆張りに巻き込まれて追従の負けが
    捨てられている。勝ちだけが残り、EVの符号が反転する
    (RESEARCH_FINDINGS.mdの集計バイアスの罠)。
    """
    # 静かな系列(値幅0.20)→ 基準0.20、SL幅=2.0×0.20=0.40、TP=0.60。
    # 急変後に-0.50だけ下げて留まる系列を作る: 追従(買い)はSLに触れて決着、
    # 逆張り(売り)はTP(-0.60)にもSL(+0.40)にも届かず未決着。
    df = _flat_series(120)
    df.loc[40, ["open", "high", "low", "close"]] = [150.0, 151.0, 149.95, 150.9]
    for i in range(41, 120):
        df.loc[i, ["open", "high", "low", "close"]] = [150.42, 150.45, 150.38, 150.40]

    follow, fade = measure_entries(
        df, [40], sl_atr_mult=2.0, rr=1.5, point_size=0.001,
        spreads=np.full(len(df), 20.0), extra_spread=0.0,
        ref_window=20, max_horizon=40,
    )
    assert follow.trades == 1 and follow.wins == 0  # 追従は負けとして決着
    assert fade.trades == 0 and fade.unresolved == 1  # 逆張りは未決着で残る


def test_extra_spread_only_makes_the_expectancy_worse():
    """発表時のスプレッド拡大を入れて改善することはありえない。"""
    df = _trending_after(120, event_index=40, direction=1)
    kwargs = dict(
        indexes=[40], sl_atr_mult=2.0, rr=1.5, point_size=0.001,
        spreads=np.full(len(df), 20.0), ref_window=20, max_horizon=60,
    )
    cheap, _ = measure_entries(df, extra_spread=0.0, **kwargs)
    dear, _ = measure_entries(df, extra_spread=200.0, **kwargs)
    assert dear.ev_r < cheap.ev_r


def test_measure_entries_skips_bars_without_a_reference_window():
    """基準が計算できない先頭部分で落ちないこと。"""
    df = _flat_series(30)
    follow, fade = measure_entries(
        df, [0, 1, 2], sl_atr_mult=2.0, rr=1.5, point_size=0.001,
        spreads=np.full(len(df), 20.0), extra_spread=0.0,
        ref_window=20, max_horizon=10,
    )
    assert follow.trades == 0 and fade.trades == 0


def _outcome(values: list[float]) -> "Outcome":
    from event_scan import Outcome

    o = Outcome()
    for v in values:
        o.add(v, won=v > 0)
    return o


def test_beats_rejects_a_tiny_edge_over_the_control():
    """急変が対照をわずかに上回っただけで『候補』にしてはいけない。

    実測でも、仕込んだイベントに対して対照が+1.348R・急変が+1.398Rという、
    差が誤差に埋もれる結果が出た。この差を採用すると「効いているのは時間帯
    なのに、発表のおかげだ」と読み違える。
    """
    candidate = _outcome([1.5, -1.0] * 40 + [1.5])
    control = _outcome([1.5, -1.0] * 40)
    assert not beats(candidate, control)


def test_beats_accepts_a_clear_edge_over_the_control():
    candidate = _outcome([1.5] * 60 + [-1.0] * 20)
    control = _outcome([1.5] * 20 + [-1.0] * 60)
    assert beats(candidate, control)


def test_beats_is_false_without_any_control_trades():
    assert not beats(_outcome([1.5, -1.0]), _outcome([]))


def test_stderr_shrinks_as_the_sample_grows():
    small = _outcome([1.5, -1.0] * 10)
    large = _outcome([1.5, -1.0] * 1000)
    assert small.stderr_r > large.stderr_r
