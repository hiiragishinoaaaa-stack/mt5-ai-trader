# mt5_ai_trader (ARTEMIS)

MT5(MetaTrader5)デモ口座 × AI判断 の自動売買BOT MVP。

**Phase 1(データ取得 → 指標計算 → AI判断 → ログ保存)に加え、
Phase 2として「`DEMO_ONLY=true`の場合のみ動作するデモ口座への自動発注」
に対応した。既定(`DEMO_ONLY`未設定)では発注は一切行われない。**

## アーキテクチャ

```
mt5_ai_trader/
  config.py         設定値(.env読み込み)。他モジュールは全てここを参照する。
  market_feed.py    EAが書き出す価格データJSONを読む(Phase 1)。
  order_executor.py AIのBUY/SELL判断から発注リクエストJSONを書き出す(Phase 2)。
  ea/
    ARTEMIS_Bridge.mq5   MT5上で動くEA。価格データの書き出しと、
                         発注リクエストの読み取り・実行(order_send)を行う。
  indicators.py     EMA / RSI / MACD の計算(純粋関数、MT5非依存)。
  ai_engine.py      売買判断ロジック。AIEngineインターフェースの背後に隠蔽。
  logger.py         コンソール + logs/trades.log へのロギング設定。
  main.py           上記を組み合わせるエントリーポイント。
  tests/            indicators.py / market_feed.py / order_executor.py 等の
                    単体テスト(MT5接続不要)。
  logs/             実行ログの出力先。
```

モジュール間の依存方向は一方向(`main.py` → 各モジュール)になっており、
特定モジュールの実装を差し替えても他モジュールに影響しないよう設計している。

### なぜMT5 Python APIを使わないのか(EAブリッジ方式)

当初は `MetaTrader5` パッケージ(MT5公式のPython API)経由でデータを
取得していたが、XMTrading MT5・MetaQuotes公式MT5のいずれでも
`mt5.initialize()` がIPC timeoutで安定動作しない問題が解消できなかった。
原因はPython側のコードではなくMT5とPython間のIPC層にあると判断し、
MT5 Python APIに一切依存しない構成に切り替えている。

代わりに、MT5ターミナル上で動くEA(`ea/ARTEMIS_Bridge.mq5`)が
ティック・ローソク足データを定期的にJSONファイルへ書き出し、Python側
(`market_feed.py`)はそのファイルを読むだけにする。ファイルの読み込みは
ローカルディスクI/Oのため、IPC通信のようにハングする心配がない。

Phase 2の発注も同じ考え方で、Pythonは発注リクエストをJSONファイルへ
書き出すだけで、実際の`order_send`(MQL5では`CTrade`経由)はEA側で行う。
Python側はMT5の口座状態(残高やポジション)を一切知り得ないため、
「本当にデモ口座か」「既に同じ通貨のポジションを持っていないか」の
最終確認は必ずEA側(ブローカーに直接接続している側)で行う設計にしている。

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
   `mt5_ai_trader\ea\ARTEMIS_Bridge.mq5` をコピーする。
   - 以前のバージョン(`ARTEMIS_MarketFeed.mq5`)を既にチャートに追加
     済みの場合は、先にチャートから外し(EA名を右クリック→「削除」)、
     `MQL5\Experts`フォルダの古いファイルも削除してから、新しい
     `ARTEMIS_Bridge.mq5`を配置すること。
4. MT5に戻り、「表示」→「ナビゲーター」(Ctrl+N)を開く。
   「エキスパートアドバイザ」の一覧を右クリック →「更新」すると
   `ARTEMIS_Bridge` が表示される。
5. MT5上部ツールバーの「アルゴ取引」ボタンが**緑色で有効**になっていることを
   確認する(灰色の場合はクリックして有効にする)。

### STEP 2: EAをチャートにコンパイル・適用する

