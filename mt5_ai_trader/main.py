"""MT5 × AI 自動売買BOT MVP のエントリーポイント。

MT5デモ口座からUSDJPY等の価格データを取得し、テクニカル指標(EMA/RSI/MACD)
を計算した上で、AIエンジンにBUY/SELL/WAITを判断させ、結果をコンソールと
logs/trades.log に出力する。

BUY/SELLと判断された場合、config.DEMO_ONLY が明示的にTrueであれば
order_executor.py が発注リクエストを送出する(既定はOFF)。実際の発注
そのものはEA側(ea/ARTEMIS_Bridge.mq5)が行い、Pythonは一切MT5へ
直接発注しない。

## 発注テスト用モード(FORCE_SIGNAL / TEST_ORDER_ONCE)

通常はAIの判断(EMA/RSI/MACD)がBUY/SELLの条件を満たすまで発注は行われない。
条件が揃うのを待たずにMT5への発注・SL/TP設定・結果JSONの一連の流れだけを
確認したい場合、.envで以下を設定する。

    DEMO_ONLY=true
    FORCE_SIGNAL=BUY   # BUY / SELL / WAIT / 空欄(通常運転)
    TEST_ORDER_ONCE=true

FORCE_SIGNALはDEMO_ONLY=trueの場合のみ有効で、AIの判断結果を上書きする。
TEST_ORDER_ONCEはCLIの--once有無に関わらず1サイクルだけ実行して終了する。
どちらもFORCE_SIGNALを空欄に戻せば既存のAI判断ロジックにそのまま戻る。

価格データの取得・発注のいずれもMT5 Python API(MetaTrader5パッケージ)
ではなく、EAブリッジ方式(ea/ARTEMIS_Bridge.mq5がJSONファイル経由で
やり取りする)で行っている。詳細はmarket_feed.py / order_executor.py の
docstringとREADME.mdを参照。

## Dashboardからの設定変更(config.json)

ORDER_VOLUME・SL_POINTS・TP_POINTS・TIMEFRAME・LOOP_INTERVAL_SECONDS・
RSI_OVERBOUGHT・RSI_OVERSOLD・EMA_FAST_PERIOD・EMA_SLOW_PERIOD・
ENTRY_STRICTNESS・ENABLE_ORDERS・DEMO_ONLY は、.envだけでなく
config.json(settings_server.py経由でDashboardから書き込まれる)でも
上書きできる(settings_schema.py参照)。run_once()の先頭で毎サイクル
config.load_config_json()を呼び、config.jsonの更新日時が変わっていれば
自動的に再読込する。詳細はREADME.mdの「Dashboardからの設定変更」を参照。

## BOT_RUN_STATE(DashboardのSTART/STOP/EMERGENCY STOP)

config.BOT_RUN_STATEがRUNNING以外(STOPPED/EMERGENCY_STOPPED)の場合、
run_once()は価格取得・AI判断・発注を一切行わずWAITのai_statusだけを
書き出して早期リターンする。プロセス自体(このmain.pyのループ、および
systemdサービス)は動き続ける。詳細はREADME.mdの「Dashboardからの
BOT起動/停止(Phase 5)」を参照。

## 日次サマリー通知(Phase 6)

BOT_RUN_STATEの値に関わらず、run_once()の先頭で毎サイクル
daily_summary.maybe_send_daily_summary()を呼び出す(売買を止めていても
その日の結果は知りたいはずのため)。実際に送信するかどうかは
DISCORD_NOTIFY_DAILY_SUMMARY等の設定と1日1回の重複送信防止によって
daily_summary.py内部で判定される。詳細はdaily_summary.pyを参照。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import ai_status
import config
import daily_summary
import indicators
from ai_engine import Signal, get_ai_engine
from logger import setup_logger
from market_feed import FileMarketFeed, MarketFeedError
from order_executor import FileOrderExecutor, generate_request_id
from trade_history_feed import FileTradeHistoryFeed

# setup_logger()はmain()内で(--debugの有無を見た上で)呼び出す。
# ここではハンドラ未設定のロガーを取得するだけ(setup_logger()と同じ名前の
# ロガーを参照するため、後から設定した内容がそのまま反映される)。
logger = logging.getLogger("mt5_ai_trader")

_VALID_FORCE_SIGNALS = ("BUY", "SELL", "WAIT")


def resolve_force_signal(raw: str) -> str:
    """config.FORCE_SIGNALの生値を検証する。不正な値は無効(空欄)として扱う。"""
    if not raw:
        return ""
    if raw not in _VALID_FORCE_SIGNALS:
        logger.error(
            "FORCE_SIGNAL='%s' は無効な値です(BUY/SELL/WAIT/空欄のいずれかを指定してください)。"
            "無視して通常のAI判断で動作します。",
            raw,
        )
        return ""
    return raw


def resolve_loop_interval(cli_interval: int | None) -> int:
    """ループの待機秒数を決める。

    --intervalがCLIで明示的に指定されていればそれを優先する(固定値)。
    未指定の場合はconfig.LOOP_INTERVAL_SECONDSを都度参照するため、
    Dashboard(config.json)からの変更が次サイクルの待機時間に反映される。
    """
    return cli_interval if cli_interval is not None else config.LOOP_INTERVAL_SECONDS


def apply_force_signal(signal: Signal, force_signal: str) -> Signal:
    """発注テスト用モード: DEMO_ONLY=trueかつforce_signalが設定されている場合、
    AIの判断をforce_signalで上書きする。それ以外は元のsignalをそのまま返す
    (= 通常運転時、FORCE_SIGNALが空欄なら既存ロジックのまま)。
    """
    if not force_signal:
        return signal
    if not config.DEMO_ONLY:
        # DEMO_ONLY=falseの場合はFORCE_SIGNALを無視する(起動時に警告済み)。
        return signal

    return Signal(
        action=force_signal,  # type: ignore[arg-type]
        reason=f"[TEST MODE] FORCE_SIGNAL={force_signal} (本来のAI判断: {signal.action} / {signal.reason})",
        details=signal.details,
    )


def run_once(
    feed: FileMarketFeed,
    ai_engine,
    order_executor: FileOrderExecutor,
    force_signal: str = "",
    request_id: str | None = None,
    trade_history_feed: FileTradeHistoryFeed | None = None,
) -> Signal | None:
    """1回分のデータ取得 → 指標計算 → AI判断 → (必要なら発注) → ログ出力を行う。

    データ取得や判断、発注のどこで例外が起きても、ここで捕捉してログに残し、
    呼び出し元(ループ)を落とさない。

    先頭でconfig.load_config_json()を呼び、Dashboardからconfig.jsonが
    更新されていれば設定を再読込してから今回のサイクルを実行する。
    """
    if config.load_config_json():
        logger.info(
            "設定を再読込しました: enable_orders=%s demo_only=%s symbol=%s timeframe=%s "
            "order_volume=%s sl_points=%s tp_points=%s ema_fast=%s ema_slow=%s "
            "rsi_overbought=%s rsi_oversold=%s entry_strictness=%s loop_interval=%s秒",
            config.ENABLE_ORDERS,
            config.DEMO_ONLY,
            config.SYMBOL,
            config.TIMEFRAME,
            config.ORDER_VOLUME,
            config.SL_POINTS,
            config.TP_POINTS,
            config.EMA_FAST_PERIOD,
            config.EMA_SLOW_PERIOD,
            config.RSI_OVERBOUGHT,
            config.RSI_OVERSOLD,
            config.ENTRY_STRICTNESS,
            config.LOOP_INTERVAL_SECONDS,
        )

    try:
        daily_summary.maybe_send_daily_summary(trade_history_feed or FileTradeHistoryFeed())
    except Exception:
        logger.exception("日次サマリー送信チェック中に予期しないエラーが発生しました(Discord通知のみに影響)")

    if config.BOT_RUN_STATE != "RUNNING":
        reason = (
            "緊急停止中です(DashboardのSTARTボタンで再開できます)"
            if config.BOT_RUN_STATE == "EMERGENCY_STOPPED"
            else "停止中です(DashboardのSTARTボタンで再開できます)"
        )
        signal = Signal(action="WAIT", reason=reason, details={})
        try:
            ai_status.write_status(signal, config.SYMBOL, config.TIMEFRAME)
        except OSError:
            logger.exception("AI判断ファイルの書き出しに失敗しました(Dashboard表示のみに影響)")
        logger.info("BOT_RUN_STATE=%s のため判断・発注をスキップします", config.BOT_RUN_STATE)
        return signal

    try:
        snapshot = feed.read_snapshot(config.SYMBOL, config.TIMEFRAME)
        enriched = indicators.add_indicators(snapshot.candles)
        signal = ai_engine.decide(enriched)
        signal = apply_force_signal(signal, force_signal)

        message = (
            f"[{config.SYMBOL}] bid={snapshot.tick.bid} ask={snapshot.tick.ask} "
            f"=> {signal.action} ({signal.reason})"
        )
        print(message)
        logger.info(message)
        logger.debug("signal details: %s", signal.details)

        try:
            ai_status.write_status(signal, config.SYMBOL, config.TIMEFRAME)
        except OSError:
            logger.exception("AI判断ファイルの書き出しに失敗しました(Dashboard表示のみに影響)")

        order_executor.submit_if_needed(signal, request_id=request_id)

        return signal
    except MarketFeedError as exc:
        logger.error("価格データの取得に失敗しました: %s", exc)
        return None
    except Exception:
        logger.exception("判断処理中に予期しないエラーが発生しました")
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MT5 AI Trader MVP")
    parser.add_argument(
        "--once",
        action="store_true",
        help="ループさせず1回だけ実行して終了する",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help=(
            "ループ実行時の取得間隔(秒)。未指定の場合はconfig.LOOP_INTERVAL_SECONDS"
            "(既定60秒、config.json経由でDashboardからも変更可)を毎サイクル参照する"
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="DEBUGレベルの詳細ログを出力する",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(debug=args.debug)

    force_signal = resolve_force_signal(config.FORCE_SIGNAL)
    test_order_once = config.TEST_ORDER_ONCE

    logger.info(
        "設定: symbol=%s timeframe=%s ai_engine=%s debug=%s "
        "market_data_file=%s max_staleness=%s秒 enable_orders=%s demo_only=%s "
        "config_json=%s",
        config.SYMBOL,
        config.TIMEFRAME,
        config.AI_ENGINE,
        args.debug,
        config.MARKET_DATA_FILE_PATH,
        config.MARKET_DATA_MAX_STALENESS_SECONDS,
        config.ENABLE_ORDERS,
        config.DEMO_ONLY,
        config.CONFIG_JSON_PATH,
    )
    if config.ENABLE_ORDERS and config.DEMO_ONLY:
        logger.info(
            "発注機能が有効です: volume=%s sl_points=%s tp_points=%s entry_strictness=%s "
            "(必ずMT5のEA側もデモ口座であることを確認してください)",
            config.ORDER_VOLUME,
            config.SL_POINTS,
            config.TP_POINTS,
            config.ENTRY_STRICTNESS,
        )
    else:
        logger.info(
            "発注機能は無効です(enable_orders=%s demo_only=%s のいずれかがfalse)。"
            "判断のみ行いログに記録します。Dashboard SettingsまたはREADMEを参照してください。",
            config.ENABLE_ORDERS,
            config.DEMO_ONLY,
        )

    if force_signal or test_order_once:
        if config.DEMO_ONLY:
            logger.warning(
                "[TEST MODE] 発注テスト用モードが有効です: FORCE_SIGNAL=%s TEST_ORDER_ONCE=%s",
                force_signal or "(未設定)",
                test_order_once,
            )
        else:
            logger.warning(
                "[TEST MODE] FORCE_SIGNAL/TEST_ORDER_ONCEが設定されていますが、"
                "DEMO_ONLY=falseのため無効です(通常のAI判断のみで動作します)"
            )

    feed = FileMarketFeed()
    ai_engine = get_ai_engine()
    order_executor = FileOrderExecutor()

    exit_code = 0
    try:
        if args.once or test_order_once:
            # TEST_ORDER_ONCE用にrequest_idを1度だけ生成し、run_once()へ渡す。
            # 同じIDを使い回すことで、万一この呼び出しが二重に実行されても
            # order_executor側のガードにより二重発注にならない。
            request_id = generate_request_id() if test_order_once else None
            signal = run_once(feed, ai_engine, order_executor, force_signal=force_signal, request_id=request_id)
            if signal is None:
                exit_code = 1
        else:
            if args.interval is not None:
                logger.info(
                    "監視ループを開始します (interval=%s秒、--intervalで固定)。Ctrl+Cで終了します。",
                    args.interval,
                )
            else:
                logger.info(
                    "監視ループを開始します (interval=%s秒、config.LOOP_INTERVAL_SECONDS。"
                    "Dashboardから変更すると次サイクルから反映されます)。Ctrl+Cで終了します。",
                    config.LOOP_INTERVAL_SECONDS,
                )
            while True:
                run_once(feed, ai_engine, order_executor, force_signal=force_signal)
                # run_once()内でconfig.jsonの再読込は既に行われているため、
                # ここでは最新のconfig.LOOP_INTERVAL_SECONDSを参照するだけ。
                interval = resolve_loop_interval(args.interval)
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("ユーザーにより停止されました")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
