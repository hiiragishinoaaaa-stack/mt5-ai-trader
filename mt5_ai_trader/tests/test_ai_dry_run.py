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
    assert all(len(w) == 100 for _, w in windows)
    # 古い順に並ぶ(表示が時系列になるように)
    times = [w.iloc[-1]["time"] for _, w in windows]
    assert times == sorted(times)
    # 絶対indexは、そのウィンドウ最終足の元データ上の位置
    for end_index, w in windows:
        assert candles.iloc[end_index]["time"] == w.iloc[-1]["time"]


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


# --- 判断後の採点 --------------------------------------------------------------


def test_evaluate_action_skips_wait_without_counting_it_as_a_loss():
    """見送りは損益0の「取引なし」。外れとして数えない。"""
    verdict = ai_dry_run.evaluate_action(
        "WAIT", lambda *a: 0, 0, 100.0, 100.0, 0.001, 20.0, 6.0, 1.5
    )

    assert verdict.outcome == -2
    assert verdict.ev_r == 0.0
    assert "見送り" in verdict.mark


def test_evaluate_action_scores_a_win_net_of_spread():
    verdict = ai_dry_run.evaluate_action(
        "BUY", lambda *a: 1, 0, 100.0, 100.0, 0.001, 60.0, 6.0, 1.5
    )

    assert verdict.outcome == 1
    # RR1.5から、スプレッド60pt / SL幅600pt = 0.1R を引く
    assert verdict.ev_r == pytest.approx(1.4)


def test_evaluate_action_scores_a_loss_net_of_spread():
    verdict = ai_dry_run.evaluate_action(
        "SELL", lambda *a: 0, 0, 100.0, 100.0, 0.001, 60.0, 6.0, 1.5
    )

    assert verdict.ev_r == pytest.approx(-1.1)


def test_evaluate_action_marks_unresolved_trades():
    verdict = ai_dry_run.evaluate_action(
        "BUY", lambda *a: -1, 0, 100.0, 100.0, 0.001, 0.0, 6.0, 1.5
    )

    assert verdict.outcome == -1
    assert verdict.ev_r == 0.0


def test_summarise_excludes_skips_from_the_denominator():
    verdicts = [
        ai_dry_run.Verdict("BUY", 1, 1.4),
        ai_dry_run.Verdict("BUY", 0, -1.1),
        ai_dry_run.Verdict("WAIT", -2, 0.0),
    ]

    line = ai_dry_run.summarise("gemini", verdicts)

    assert " 2" in line  # 取引数は2件(見送りは除く)
    assert "+0.150" in line  # (1.4 - 1.1) / 2


def test_summarise_handles_all_skipped():
    line = ai_dry_run.summarise("gemini", [ai_dry_run.Verdict("WAIT", -2, 0.0)])

    assert "-" in line


def test_main_prints_scoring_table(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 600)
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _StubEngine("BUY"))
    monkeypatch.setattr(
        "sys.argv",
        ["ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100", "--count", "2", "--step", "50"],
    )

    ai_dry_run.main()

    out = capsys.readouterr().out
    assert "採点" in out
    assert "EV(R)" in out
    assert "一致率は成績ではない" in out


def test_main_no_evaluate_skips_scoring(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 400)
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _StubEngine("BUY"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100",
            "--count", "1", "--no-evaluate",
        ],
    )

    ai_dry_run.main()

    assert "採点" not in capsys.readouterr().out


# --- API失敗を「見送り」と混同しない --------------------------------------------


class _FailingEngine(AIEngine):
    """本番のLLMエンジンと同じく、失敗時はerror付きWAITへフォールバックする。"""

    def __init__(self, http_status: int | None = None, fail_times: int = 99) -> None:
        self.http_status = http_status
        self.fail_times = fail_times
        self.calls = 0

    def decide(self, df: pd.DataFrame) -> Signal:
        from ai_engine import error_signal

        self.calls += 1
        if self.calls <= self.fail_times:
            return error_signal("API呼び出しに失敗しました", self.http_status)
        return Signal("BUY", "復帰後の判断", {}, confidence=50.0)


