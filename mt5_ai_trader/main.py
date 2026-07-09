"""MT5 × AI 自動売買BOT MVP のエントリーポイント。

MT5デモ口座からUSDJPY等の価格データを取得し、テクニカル指標(EMA/RSI/MACD)
を計算した上で、AIエンジンにBUY/SELL/WAITを判断させ、結果をコンソールと
logs/trades.log に出力する。

BUY/SELLと判断された場合、config.DEMO_ONLY が明示的にTrueであれば
order_executor.py が発注リクエストを送出する(既定はOFF)。実際の発注
そのものはEA側(ea/ARTEMIS_Bridge.mq5)が行い、Pythonは一切MT5へ
直接発注しない。

価格データの取得・発注のいずれもMT5 Python API(MetaTrader5パッケージ)
ではなく、EAブリッジ方式(ea/ARTEMIS_Bridge.mq5がJSONファイル経由で
やり取りする)で行っている。詳細はmarket_feed.py / order_executor.py の
docstringとREADME.mdを参照。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import config
import indicators
from ai_engine import Signal, get_ai_engine
from logger import setup_logger
from market_feed import FileMarketFeed, MarketFeedError
from order_executor import FileOrderExecutor

# setup_logger()はmain()内で(--debugの有無を見た上で)呼び出す。
# ここではハンドラ未設定のロガーを取得するだけ(setup_logger()と同じ名前の
# ロガーを参照するため、後から設定した内容がそのまま反映される)。
logger = logging.getLogger("mt5_ai_trader")


def run_once(feed: FileMarketFeed, ai_engine, order_executor: FileOrderExecutor) -> Signal | None:
    """1回分のデータ取得 → 指標計算 → AI判断 → (必要なら発注) → ログ出力を行う。

    データ取得や判断、発注のどこで例外が起きても、ここで捕捉してログに残し、
    呼び出し元(ループ)を落とさない。
    """
    try:
        snapshot = feed.read_snapshot(config.SYMBOL, config.TIMEFRAME)
        enriched = indicators.add_indicators(snapshot.candles)
        signal = ai_engine.decide(enriched)

        message = (
            f"[{config.SYMBOL}] bid={snapshot.tick.bid} ask={snapshot.tick.ask} "
            f"=> {signal.action} ({signal.reason})"
        )
        print(message)
        logger.info(message)
        logger.debug("signal details: %s", signal.details)

        order_executor.submit_if_needed(signal)

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
        default=config.LOOP_INTERVAL_SECONDS,
        help="ループ実行時の取得間隔(秒)",
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

    logger.info(
        "設定: symbol=%s timeframe=%s ai_engine=%s debug=%s "
        "market_data_file=%s max_staleness=%s秒 demo_only=%s",
        config.SYMBOL,
        config.TIMEFRAME,
        config.AI_ENGINE,
        args.debug,
        config.MARKET_DATA_FILE_PATH,
        config.MARKET_DATA_MAX_STALENESS_SECONDS,
        config.DEMO_ONLY,
    )
    if config.DEMO_ONLY:
        logger.info(
            "発注機能が有効です: volume=%s sl_points=%s tp_points=%s "
            "(必ずMT5のEA側もデモ口座であることを確認してください)",
            config.ORDER_VOLUME,
            config.SL_POINTS,
            config.TP_POINTS,
        )

    feed = FileMarketFeed()
    ai_engine = get_ai_engine()
    order_executor = FileOrderExecutor()

    exit_code = 0
    try:
        if args.once:
            signal = run_once(feed, ai_engine, order_executor)
            if signal is None:
                exit_code = 1
        else:
            logger.info(
                "監視ループを開始します (interval=%s秒)。Ctrl+Cで終了します。",
                args.interval,
            )
            while True:
                run_once(feed, ai_engine, order_executor)
                time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("ユーザーにより停止されました")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
