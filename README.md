# mt5-ai-trader (Project ARTEMIS)

MT5 × AI 自動売買システム「ARTEMIS」。段階的に機能を拡張しているプロジェクトで、
現在は以下の2つが独立して存在する。

```
mt5-ai-trader/
  mt5_ai_trader/   Python本体 + MT5用EA(ea/)。価格取得・AI判断・(デモ口座限定の)自動発注。
  dashboard/       ARTEMIS X Dashboard。Web管理画面のUIモック(まだPython/MT5とは未接続)。
```

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

## dashboard/ — Web管理画面(UIモック)

AIの判断状況・損益・ポジション・設定などを確認するためのダッシュボード。
現時点ではUIのみで、実データとの接続は行っていない。

詳しくは [`dashboard/README.md`](dashboard/README.md) を参照。

```
cd dashboard
npm install
npm run dev
```
