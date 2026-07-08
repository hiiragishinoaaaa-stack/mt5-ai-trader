"""MT5 × AI 自動売買BOT MVP のエントリーポイント。

MT5デモ口座からUSDJPY等の価格データを取得し、テクニカル指標(EMA/RSI/MACD)
を計算した上で、AIエンジンにBUY/SELL/WAITを判断させ、結果をコンソールと
logs/trades.log に出力する。

このMVPでは注文(発注)は一切行わない。判断結果を記録するところまでが
スコープであり、実売買は将来のステップで order_executor.py 等を追加して
対応する想定。

注意: mt5_client.MT5Client は接続〜データ取得を別プロセスで実行するため、
Windows上でmultiprocessingが正しく動作するよう、本ファイルの
`if __name__ == "__main__":` ガードは削除しないこと。
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
from mt5_client import MT5Client, MT5ConnectionError

# setup_logger()はmain()内で(--debugの有無を見た上で)呼び出す。
# ここではハンドラ未設定のロガーを取得するだけ(setup_logger()と同じ名前の
# ロガーを参照するため、後から設定した内容がそのまま反映される)。
logger = logging.getLogger("mt5_ai_trader")


def run_once(client: MT5Client, ai_engine) -> Signal | None:
    """1回分のデータ取得 → 指標計算 → AI判断 → ログ出力を行う。

    データ取得(別プロセスでのMT5接続を含む)や判断のどこで例外が起きても、
    ここで捕捉してログに残し、呼び出し元(ループ)を落とさない。
    """
    try:
        snapshot = client.fetch_snapshot(config.SYMBOL, config.TIMEFRAME, config.BARS_COUNT)
        enriched = indicators.add_indicators(snapshot.candles)
        signal = ai_engine.decide(enriched)

        message = (
            f"[{config.SYMBOL}] bid={snapshot.tick.bid} ask={snapshot.tick.ask} "
            f"=> {signal.action} ({signal.reason})"
        )
        print(message)
        logger.info(message)
        logger.debug("signal details: %s", signal.details)
        return signal
    except MT5ConnectionError as exc:
        logger.error("MT5とのやり取りでエラーが発生しました: %s", exc)
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
        help="DEBUGレベルの詳細ログ(MT5との通信の内訳等)を出力する",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(debug=args.debug)

    logger.info(
        "設定: symbol=%s timeframe=%s bars_count=%s ai_engine=%s debug=%s "
        "fetch_timeout=%s秒",
        config.SYMBOL,
        config.TIMEFRAME,
        config.BARS_COUNT,
        config.AI_ENGINE,
        args.debug,
        config.MT5_FETCH_TIMEOUT_SECONDS,
    )

    client = MT5Client()
    ai_engine = get_ai_engine()

    exit_code = 0
    try:
        if args.once:
            signal = run_once(client, ai_engine)
            if signal is None:
                exit_code = 1
        else:
            logger.info(
                "監視ループを開始します (interval=%s秒)。Ctrl+Cで終了します。",
                args.interval,
            )
            while True:
                run_once(client, ai_engine)
                time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("ユーザーにより停止されました")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
