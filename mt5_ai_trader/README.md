# mt5_ai_trader

MT5(MetaTrader5)デモ口座 × AI判断 の自動売買BOT MVP。

**現時点のスコープは「データ取得 → 指標計算 → AI判断 → ログ保存」までであり、
実際の発注(注文執行)は行わない。**

## アーキテクチャ

```
mt5_ai_trader/
  config.py       設定値(.env読み込み)。他モジュールは全てここを参照する。
  mt5_client.py   MT5ターミナルとの通信(接続/ティック取得/ローソク足取得)。
  indicators.py   EMA / RSI / MACD の計算(純粋関数、MT5非依存)。
  ai_engine.py    売買判断ロジック。AIEngineインターフェースの背後に隠蔽。
  logger.py       コンソール + logs/trades.log へのロギング設定。
  main.py         上記を組み合わせるエントリーポイント。
  tests/          indicators.py 等の単体テスト(MT5接続不要)。
  logs/           実行ログの出力先。
```

モジュール間の依存方向は一方向(`main.py` → 各モジュール)になっており、
特定モジュールの実装を差し替えても他モジュールに影響しないよう設計している。

### AI判断エンジンの差し替え(将来のOpenAI/Claude対応)

`ai_engine.py` の `AIEngine` 抽象クラスを継承した新しいクラス
(`OpenAIEngine` / `ClaudeEngine` など)を実装し、`get_ai_engine()` の
ファクトリに登録、`.env` の `AI_ENGINE` を切り替えるだけで、
`main.py` 側のコードを一切変更せずにAI判断ロジックを差し替えられる。

## セットアップ(Windows + MT5ターミナル)

MetaTrader5のPythonパッケージはWindows上で稼働するMT5ターミナルが必要な
ため、実行にはWindows環境が必要。

1. MT5ターミナルをインストールし、デモ口座を作成してログインしておく。
2. Python 3.10以上の仮想環境を作成する。
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
3. 依存関係をインストールする。
   ```
   pip install -r requirements.txt
   ```
4. `.env.example` を `.env` にコピーし、デモ口座の情報を入力する。
   ```
   copy .env.example .env
   ```
5. 実行する。
   ```
   python main.py --once      # 1回だけ実行
   python main.py              # 既定の間隔でループ実行(Ctrl+Cで停止)
   python main.py --once --debug   # MT5との通信の詳細ログ付きで1回実行
   ```

判断結果はコンソールと `logs/trades.log` の両方に出力される。

### 接続がうまくいかない場合

`mt5.initialize()` の前後にログを出力しているため、`--debug` を付けて
実行し、`logs/trades.log` またはコンソール出力で以下を確認する。

- `MT5_PATH` が正しいファイルに存在しているか(ログに `存在=True/False` と出る)
- `login` / `server` が空欄になっていないか
- MT5ターミナルが起動・デモ口座にログイン済みか

`mt5.initialize()` が応答しない場合でも、`MT5_INIT_TIMEOUT_MS`(既定10秒、
`.env` で変更可)を超えるとエラーとして打ち切られ、`main.py --once` は
ハングせずにエラー終了する。

## テスト(Windows以外でも実行可能)

`indicators.py` や `ai_engine.py` はMT5に依存しない純粋なロジックのため、
MT5環境がなくても単体テストを実行できる。

```
pip install -r requirements-dev.txt
pytest
```

## 免責事項

本MVPはデモ口座での動作確認・研究目的のものであり、実口座での自動発注は
一切行わない。将来的に発注機能を追加する場合も、リスク管理(ロット計算、
損切り、最大ドローダウン制御など)を別モジュールとして設計・実装した上で、
十分なバックテスト・デモ運用を経てから有効化すること。