def test_evaluate_action_separates_failure_from_a_deliberate_skip():
    """APIエラーのWAITは、見送りとしても外れとしても数えない。"""
    failed = ai_dry_run.evaluate_action(
        "WAIT", lambda *a: 0, 0, 100.0, 100.0, 0.001, 20.0, 6.0, 1.5, failed=True
    )
    skipped = ai_dry_run.evaluate_action(
        "WAIT", lambda *a: 0, 0, 100.0, 100.0, 0.001, 20.0, 6.0, 1.5, failed=False
    )

    assert failed.outcome == -3
    assert "判断できず" in failed.mark
    assert skipped.outcome == -2
    assert "見送り" in skipped.mark


def test_summarise_counts_failures_in_their_own_column():
    verdicts = [
        ai_dry_run.Verdict("BUY", 1, 1.4),
        ai_dry_run.Verdict("WAIT", -2, 0.0),
        ai_dry_run.Verdict("WAIT", -3, 0.0),
        ai_dry_run.Verdict("WAIT", -3, 0.0),
    ]

    line = ai_dry_run.summarise("gemini", verdicts)

    # 取引1 / 的中1 / 見送り1 / 判断不能2
    assert line.split()[1:3] == ["1", "1"]
    assert line.endswith("         1         2")


def test_call_engine_retries_on_rate_limit_then_succeeds(capsys):
    engine = _FailingEngine(http_status=429, fail_times=1)

    signal = ai_dry_run.call_engine(engine, pd.DataFrame(), retries=2, backoff_seconds=0.0)

    assert engine.calls == 2
    assert signal.action == "BUY"
    assert "レート制限" in capsys.readouterr().out


def test_call_engine_gives_up_after_the_retry_budget():
    engine = _FailingEngine(http_status=429)

    signal = ai_dry_run.call_engine(engine, pd.DataFrame(), retries=1, backoff_seconds=0.0)

    assert engine.calls == 2  # 初回 + 再試行1回
    assert signal.details["error"]


def test_call_engine_does_not_retry_other_errors():
    engine = _FailingEngine(http_status=404)

    ai_dry_run.call_engine(engine, pd.DataFrame(), retries=3, backoff_seconds=0.0)

    assert engine.calls == 1  # 404は待っても直らないので即あきらめる


def test_main_excludes_failed_calls_from_agreement(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 600)
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _FailingEngine(http_status=500))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100",
            "--count", "2", "--step", "50", "--sleep", "0",
        ],
    )

    ai_dry_run.main()

    out = capsys.readouterr().out
    assert "集計から除外" in out
    assert "判断の一致率" not in out  # 比較できた回が無いので一致率も出さない


def test_call_engine_obeys_the_server_suggested_wait(monkeypatch, capsys):
    """レート制限の応答が待ち時間を指定してきたら、それに従う。"""
    from ai_engine import error_signal

    slept: list[float] = []
    monkeypatch.setattr(ai_dry_run.time, "sleep", slept.append)

    class _Engine(AIEngine):
        def __init__(self):
            self.calls = 0

        def decide(self, df):
            self.calls += 1
            if self.calls == 1:
                return error_signal("制限", 429, retry_after_seconds=12.5)
            return Signal("BUY", "復帰", {}, confidence=50.0)

    ai_dry_run.call_engine(_Engine(), pd.DataFrame(), retries=1, backoff_seconds=30.0)

    # 指定12.5秒 + 余裕1秒。既定の30秒は使わない
    assert slept == [pytest.approx(13.5)]
    assert "14秒待って" in capsys.readouterr().out


def test_call_engine_falls_back_to_default_wait_without_a_suggestion(monkeypatch):
    from ai_engine import error_signal

    slept: list[float] = []
    monkeypatch.setattr(ai_dry_run.time, "sleep", slept.append)

    class _Engine(AIEngine):
        def decide(self, df):
            return error_signal("制限", 429)

    ai_dry_run.call_engine(_Engine(), pd.DataFrame(), retries=1, backoff_seconds=25.0)

    assert slept == [25.0]


