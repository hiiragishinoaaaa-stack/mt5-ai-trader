# mt5_ai_trader (ARTEMIS)

MT5(MetaTrader5)デモ口座 × AI判断 の自動売買BOT MVP。

**現時点のスコープは「データ取得 → 指標計算 → AI判断 → ログ保存」までであり、
実際の発注(注文執行)は行わない。**

## アーキテクチャ

```
mt5_ai_trader/
  config.py       設定値(.env読み込み)。他モジュールは全てここを参照する。
  market_feed.py  EAが書き出すJSONファイルを読み、価格データを取得する。
  ea/
    ARTEMIS_MarketFeed.mq5   MT5上で動くEA。ティック・ローソク足をJSONへ書き出す。
  indicators.py   EMA / RSI / MACD の計算(純粋関数、MT5非依存)。
  ai_engine.py    売買判断ロジック。AIEngineインターフェースの背後に隠蔽。
  logger.py       コンソール + logs/trades.log へのロギング設定。
  main.py         上記を組み合わせるエントリーポイント。
  tests/          indicators.py / market_feed.py 等の単体テスト(MT5接続不要)。
  logs/           実行ログの出力先。
```

モジュール間の依存方向は一方向(`main.py` → 各モジュール)になっており、
特定モジュールの実装を差し替えても他モジュールに影響しないよう設計している。

### なぜMT5 Python APIを使わないのか(EAブリッジ方式)

当初は `MetaTrader5` パッケージ(MT5公式のPython API)経由でデータを
取得していたが、XMTrading MT5・MetaQuotes公式MT5のいずれでも
`mt5.initialize()` がIPC timeoutで安定動作しない問題が解消できなかった。
原因はPython側のコードではなくMT5とPython間のIPC層にあると判断し、
MT5 Python APIに一切依存しない構成に切り替えている。

代わりに、MT5ターミナル上で動くEA(`ea/ARTEMIS_MarketFeed.mq5`)が
ティック・ローソク足データを定期的にJSONファイルへ書き出し、Python側
(`market_feed.py`)はそのファイルを読むだけにする。ファイルの読み込みは
ローカルディスクI/Oのため、IPC通信のようにハングする心配がない。

> **注意(`.mq5`ファイルを編集する場合)**: `ea/`配下の`.mq5`ファイルは
> 非ASCII文字(日本語等)を含めないこと。日本語コメントを含むMQL5
> ソースを一部のWindows環境のMetaEditorが誤ったコードページ
> (Shift-JIS等)で読み込み、ファイル先頭のコメントブロックが正しく
> 終端せず`input`宣言ごと壊れて`undeclared identifier`エラーになる
> 事象を確認している。EAの説明はこのREADMEに書き、`.mq5`側は英語の
> コメントのみにする。

`indicators.py` と `ai_engine.py` は、データの取得経路が変わっても
一切変更していない。`market_feed.py` が返すデータの形(pandas DataFrame、
列は `time/open/high/low/close/tick_volume/spread/real_volume`)を、
以前MT5 Python APIから取得していた形とそろえてあるため。

### AI判断エンジンの差し替え(将来のOpenAI/Claude対応)

`ai_engine.py` の `AIEngine` 抽象クラスを継承した新しいクラス
(`OpenAIEngine` / `ClaudeEngine` など)を実装し、`get_ai_engine()` の
ファクトリに登録、`.env` の `AI_ENGINE` を切り替えるだけで、
`main.py` 側のコードを一切変更せずにAI判断ロジックを差し替えられる。

## セットアップ(Windows + MT5ターミナル)

初心者向けに、MT5へのEA配置からPython実行までを順番に説明する。

### STEP 1: EAをMT5に配置する

1. MT5ターミナルを起動する(ログイン済みであること)。
2. MT5のメニューから「ファイル」→「データフォルダを開く」を選ぶ。
   エクスプローラーが開く。
3. 開いたフォルダの中の `MQL5\Experts` フォルダに、このリポジトリの
   `mt5_ai_trader\ea\ARTEMIS_MarketFeed.mq5` をコピーする。
4. MT5に戻り、「表示」→「ナビゲーター」(Ctrl+N)を開く。
   「エキスパートアドバイザ」の一覧を右クリック →「更新」すると
   `ARTEMIS_MarketFeed` が表示される。
5. MT5上部ツールバーの「アルゴ取引」ボタンが**緑色で有効**になっていることを
   確認する(灰色の場合はクリックして有効にする)。

