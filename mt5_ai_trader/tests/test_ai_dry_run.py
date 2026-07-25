"""ai_dry_run.py の単体テスト。ネットワーク・MT5・EA不要。

AIエンジンはダミーに差し替えるため、実際のAPI呼び出しは一切発生しない。
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import ai_dry_run
from ai_engine import AIEngine, Signal


class _StubEngine(AIEngine):
    """常に同じ判断を返すダミー。呼ばれた回数を記録する。"""

    def __init__(self, action: str = "BUY") -> None:
        self.action = action
        self.calls = 0

    def decide(self, df: pd.DataFrame) -> Signal:
        self.calls += 1
        return Signal(self.action, "スタブの判断", {}, confidence=42.0)


def _candles(n: int) -> pd.DataFrame:
    rows = []
    price = 150.0
    t = 1700000000
    for i in range(n):
        price += 0.02 if i % 3 == 0 else -0.01
        o = price
        c = price + 0.005
        rows.append(
            {"time": t, "open": o, "high": max(o, c) + 0.02, "low": min(o, c) - 0.02, "close": c, "spread": 2}
        )
        t += 900
        price = c
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


# --- iter_windows -------------------------------------------------------------


def test_iter_windows_returns_requested_count_in_chronological_order():
    candles = _candles(500)

    windows = ai_dry_run.iter_windows(candles, bars_count=100, count=3, step=50)

    assert len(windows) == 3
    assert all(len(w) == 100 for w in windows)
    # 古い順に並ぶ(表示が時系列になるように)
    times = [w.iloc[-1]["time"] for w in windows]
    assert times == sorted(times)


def test_iter_windows_stops_when_history_runs_out():
    candles = _candles(150)

    windows = ai_dry_run.iter_windows(candles, bars_count=100, count=5, step=40)

    # 100本必要なので、150本からは2つしか取れない(末尾と40本前)
    assert len(windows) == 2


def test_iter_windows_empty_when_shorter_than_window():
    candles = _candles(50)

    assert ai_dry_run.iter_windows(candles, bars_count=100, count=3, step=10) == []


# --- format_signal / score_line -----------------------------------------------


def test_format_signal_shows_action_confidence_and_reason():
    text = ai_dry_run.format_signal(Signal("SELL", "下降トレンド", {}, confidence=61.5))

    assert "SELL" in text
    assert "61.5" in text
    assert "下降トレンド" in text


def test_score_line_none_without_breakdown():
    assert ai_dry_run.score_line(Signal("WAIT", "理由", {})) is None


def test_score_line_renders_both_directions():
    signal = Signal(
        "WAIT",
        "理由",
        {"buy_score": 4, "buy_total": 11, "sell_score": 2, "sell_total": 11, "required_score": 7},
    )

    line = ai_dry_run.score_line(signal)

    assert "BUY 4/11" in line
    assert "SELL 2/11" in line
    assert "必要 7" in line


# --- CLI ----------------------------------------------------------------------


def _write_history(tmp_path, n: int):
    candles = _candles(n)
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
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_main_prints_both_judgements_and_agreement(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 400)
    stub = _StubEngine("BUY")
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: stub)
    monkeypatch.setattr(
        "sys.argv",
        ["ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100", "--count", "2", "--step", "50"],
    )

    ai_dry_run.main()

    out = capsys.readouterr().out
    assert stub.calls == 2  # 件数ぶんだけAIを呼ぶ(=API呼び出し回数)
    assert "ルール" in out
    assert "スタブの判断" in out
    assert "一致率: " in out


def test_main_show_prompt_includes_llm_text(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 300)
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _StubEngine("WAIT"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100",
            "--count", "1", "--show-prompt",
        ],
    )

    ai_dry_run.main()

    out = capsys.readouterr().out
    assert "AIへ渡している文面" in out
    assert "USDJPY" in out


def test_main_reports_when_history_too_short(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 40)
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _StubEngine())
    monkeypatch.setattr(
        "sys.argv",
        ["ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100", "--count", "1"],
    )

    ai_dry_run.main()

    assert "ウィンドウを切り出せませんでした" in capsys.readouterr().out


# --- --list-models(404の切り分け) ---------------------------------------------


def _fake_urlopen(per_version: dict):
    """バージョンごとに応答/例外を切り替えるurlopenの差し替え。"""
    import urllib.error

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _open(req, *a, **k):
        version = req.full_url.split("/")[3]
        outcome = per_version.get(version)
        if outcome is None:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(req.full_url, outcome, "Denied", {}, None)
        return _Resp(json.dumps({"models": outcome}).encode("utf-8"))

    return _open


def _model(name: str, method: str = "generateContent"):
    return {"name": f"models/{name}", "supportedGenerationMethods": [method]}


def test_list_models_reports_missing_key(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "")

    ai_dry_run.list_gemini_models()

    assert "GEMINI_API_KEY が未設定" in capsys.readouterr().out


def test_list_models_confirms_a_valid_configuration(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("config.GEMINI_API_VERSION", "v1beta")
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        ai_dry_run.urllib.request, "urlopen", _fake_urlopen({"v1beta": [_model("gemini-2.5-flash")]})
    )

    ai_dry_run.list_gemini_models()

    out = capsys.readouterr().out
    assert "現在の設定" in out and "有効です" in out
    assert "dummy-key" not in out


def test_list_models_points_at_the_other_api_version(monkeypatch, capsys):
    """同じモデルが別バージョンにある場合、その乗り換え先を名指しする。"""
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("config.GEMINI_API_VERSION", "v1beta")
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        ai_dry_run.urllib.request,
        "urlopen",
        _fake_urlopen({"v1beta": [_model("gemini-1.0-pro")], "v1": [_model("gemini-2.5-flash")]}),
    )

    ai_dry_run.list_gemini_models()

    out = capsys.readouterr().out
    assert "404の原因です" in out
    assert "GEMINI_API_VERSION=v1" in out


def test_list_models_suggests_a_flash_model_when_nothing_matches(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("config.GEMINI_API_VERSION", "v1beta")
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-9-imaginary")
    monkeypatch.setattr(
        ai_dry_run.urllib.request,
        "urlopen",
        _fake_urlopen({"v1beta": [_model("gemini-2.0-flash"), _model("text-embed", "embedContent")]}),
    )

    ai_dry_run.list_gemini_models()

    out = capsys.readouterr().out
    assert "GEMINI_MODEL=gemini-2.0-flash" in out
    assert "text-embed" not in out  # generateContent非対応は候補にしない


def test_list_models_explains_auth_error_across_versions(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr(ai_dry_run.urllib.request, "urlopen", _fake_urlopen({"v1beta": 403, "v1": 403}))

    ai_dry_run.list_gemini_models()

    out = capsys.readouterr().out
    assert "HTTP 403" in out
    assert "認証エラー" in out
    assert "dummy-key" not in out


# --- --probe(実際に生成が通る組み合わせを探す) ---------------------------------


def _fake_generate(outcomes: dict):
    """(version, model) ごとに成功/HTTPエラーを切り替えるurlopenの差し替え。

    モデル一覧(GET)と生成(POST)の両方が同じurlopenを通るため、
    リクエストの種別で応答を出し分ける。
    """
    import urllib.error

    class _Resp:
        def __init__(self, body=b"{}"):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _open(req, *a, **k):
        parts = req.full_url.split("/")
        version = parts[3]
        if req.data is None:  # モデル一覧
            models = outcomes.get(("list", version))
            if models is None:
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return _Resp(json.dumps({"models": [_model(m) for m in models]}).encode("utf-8"))
        model = parts[-1].removesuffix(":generateContent")
        if outcomes.get((version, model)):
            return _Resp()
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    return _open


def test_probe_confirms_working_configuration(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("config.GEMINI_API_VERSION", "v1beta")
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        ai_dry_run.urllib.request, "urlopen", _fake_generate({("v1beta", "gemini-2.5-flash"): True})
    )

    ai_dry_run.probe_generate_content()

    out = capsys.readouterr().out
    assert "成功" in out
    assert ".env の変更は不要" in out


def test_probe_finds_a_working_model_when_configured_one_404s(monkeypatch, capsys):
    """一覧に載っていても生成が404になる場合に、実際に通るモデルを提示する。"""
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("config.GEMINI_API_VERSION", "v1beta")
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        ai_dry_run.urllib.request,
        "urlopen",
        _fake_generate(
            {
                ("list", "v1beta"): ["gemini-2.5-flash", "gemini-3.6-flash"],
                ("list", "v1"): ["gemini-2.5-flash"],
                ("v1beta", "gemini-3.6-flash"): True,  # これだけ生成できる
            }
        ),
    )

    ai_dry_run.probe_generate_content()

    out = capsys.readouterr().out
    assert "GEMINI_MODEL=gemini-3.6-flash" in out
    assert "GEMINI_API_VERSION=v1beta" in out
    assert "dummy-key" not in out


def test_probe_reports_when_every_candidate_fails(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("config.GEMINI_API_VERSION", "v1beta")
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        ai_dry_run.urllib.request,
        "urlopen",
        _fake_generate({("list", "v1beta"): ["gemini-2.5-flash", "gemini-3.6-flash"]}),
    )

    ai_dry_run.probe_generate_content()

    assert "候補がすべて失敗しました" in capsys.readouterr().out


def test_probe_reports_missing_key(monkeypatch, capsys):
    monkeypatch.setattr("config.GEMINI_API_KEY", "")

    ai_dry_run.probe_generate_content()

    assert "GEMINI_API_KEY が未設定" in capsys.readouterr().out
