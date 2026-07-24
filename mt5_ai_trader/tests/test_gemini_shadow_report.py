"""gemini_shadow_report.py の単体テスト。MT5/EA不要、合成データのみで実行できる。"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import gemini_shadow_report as report


# --- load_shadow_log ------------------------------------------------------------


def test_load_shadow_log_parses_json_lines(tmp_path):
    path = tmp_path / "shadow.jsonl"
    path.write_text(
        '{"rule_action": "WAIT", "gemini_action": "BUY", "agree": false}\n'
        '{"rule_action": "BUY", "gemini_action": "BUY", "agree": true}\n',
        encoding="utf-8",
    )

    rows = report.load_shadow_log(path)

    assert len(rows) == 2
    assert rows[0]["rule_action"] == "WAIT"
    assert rows[1]["agree"] is True


def test_load_shadow_log_skips_blank_and_malformed_lines(tmp_path):
    path = tmp_path / "shadow.jsonl"
    path.write_text('{"rule_action": "WAIT"}\n\n{not valid json\n', encoding="utf-8")

    rows = report.load_shadow_log(path)

    assert len(rows) == 1


# --- agreement_stats --------------------------------------------------------------


def test_agreement_stats_empty_rows():
    stats = report.agreement_stats([])
    assert stats == {"total": 0, "agree_count": 0, "agree_rate": 0.0, "by_rule_action": {}}


def test_agreement_stats_computes_overall_and_per_action_rates():
    rows = [
        {"rule_action": "BUY", "gemini_action": "BUY", "agree": True},
        {"rule_action": "BUY", "gemini_action": "SELL", "agree": False},
        {"rule_action": "WAIT", "gemini_action": "WAIT", "agree": True},
        {"rule_action": "SELL", "gemini_action": "SELL", "agree": True},
    ]

    stats = report.agreement_stats(rows)

    assert stats["total"] == 4
    assert stats["agree_count"] == 3
    assert stats["agree_rate"] == pytest.approx(75.0)
    assert stats["by_rule_action"]["BUY"] == {"count": 2, "agree_count": 1, "agree_rate": pytest.approx(50.0)}
    assert stats["by_rule_action"]["SELL"] == {"count": 1, "agree_count": 1, "agree_rate": pytest.approx(100.0)}
    assert stats["by_rule_action"]["WAIT"] == {"count": 1, "agree_count": 1, "agree_rate": pytest.approx(100.0)}


# --- _find_bar_index --------------------------------------------------------------


def _candles(times: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(times, unit="s"),
            "open": [100.0] * len(times),
            "high": [100.5] * len(times),
            "low": [99.5] * len(times),
            "close": [100.2] * len(times),
        }
    )


def test_find_bar_index_returns_latest_bar_at_or_before_timestamp():
    candles = _candles([1000, 1900, 2800, 3700])  # 900秒間隔
    assert report._find_bar_index(candles, 2850) == 2  # 2800のバー(3700より前)
    assert report._find_bar_index(candles, 2800) == 2  # ちょうど一致


def test_find_bar_index_returns_none_when_timestamp_before_all_candles():
    candles = _candles([1000, 1900])
    assert report._find_bar_index(candles, 500) is None


# --- simulate_shadow_outcomes -----------------------------------------------------


def test_simulate_shadow_outcomes_computes_hypothetical_trades():
    # 900秒間隔のローソク足。最初のバー(t=1000)の後、価格が上昇してTPに到達する。
    candles = pd.DataFrame(
        {
            "time": pd.to_datetime([1000, 1900, 2800], unit="s"),
            "open": [100.0, 100.5, 101.0],
            "high": [100.1, 100.6, 104.1],  # 3本目でBUYのTP(+400pt, point_size=0.01)に到達
            "low": [99.9, 100.4, 100.9],
            "close": [100.0, 100.5, 101.0],
        }
    )
    rows = [
        {
            "timestamp": 1000,
            "price": 100.0,
            "rule_action": "WAIT",
            "gemini_action": "BUY",
            "agree": False,
        }
    ]

    gemini_result, rule_result = report.simulate_shadow_outcomes(
        rows, candles, sl_points=200, tp_points=400, point_size=0.01
    )

    assert len(gemini_result.trades) == 1
    assert gemini_result.trades[0].reason == "take_profit"
    assert gemini_result.trades[0].pnl_points == pytest.approx(400.0)
    assert rule_result.trades == []  # ルールはWAITだったので仮想トレードは発生しない


def test_simulate_shadow_outcomes_skips_rows_before_candle_history():
    candles = _candles([10_000, 10_900])
    rows = [{"timestamp": 100, "price": 100.0, "rule_action": "BUY", "gemini_action": "BUY", "agree": True}]

    gemini_result, rule_result = report.simulate_shadow_outcomes(
        rows, candles, sl_points=200, tp_points=400, point_size=0.01
    )

    assert gemini_result.trades == []
    assert rule_result.trades == []


def test_simulate_shadow_outcomes_skips_rows_missing_price():
    candles = _candles([1000, 1900, 2800])
    rows = [{"timestamp": 1000, "price": None, "rule_action": "BUY", "gemini_action": "BUY", "agree": True}]

    gemini_result, rule_result = report.simulate_shadow_outcomes(
        rows, candles, sl_points=200, tp_points=400, point_size=0.01
    )

    assert gemini_result.trades == []
    assert rule_result.trades == []


# --- CLI end-to-end smoke test -----------------------------------------------------


def test_main_runs_end_to_end_with_candles_file(tmp_path, monkeypatch, capsys):
    shadow_log = tmp_path / "shadow.jsonl"
    shadow_log.write_text(
        json.dumps(
            {"timestamp": 1000, "price": 100.0, "rule_action": "WAIT", "gemini_action": "BUY", "agree": False}
        )
        + "\n",
        encoding="utf-8",
    )

    candles_payload = {
        "symbol": "USDJPY",
        "timeframe": "M15",
        "exported_at": 2800,
        "candles": [
            {"time": 1000, "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "spread": 2},
            {"time": 1900, "open": 100.5, "high": 100.6, "low": 100.4, "close": 100.5, "spread": 2},
            {"time": 2800, "open": 101.0, "high": 104.1, "low": 100.9, "close": 101.0, "spread": 2},
        ],
    }
    candles_file = tmp_path / "history.json"
    candles_file.write_text(json.dumps(candles_payload), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "gemini_shadow_report.py",
            "--shadow-log", str(shadow_log),
            "--candles-file", str(candles_file),
            "--sl-points", "200",
            "--tp-points", "400",
            "--point-size", "0.01",
        ],
    )

    report.main()

    out = capsys.readouterr().out
    assert "一致率" in out
    assert "仮想損益" in out
    assert "Gemini追従" in out


def test_main_without_candles_file_only_prints_agreement(tmp_path, monkeypatch, capsys):
    shadow_log = tmp_path / "shadow.jsonl"
    shadow_log.write_text(
        json.dumps({"rule_action": "BUY", "gemini_action": "BUY", "agree": True}) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr("sys.argv", ["gemini_shadow_report.py", "--shadow-log", str(shadow_log)])

    report.main()

    out = capsys.readouterr().out
    assert "一致率" in out
    assert "Gemini追従" not in out  # 仮想損益の比較表そのものは出力されない
    assert "--candles-fileを指定すると仮想損益も計算できます" in out


def test_main_reports_when_log_is_empty(tmp_path, monkeypatch, capsys):
    shadow_log = tmp_path / "shadow.jsonl"
    shadow_log.write_text("", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["gemini_shadow_report.py", "--shadow-log", str(shadow_log)])

    report.main()

    out = capsys.readouterr().out
    assert "ログがありませんでした" in out