### STEP 2: EAをチャートにコンパイル・適用する

1. ナビゲーターの `ARTEMIS_MarketFeed` をダブルクリックすると、
   自動的にMetaEditorが開きコンパイルされる(初回のみ)。
   MetaEditorのツールバーの「コンパイル」ボタンを押し、エラーが
   0件であることを確認する。
   - `undeclared identifier` 等のエラーが大量に出る場合、リポジトリから
     取得した`.mq5`ファイルがそのままコピーされているか確認する。
     `MQL5\Experts`フォルダに手動でコピー&ペーストした際、テキスト
     エディタ側の文字コード変換で壊れることがある。エクスプローラーで
     `.mq5`ファイル自体をコピーする(ファイルの中身を別エディタで
     開いて保存し直したりしない)こと。
2. MT5に戻り、USDJPYのチャートを開く(なければ「ファイル」→「新規チャート」
   →「USDJPY」)。時間足は `.env` の `TIMEFRAME` と合わせる(既定は M15)。
3. ナビゲーターの `ARTEMIS_MarketFeed` をチャート上にドラッグ&ドロップする。
4. 表示される設定ダイアログの「全般」タブで「アルゴ取引を許可する」に
   チェックを入れて「OK」を押す。
   - `InpSymbol` (既定 USDJPY)・`InpTimeframe` (既定 M15) は、
     `.env` の `SYMBOL` / `TIMEFRAME` と必ず一致させること。
5. チャート右上にスマイルアイコン(EA稼働中の印)が出ていればOK。
   「エキスパート」タブ(ターミナル下部のログ)に
   `ARTEMIS: 稼働開始。...` と表示されていることを確認する。

### STEP 3: ファイルが書き出されているか確認する

エクスプローラーで以下を開き、`artemis_market_data.json` が作成され、
数秒おきに更新日時が変わっていることを確認する。

```
%APPDATA%\MetaQuotes\Terminal\Common\Files\
```

(アドレスバーに直接`%APPDATA%\MetaQuotes\Terminal\Common\Files\`と入力するとよい)

### STEP 4: Python側をセットアップする

1. Python 3.10以上の仮想環境を作成する。
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
2. 依存関係をインストールする(MT5 Python APIを使わないため、
   `MetaTrader5` パッケージのインストールは不要)。
   ```
   pip install -r requirements.txt
   ```
3. `.env.example` を `.env` にコピーする。既定値のままで動くはずだが、
   `SYMBOL` / `TIMEFRAME` がEA側の設定と一致しているか確認する。
   ```
   copy .env.example .env
   ```

### STEP 5: 実行する

```
python main.py --once            # 1回だけ実行
python main.py                   # 既定の間隔でループ実行(Ctrl+Cで停止)
python main.py --once --debug    # 詳細ログ付きで1回実行
```

以下のような行が表示されれば成功。

```
[USDJPY] bid=157.123 ask=157.126 => WAIT (トレンド・モメンタムの条件が揃っていません)
```

判断結果はコンソールと `logs/trades.log` の両方に出力される。

### うまくいかない場合

| エラーメッセージ | 対処 |
|---|---|
| `データファイルが見つかりません` | STEP2でEAをチャートに追加したか、「アルゴ取引」が有効か確認 |
| `データが古すぎます` | EAが動作していない(チャートから外れた、MT5が落ちている等)。STEP3のファイル更新日時を確認 |
| `シンボルが一致しません` | EAの`InpSymbol`と`.env`の`SYMBOL`が食い違っている |

いずれもファイルI/Oのみで判定しているため、以前のMT5 Python API方式で
発生していた「原因不明のまま無応答で固まる」ことは構造上発生しない。

## テスト(Windows以外でも実行可能)

`indicators.py` や `ai_engine.py`、`market_feed.py` はいずれもMT5に
依存しない純粋なロジック・ファイルI/Oのため、MT5環境がなくても
単体テストを実行できる。

```
pip install -r requirements-dev.txt
pytest
```

## 免責事項

本MVPはデモ口座での動作確認・研究目的のものであり、実口座での自動発注は
一切行わない。将来的に発注機能を追加する場合も、リスク管理(ロット計算、
損切り、最大ドローダウン制御など)を別モジュールとして設計・実装した上で、
十分なバックテスト・デモ運用を経てから有効化すること。
