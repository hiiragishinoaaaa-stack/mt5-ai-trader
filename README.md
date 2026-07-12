# mt5-ai-trader (Project ARTEMIS)

MT5 × AI 自動売買システム「ARTEMIS」。段階的に機能を拡張しているプロジェクトで、
現在は以下の2つが独立して存在する。

```
mt5-ai-trader/
  mt5_ai_trader/   Python本体 + MT5用EA(ea/)。価格取得・AI判断・(デモ口座限定の)自動発注。
  dashboard/       ARTEMIS X Dashboard。Web管理画面。Settings画面の売買設定は
                   settings_server.py(mt5_ai_trader/)と実際に接続している。
  scripts/         VPSセットアップ用スクリプト(venv作成・npm build・systemd登録)。
  deploy/systemd/  systemdサービス定義(Dashboard/settings_server.py/main.py)。
  docs/            VPS常駐デプロイ手順など。
```

VPS(常時稼働サーバー)へのデプロイ・自動起動化(systemd)については
[`docs/VPS_DEPLOYMENT.md`](docs/VPS_DEPLOYMENT.md)を参照。

## mt5_ai_trader/ — ボット本体

MT5デモ口座からEAブリッジ経由で価格を取得し、EMA/RSI/MACDでBUY/SELL/WAITを
判断してログに記録する。`DEMO_ONLY=true`の場合のみ、EA(`ARTEMIS_Bridge.mq5`)
経由でデモ口座への自動発注も行う。

詳しいセットアップ手順(EAのMT5への配置、Pythonの実行方法など)は
[`mt5_ai_trader/README.md`](mt5_ai_trader/README.md)を参照。

```
cd mt5_ai_trader
pip install -r requirements.txt
python main.py --once
```

## dashboard/ — Web管理画面

AIの判断状況・損益・ポジション・設定などを確認するためのダッシュボード。
Home/Trade/AnalyticsはまだUIモックだが、Settings画面の売買設定(AI判断
ロジック・発注設定)は`mt5_ai_trader/settings_server.py`と実際に接続しており、
保存すると`mt5_ai_trader/config.json`経由でボットに反映される。

詳しくは [`dashboard/README.md`](dashboard/README.md) を参照。

```
cd dashboard
npm install
npm run dev
```
