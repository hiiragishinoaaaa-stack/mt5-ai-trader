"""ARTEMIS X Dashboard向けの設定変更用ローカルAPIサーバー。

Dashboard(ブラウザ/スマホ)から、Python側の売買設定(config.json)を
読み書きするためだけの、依存パッケージを追加しない最小限のHTTPサーバー。
main.py(トレードのメインループ)とは別プロセスとして実行する
(このサーバーが動いていなくてもmain.pyは通常通り動作する)。

## セキュリティに関する重要な注意

このサーバーには既定で認証機能が無い。DEMO_ONLY・ENABLE_ORDERS・ロット数
などトレードに直結する設定を書き換えられるため、**信頼できるローカル
ネットワーク(自宅Wi-Fi等)内でのみ使用し、絶対にインターネットへ公開
(ポート開放・リバースプロキシ等)しないこと。**
簡易的な追加防御として、.envで`SETTINGS_API_TOKEN`を設定すると、
リクエストに`Authorization: Bearer <token>`ヘッダーが必須になる。

## エンドポイント

    GET  /api/settings   現在の設定値(config.json + .env + 既定値)を返す
    POST /api/settings   送信されたJSONで設定を更新し、config.jsonへ
                         アトミックに書き込む。範囲外の値は拒否する
                         (settings_schema.validate()を参照)。
    GET  /api/account     EA(ARTEMIS_Bridge.mq5)が書き出す残高・証拠金・
                         保有ポジション一覧を返す(account_feed.pyを参照)。
                         MT5/EA側がまだデータを書き出していない場合は
                         503を返す(settings_server自体は正常)。
    GET  /api/ai-status    main.pyが各サイクルで書き出す最新のAI判断
                         (action/confidence/reason等)を返す(ai_status.py
                         を参照)。main.pyが動作していない場合は503を返す。
    GET  /api/trade-history EA(ARTEMIS_Bridge.mq5、v4.00以降)が書き出す
                         決済済み取引一覧を返す(trade_history_feed.pyを
                         参照)。MT5/EA側がまだデータを書き出していない
                         場合は503を返す。
    POST /api/close-position DashboardのCLOSEボタンから呼ばれる。
                         config.SYMBOLのARTEMIS自身の全ポジションを決済
                         するようEAへ要求する(position_closer.pyを参照、
                         要EA v4.03以降)。ENABLE_ORDERS/DEMO_ONLYが
                         有効でない場合は決済リクエストを送出せず失敗を
                         返す。EAの応答を待つため、最大
                         ORDER_RESULT_WAIT_SECONDS秒ブロックする。

## 実行方法

    python settings_server.py
"""
from __future__ import annotations

import dataclasses
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import account_feed
import ai_status
import config
import position_closer
import settings_schema
import trade_history_feed
from logger import setup_logger

logger = logging.getLogger("mt5_ai_trader")

_SETTINGS_PATH = "/api/settings"
_ACCOUNT_PATH = "/api/account"
_AI_STATUS_PATH = "/api/ai-status"
_TRADE_HISTORY_PATH = "/api/trade-history"
_CLOSE_POSITION_PATH = "/api/close-position"
_account_feed = account_feed.FileAccountFeed()
_trade_history_feed = trade_history_feed.FileTradeHistoryFeed()
_position_closer = position_closer.FilePositionCloser()


class SettingsRequestHandler(BaseHTTPRequestHandler):
    server_version = "ARTEMISSettingsServer/1.0"

    def _set_common_headers(self, status: int, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Type", content_type)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._set_common_headers(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_authorized(self) -> bool:
        if not config.SETTINGS_API_TOKEN:
            return True  # トークン未設定なら認証チェックをしない(既定)
        expected = f"Bearer {config.SETTINGS_API_TOKEN}"
        return self.headers.get("Authorization") == expected

    def do_OPTIONS(self) -> None:  # noqa: N802 (BaseHTTPRequestHandlerの規約に合わせる)
        # ブラウザのCORSプリフライトリクエストに応答する。
        self._set_common_headers(204)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == _SETTINGS_PATH:
            self._handle_get_settings()
        elif self.path == _ACCOUNT_PATH:
            self._handle_get_account()
        elif self.path == _AI_STATUS_PATH:
            self._handle_get_ai_status()
        elif self.path == _TRADE_HISTORY_PATH:
            self._handle_get_trade_history()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_get_settings(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        settings = settings_schema.current_settings()
        self._send_json(200, {"settings": settings})

    def _handle_get_account(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            state = _account_feed.read_state()
        except account_feed.AccountFeedError as exc:
            self._send_json(503, {"error": str(exc)})
            return

        payload = dataclasses.asdict(state)
        payload["target_symbol"] = config.SYMBOL
        self._send_json(200, payload)

    def _handle_get_ai_status(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            snapshot = ai_status.read_status()
        except ai_status.AiStatusError as exc:
            self._send_json(503, {"error": str(exc)})
            return

        self._send_json(200, dataclasses.asdict(snapshot))

    def _handle_get_trade_history(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            trades = _trade_history_feed.read_history()
        except trade_history_feed.TradeHistoryError as exc:
            self._send_json(503, {"error": str(exc)})
            return

        self._send_json(200, {"trades": [dataclasses.asdict(t) for t in trades]})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == _SETTINGS_PATH:
            self._handle_post_settings()
        elif self.path == _CLOSE_POSITION_PATH:
            self._handle_post_close_position()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_post_settings(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"success": False, "errors": {"_": "不正なJSONです"}})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"success": False, "errors": {"_": "JSONオブジェクトを送信してください"}})
            return

        cleaned, errors = settings_schema.validate(payload)
        if errors:
            logger.warning("settings_server: バリデーションエラー: %s", errors)
            self._send_json(400, {"success": False, "errors": errors})
            return

        if not cleaned:
            self._send_json(400, {"success": False, "errors": {"_": "有効な設定項目が含まれていません"}})
            return

        try:
            settings_schema.save(cleaned)
        except OSError as exc:
            logger.error("settings_server: config.jsonの書き込みに失敗しました: %s", exc)
            self._send_json(500, {"success": False, "errors": {"_": f"保存に失敗しました: {exc}"}})
            return

        config.load_config_json(force=True)
        logger.info("settings_server: 設定を更新しました: %s", cleaned)
        self._send_json(200, {"success": True, "settings": settings_schema.current_settings()})

    def _handle_post_close_position(self) -> None:
        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        result = _position_closer.close_all()
        status = 200 if result.success else 409
        self._send_json(
            status,
            {"success": result.success, "message": result.message, "closed_count": result.closed_count},
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # 標準のstderr出力の代わりにアプリのロガーへ流す。
        logger.debug("settings_server: %s - %s", self.address_string(), format % args)


def main() -> None:
    setup_logger()

    if not config.SETTINGS_API_TOKEN:
        logger.warning(
            "settings_server: SETTINGS_API_TOKEN未設定のため認証なしで待受します。"
            "信頼できるローカルネットワーク以外では絶対に使用しないでください。"
        )

    server = ThreadingHTTPServer((config.SETTINGS_SERVER_HOST, config.SETTINGS_SERVER_PORT), SettingsRequestHandler)
    logger.info(
        "settings_server: http://%s:%s%s で待受を開始します (Ctrl+Cで終了)",
        config.SETTINGS_SERVER_HOST,
        config.SETTINGS_SERVER_PORT,
        _SETTINGS_PATH,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("settings_server: ユーザーにより停止されました")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