1. ナビゲーターの `ARTEMIS_Bridge` をダブルクリックすると、
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
3. ナビゲーターの `ARTEMIS_Bridge` をチャート上にドラッグ&ドロップする。
4. 表示される設定ダイアログの「全般」タブで「アルゴ取引を許可する」に
   チェックを入れて「OK」を押す(**Phase 1(価格取得)だけを試す間は
   `InpEnableOrders` は既定の `false` のままにしておくこと**。発注を
   試す手順はSTEP 6を参照)。
   - `InpSymbol` (既定 USDJPY)・`InpTimeframe` (既定 M15) は、
     `.env` の `SYMBOL` / `TIMEFRAME` と必ず一致させること。
5. チャート右上にスマイルアイコン(EA稼働中の印)が出ていればOK。
   「エキスパート」タブ(ターミナル下部のログ)に
   `ARTEMIS: started. ...` と表示されていることを確認する。

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

### うまくいかない場合(Phase 1: 価格取得)

| エラーメッセージ | 対処 |
|---|---|
| `データファイルが見つかりません` | STEP2でEAをチャートに追加したか、「アルゴ取引」が有効か確認 |
| `データが古すぎます` | EAが動作していない(チャートから外れた、MT5が落ちている等)。STEP3のファイル更新日時を確認 |
| `シンボルが一致しません` | EAの`InpSymbol`と`.env`の`SYMBOL`が食い違っている |

いずれもファイルI/Oのみで判定しているため、以前のMT5 Python API方式で
発生していた「原因不明のまま無応答で固まる」ことは構造上発生しない。

## Phase 2: デモ口座への自動発注

**必ずデモ口座で試すこと。ライブ(実)口座では絶対に有効化しないこと。**
安全のため、発注は以下の二重のロックがかかっている。いずれか一方でも
満たさなければ発注は実行されない。

1. Python側: `.env` の `DEMO_ONLY=true`(既定は未設定=false=発注しない)
2. EA側: `InpEnableOrders=true`、かつMT5が実際にデモ口座へログインして
   いることをEAが`AccountInfoInteger(ACCOUNT_TRADE_MODE)`で確認できること
   (ライブ口座だった場合、EAは`InpEnableOrders=true`でも自動的に発注を
   無効化し、「エキスパート」タブに警告を出す)

