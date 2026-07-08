"""MT5 × AI 自動売買BOT MVP のエントリーポイント。

MT5デモ口座からUSDJPY等の価格データを取得し、テクニカル指標(EMA/RSI/MACD)
を計算した上で、AIエンジンにBUY/SELL/WAITを判断させ、結果をコンソールと
logs/trades.log に出力する。

このMVPでは注文(発注)は一切行わない。判断結果を記録するところまでが
スコープであり、実売買は将来のステップで order_executor.py 等を追加して
対応する想定。
"""
from __future__ import annotations

import argparse
import time

import config
import indicators
from ai_engine import Signal, get_ai_engine
from logger import setup_logger
from mt5_client import MT5Client, MT5ConnectionError

logger = setup_logger()


def run_once(client: MT5Client, ai_engine) -> Signal | None:
    """1回分のデータ取得 → 指標計算 → AI判断 → ログ出力を行う。

    データ取得や判断のどこで例外が起きても、ここで捕捉してログに残し、
    呼び出し元(ループ)を落とさない。
    """
    try:
        tick = client.get_latest_tick(config.SYMBOL)
        candles = client.get_candles(config.SYMBOL, config.TIMEFRAME, config.BARS_COUNT)
        enriched = indicators.add_indicators(candles)
        signal = ai_engine.decide(enriched)

        message = (
            f"[{config.SYMBOL}] bid={tick.bid} ask={tick.ask} "
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = MT5Client()
    ai_engine = get_ai_engine()

    try:
        client.connect()
    except MT5ConnectionError as exc:
        logger.error("MT5への接続に失敗しました: %s", exc)
        return

    logger.info(
        "MT5接続に成功しました。symbol=%s timeframe=%s ai_engine=%s",
        config.SYMBOL,
        config.TIMEFRAME,
        config.AI_ENGINE,
    )

    try:
        if args.once:
            run_once(client, ai_engine)
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
    finally:
        client.disconnect()
        logger.info("MT5との接続を終了しました")


if __name__ == "__main__":
    main()