def test_main_model_override_applies_for_the_run(tmp_path, monkeypatch, capsys):
    """--model は .env を書き換えずにモデルを差し替える(機種比較用)。"""
    import config

    path = _write_history(tmp_path, 400)
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _StubEngine("BUY"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100",
            "--count", "1", "--engine", "gemini", "--model", "gemini-3.1-pro-preview",
        ],
    )

    ai_dry_run.main()

    assert config.GEMINI_MODEL == "gemini-3.1-pro-preview"
    assert "モデルを gemini-3.1-pro-preview に差し替えて" in capsys.readouterr().out


def test_main_model_override_warns_for_unknown_engine(tmp_path, monkeypatch, capsys):
    path = _write_history(tmp_path, 400)
    monkeypatch.setattr(ai_dry_run, "get_ai_engine", lambda name: _StubEngine("BUY"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai_dry_run.py", "--candles-file", str(path), "--bars-count", "100",
            "--count", "1", "--engine", "rule_based", "--model", "なにか",
        ],
    )

    ai_dry_run.main()

    assert "モデル差し替えの設定がありません" in capsys.readouterr().out


# --- 正解付き出題(--curated) ---------------------------------------------------


def _trending_candles(n: int, drift: float) -> pd.DataFrame:
    """一方向に素直に伸びる系列(BUYまたはSELLが必ず正解になる)。"""
    rows = []
    price = 150.0
    t = 1700000000
    for _ in range(n):
        price += drift
        rows.append(
            {"time": t, "open": price, "high": price + 0.01, "low": price - 0.01,
             "close": price, "spread": 2}
        )
        t += 900
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def test_build_curated_set_labels_a_rising_market_as_buy():
    """上げ続ける相場では、買いがTP先着になるのでBUYが正解になる。"""
    candles = _trending_candles(600, drift=0.02)

    cases = ai_dry_run.build_curated_set(
        candles, 0.001, bars_count=100, sl_atr_mult=1.0, rr=1.5, per_class=5
    )

    assert cases
    labels = {label for _, label in cases}
    assert labels == {"BUY"}  # 下落局面もレンジも無いのでBUYだけ


def test_build_curated_set_labels_a_falling_market_as_sell():
    candles = _trending_candles(600, drift=-0.02)

    cases = ai_dry_run.build_curated_set(
        candles, 0.001, bars_count=100, sl_atr_mult=1.0, rr=1.5, per_class=5
    )

    assert {label for _, label in cases} == {"SELL"}


def test_build_curated_set_caps_each_class_at_per_class():
    candles = _trending_candles(1200, drift=0.02)

    cases = ai_dry_run.build_curated_set(
        candles, 0.001, bars_count=100, sl_atr_mult=1.0, rr=1.5, per_class=4
    )

    assert len(cases) <= 4  # 1クラスしか無い相場なので上限どおり


def test_build_curated_set_returns_indexes_in_time_order():
    candles = _trending_candles(800, drift=0.02)

    cases = ai_dry_run.build_curated_set(
        candles, 0.001, bars_count=100, sl_atr_mult=1.0, rr=1.5, per_class=6
    )

    assert [i for i, _ in cases] == sorted(i for i, _ in cases)


def test_run_curated_reports_per_class_accuracy(capsys):
    candles = _trending_candles(600, drift=0.02)
    cases = [(200, "BUY"), (300, "SELL"), (400, "WAIT")]

    ai_dry_run.run_curated(
        candles, cases, _StubEngine("BUY"), "stub", bars_count=100, retries=0, sleep_seconds=0
    )

    out = capsys.readouterr().out
    assert "正答率" in out
    assert "取り違えの内訳" in out
    assert "実戦成績ではない" in out  # 誤読を防ぐ注意書きは必ず出す


def test_run_curated_excludes_api_failures_from_accuracy(capsys):
    candles = _trending_candles(600, drift=0.02)
    cases = [(200, "BUY"), (300, "BUY")]

    ai_dry_run.run_curated(
        candles, cases, _FailingEngine(http_status=500), "stub",
        bars_count=100, retries=0, sleep_seconds=0,
    )

    out = capsys.readouterr().out
    assert "判断が1件も取れませんでした" in out