> **既知の問題**: 一部のブローカー(XM/XMTradingを含む。特に有効期限のない
> デモ口座)では、MT5ターミナルの画面上は「Demo Account」と表示されて
> いても、`ACCOUNT_TRADE_MODE`がデモとして正しく報告されないことがある
> (MQL5公式フォーラムでも報告されている既知の挙動)。この場合、EAは
> 安全側に倒して発注を無効化し、「エキスパート」タブに
> `InpConfirmedDemoAccount にこの口座番号を設定してください」という
> 案内を表示する。本当に自分のデモ口座だと確認できた場合のみ、
> EAの入力パラメータ `InpConfirmedDemoAccount` にその口座番号(ログインID)
> を入力することで、`ACCOUNT_TRADE_MODE`の代わりにこの明示的な確認を
> 発注許可の根拠として使う。**ライブ(実)口座の番号は絶対に入力しないこと。**

### STEP 6: 発注を有効化する(任意、デモ口座のみ)

1. MT5のチャート上の `ARTEMIS_Bridge` を右クリック→「エキスパートアドバイザの
   プロパティ」を開き、入力パラメータの `InpEnableOrders` を `true` に変更する。
   - `InpMagicNumber`(既定 990101)は、このEAが出した注文を識別するための
     番号。他のEAと衝突しなければ変更不要。
   - 「エキスパート」タブに `InpEnableOrders is true but this account is
     NOT recognized as a demo account` と表示された場合、上記の既知の問題
     に該当している。ログに表示される自分の口座番号(login)を確認した上で、
     `InpConfirmedDemoAccount` にその番号を入力し、EAをチャートから一度外して
     再度追加する(プロパティ変更を反映させるため)。
2. `.env` を開き、以下を設定する。
   ```
   DEMO_ONLY=true
   ORDER_VOLUME=0.01
   SL_POINTS=200
   TP_POINTS=400
   ```
   - `ORDER_VOLUME` はロット数(既定0.01固定)。
   - `SL_POINTS` / `TP_POINTS` はシンボルの最小価格単位(point)基準の
     ストップロス/テイクプロフィット距離。USDJPY(3桁表示)であれば
     200point ≒ 20pips、400point ≒ 40pips に相当する。
3. `python main.py --once --debug` を実行し、BUY/SELLが出た場合に
   以下のようなログが出ることを確認する。
   ```
   order_executor: 発注リクエストを送出しました request_id=...
   order_executor: 発注に成功しました request_id=... ticket=12345678 ...
   ```
4. MT5の「取引」タブでポジションが実際に開いたこと、SL/TPが設定されて
   いることを確認する。

### 動作の仕組み

- `main.py`はAIがBUY/SELLと判断した場合のみ、`order_executor.py`が
  発注リクエスト(`artemis_order_request.json`)を書き出す。WAITの場合は
  何もしない。
- EA(`ARTEMIS_Bridge.mq5`)はタイマーごとにこのファイルを確認し、
  存在すれば読み取って即座に削除する(1回のリクエストを二重処理しない
  ため)。その後、以下を順に確認し、いずれかに該当すれば発注せず
  理由を結果ファイルに書く。
  1. リクエストの`demo_only`がtrueか
  2. 接続中の口座が本当にデモ口座か
  3. リクエストのシンボルがEAの`InpSymbol`と一致するか
  4. 同じシンボルの既存ポジションが無いか(あれば発注をスキップする)
- 全てクリアした場合のみ`CTrade`経由で成行注文(SL/TP付き)を送信し、
  成功/失敗を結果ファイル(`artemis_order_result.json`)に書き出す。
- Pythonはこの結果ファイルを最大`ORDER_RESULT_WAIT_SECONDS`秒
  (既定10秒)待って読み取り、成功/失敗を`logs/trades.log`に記録する。
  待っても結果が確認できない場合も例外にはせず、警告ログを出して
  次のサイクルへ進む。

### うまくいかない場合(Phase 2: 発注)

| 結果メッセージ | 対処 |
|---|---|
| `DEMO_ONLY=falseのため発注をスキップします` | `.env`で`DEMO_ONLY=true`を設定 |
| `rejected: this account is not recognized as a demo account` | MT5がライブ口座にログインしているか、`ACCOUNT_TRADE_MODE`の既知の誤判定(上記STEP6の注記を参照)。デモ口座であることを確認できたら`InpConfirmedDemoAccount`を設定する |
| `rejected: demo_only flag was not true` | 通常発生しない(Python側のバグの可能性)。Issueで報告してほしい |
| `skipped: a position already exists for this symbol` | 想定通りの動作(仕様どおり重複発注しない) |
| `%s秒待っても結果を確認できませんでした` | `InpEnableOrders=true`になっているか、EAが稼働しているか確認 |

## テスト(Windows以外でも実行可能)

`indicators.py` や `ai_engine.py`、`market_feed.py`、`order_executor.py`
はいずれもMT5に依存しない純粋なロジック・ファイルI/Oのため、MT5環境が
なくても単体テストを実行できる(`order_executor.py`のテストは、EAの
代わりに結果ファイルを書き出す疑似コードでEAとのやり取りを再現している)。

```
pip install -r requirements-dev.txt
pytest
```

## 免責事項

本プロジェクトはデモ口座での動作確認・研究目的のものであり、実口座
(ライブ口座)での自動発注は想定していない。Phase 2の発注機能は
`DEMO_ONLY=true`かつEA側の`InpEnableOrders=true`かつ実際にデモ口座へ
ログインしている場合のみ動作するよう二重にロックしているが、これは
「事故的にライブ口座で発注してしまうリスクを下げる」ためのものであり、
デモ口座であっても発注に伴う挙動(約定・SL/TP設定など)に不具合が
無いことを保証するものではない。

ロットは0.01固定、SL/TPは`SL_POINTS`/`TP_POINTS`で設定される以外の
リスク管理(最大ポジション数、最大ドローダウン制御、資金管理など)は
実装していない。将来ライブ口座での運用を検討する場合は、それらを
別モジュールとして設計・実装した上で、十分なバックテスト・長期の
デモ運用を経てから判断すること。
