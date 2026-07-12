# mt5_ai_trader (ARTEMIS)

MT5(MetaTrader5)デモ口座 × AI判断 の自動売買BOT MVP。

**Phase 1(データ取得 → 指標計算 → AI判断 → ログ保存)に加え、
Phase 2として「`DEMO_ONLY=true`の場合のみ動作するデモ口座への自動発注」
に対応した。既定(`DEMO_ONLY`未設定)では発注は一切行われない。**

Web管理画面(UIモック)は`../dashboard/`にある。現時点ではこのPython本体とは
接続していない、独立したフロントエンドプロジェクト。詳細は
[`dashboard/README.md`](../dashboard/README.md)を参照。

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

エクスプローラーで以下を開き、`artemis_market_data.json` と
`artemis_account_state.json` が作成され、数秒おきに更新日時が
変わっていることを確認する。

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

### 発注テスト用モード(FORCE_SIGNAL / TEST_ORDER_ONCE)

通常はAIの判断(EMA/RSI/MACD)がBUY/SELLの条件を満たすまで発注は行われない。
条件が揃うのを待たずに「MT5への発注 → SL/TP設定 → 結果JSON確認」までの
一連の流れだけを素早く確認したい場合、`.env`に以下を設定する。

```
DEMO_ONLY=true
FORCE_SIGNAL=BUY
TEST_ORDER_ONCE=true
```

```
python main.py --debug
```

- **`FORCE_SIGNAL`**: `BUY` / `SELL` / `WAIT` / 空欄のいずれか。設定すると、
  AIが実際に計算した判断(EMA/RSI/MACD)を無視して、この値を強制的に使う。
  ログには判断のたびに `[TEST MODE] FORCE_SIGNAL=BUY (本来のAI判断: WAIT / ...)`
  のように、本来の判断と合わせて**テストモード中であることが明確に表示**される。
  **`DEMO_ONLY=true`の場合のみ有効**で、`DEMO_ONLY=false`のまま設定した
  場合は起動時に警告ログを出した上で無視され、通常のAI判断で動作する。
- **`TEST_ORDER_ONCE`**: `true`にすると、CLIの`--once`指定の有無に関わらず、
  起動後ちょうど1サイクルだけ実行してプロセスを終了する。ループ実行の
  つもりで`.env`の設定を消し忘れても、発注が繰り返されることはない。
- **二重発注防止**: `TEST_ORDER_ONCE`実行では発注リクエストのIDを起動時に
  1つだけ生成し、そのIDを使い回す。同じIDでの発注は`order_executor.py`が
  内部で記録しており、万一同じ実行内で処理が重複しても2件目は
  `request_id=... は送出済みのためスキップします(二重発注防止)`
  というログとともに送出をスキップする(実際にEA側へファイルを二重に
  書き出すことはない)。
- **通常運転に戻す**: `FORCE_SIGNAL`を空欄に戻す(`TEST_ORDER_ONCE`も
  `false`に戻す)だけで、既存のAI判断ロジック・ループ実行にそのまま戻る。
  コードの変更は不要。

### うまくいかない場合(Phase 2: 発注)

| 結果メッセージ | 対処 |
|---|---|
| `ENABLE_ORDERS=falseのため発注をスキップします` | `.env`またはDashboardの「発注設定」で`ENABLE_ORDERS=true`を設定 |
| `DEMO_ONLY=falseのため発注をスキップします` | `.env`またはDashboardの「発注設定」で`DEMO_ONLY=true`を設定 |
| `rejected: this account is not recognized as a demo account` | MT5がライブ口座にログインしているか、`ACCOUNT_TRADE_MODE`の既知の誤判定(上記STEP6の注記を参照)。デモ口座であることを確認できたら`InpConfirmedDemoAccount`を設定する |
| `rejected: demo_only flag was not true` | 通常発生しない(Python側のバグの可能性)。Issueで報告してほしい |
| `skipped: a position already exists for this symbol` | 想定通りの動作(仕様どおり重複発注しない) |
| `%s秒待っても結果を確認できませんでした` | `InpEnableOrders=true`になっているか、EAが稼働しているか確認 |

## Dashboardからの設定変更(settings_server.py)

ARTEMIS X Dashboard(`../dashboard/`)のSettings画面から、コードや`.env`を
直接編集せずに売買設定を変更できる。`.env`はGit管理・起動時固定の設定、
`config.json`はDashboardから実行中でも書き換えられる設定、という役割分担。
読み込み優先度は **config.json > .env > コード上の既定値**。

### 変更できる項目

| 項目 | 意味 | 範囲/選択肢 |
|---|---|---|
| `ORDER_VOLUME` | 発注ロット数 | 0.01〜100 |
| `SL_POINTS` | ストップロス距離(point) | 0〜100000 |
| `TP_POINTS` | テイクプロフィット距離(point) | 0〜100000 |
| `TIMEFRAME` | 判断に使う時間足 | M1/M5/M15/M30/H1/H4/D1 |
| `LOOP_INTERVAL_SECONDS` | 監視ループの間隔(秒) | 5〜86400 |
| `RSI_OVERBOUGHT` | RSI買われすぎ閾値 | 50〜100 |
| `RSI_OVERSOLD` | RSI売られすぎ閾値 | 0〜50 |
| `EMA_FAST_PERIOD` | EMA短期期間 | 1〜500 |
| `EMA_SLOW_PERIOD` | EMA長期期間 | 2〜1000 |
| `ENTRY_STRICTNESS` | エントリーの厳しさプリセット | conservative(65/35) / balanced(70/30) / aggressive(80/20)。選択するとRSI_OVERBOUGHT/OVERSOLDに反映される |
| `ENABLE_ORDERS` | 発注そのものを行うか | true/false |
| `DEMO_ONLY` | 対象口座がデモであること | true/false |
| `BOT_RUN_STATE` | Bot稼働状態(DashboardのSTART/STOP/EMERGENCY STOP) | RUNNING/STOPPED/EMERGENCY_STOPPED。詳細は「DashboardのSTART/STOP/EMERGENCY STOP(Phase 5)」を参照 |
| `DISCORD_NOTIFY_DAILY_SUMMARY` | 日次サマリー通知のON/OFF | true/false。詳細は「日次サマリー通知(Phase 6)」を参照 |
| `AI_ENGINE` | AI判断エンジンの選択 | rule_based/openai/claude。APIキーは含まれない(.envでのみ設定)。詳細は「AI判断エンジン: OpenAI/Claude連携(Phase 7)」を参照 |

`RSI_OVERBOUGHT`は`RSI_OVERSOLD`より大きい値、`EMA_FAST_PERIOD`は
`EMA_SLOW_PERIOD`より小さい値である必要があり、範囲外・矛盾した値は
保存前に拒否される(`settings_schema.py`)。

**`TIMEFRAME`についての注意**: この値を変えても、EA(`ARTEMIS_Bridge.mq5`)
が実際に取得するローソク足の時間軸は自動的には変わらない。EA側の
`InpTimeframe`もMT5上で合わせて変更すること。

### STEP 7: settings_server.pyを起動する

```
python settings_server.py
```

`main.py`(トレードのメインループ)とは別プロセスとして実行する
(`settings_server.py`が動いていなくても`main.py`は通常通り動作する。
config.jsonが存在すればその内容を使い、無ければ従来通り`.env`/既定値で動く)。

既定では`http://0.0.0.0:8787`で待受する。Dashboard側の接続先設定は
[`dashboard/README.md`](../dashboard/README.md)を参照。

### セキュリティに関する重要な注意

`settings_server.py`には既定で認証機能が無い。`ENABLE_ORDERS`・
`DEMO_ONLY`・ロット数などトレードに直結する設定を書き換えられるため、
**必ず信頼できるローカルネットワーク(自宅Wi-Fi等)内でのみ使用し、
インターネットへは絶対に公開しないこと**(ポート開放・リバースプロキシ等禁止)。

簡易的な追加防御として、`.env`で`SETTINGS_API_TOKEN`を設定すると、
`Authorization: Bearer <token>`ヘッダーの無いリクエストを拒否できる。
設定した場合、Dashboard側の`VITE_SETTINGS_API_TOKEN`にも同じ値を
設定すること。

### 実行中の設定反映のしくみ

`main.py`は監視ループの各サイクルの先頭で`config.load_config_json()`を
呼び、`config.json`の更新日時が前回と変わっていれば自動的に再読込する。
そのため`settings_server.py`経由でDashboardから設定を保存すると、
次のサイクル(既定では次の`LOOP_INTERVAL_SECONDS`後)から新しい設定が
反映される。ループの間隔自体(`LOOP_INTERVAL_SECONDS`)を変更した場合も、
`--interval`をCLIで明示していなければ次のサイクルから新しい間隔になる。

### うまくいかない場合(Dashboard連携)

| 症状 | 対処 |
|---|---|
| Dashboardに「Bot APIに接続できません」と出る | `python settings_server.py`を起動しているか確認。スマホから開いている場合は`dashboard/.env.local`の`VITE_SETTINGS_API_URL`がPCのLAN IPになっているか確認(`localhost`はスマホ自身を指してしまうため不可) |
| 保存しても`main.py`側に反映されない | `main.py`が起動中か、`CONFIG_JSON_PATH`が両方のプロセスで同じ場所を指しているか確認 |
| `401 Unauthorized` | `SETTINGS_API_TOKEN`を設定した場合、Dashboard側`VITE_SETTINGS_API_TOKEN`が一致しているか確認 |
| Home/Tradeの残高・ポジションが「—」のまま | `GET /api/account`が503を返している状態。EA(v3.00以降)が`artemis_account_state.json`を書き出しているか、MT5が起動しているか確認 |

## Dashboardの残高・ポジション表示(account_feed.py)

EA(`ARTEMIS_Bridge.mq5`)は価格データ・発注結果に加えて、口座の残高・
証拠金・保有中の全ポジションを`artemis_account_state.json`へ定期的に
書き出す(`InpUpdateIntervalSec`と同じ間隔)。`account_feed.py`がこの
ファイルを読み、`settings_server.py`の`GET /api/account`がDashboardへ返す。

- MT5に接続している口座の**すべての**ポジション(このEA以外が発注したものも
  含む)を返す。ARTEMISが発注したポジションには`is_artemis: true`のフラグが
  付く(`InpMagicNumber`が一致するかで判定)。
- データが無い/古すぎる(既定30秒、`ACCOUNT_STATE_MAX_STALENESS_SECONDS`で
  変更可)場合は`503`を返す。これは認証エラーやサーバーダウンとは別の状態
  として扱われ、DashboardのHome/Trade画面は「MT5からの応答待ち」の表示になる
  (エラー扱いにはならない)。
- 既存のEAをMT5で使っている場合、`ARTEMIS_Bridge.mq5`を再コンパイル・
  再適用しないとこの機能は有効にならない(EA側のバージョン: 3.00以降)。

## DashboardのAI判断・取引履歴・Discord通知(Phase 4)

### AI判断のリアルタイム表示(ai_status.py)

`main.py`は各サイクルの判断(BUY/SELL/WAIT・confidence・理由)を
`artemis_ai_status.json`(MT5非依存、Pythonのプロジェクトフォルダ内)へ
書き出す。`ai_status.py`がこれを読み、`settings_server.py`の
`GET /api/ai-status`がDashboardのHome/Trade画面へ返す。`confidence`は
統計的な確率ではなく、トレンド/MACD/RSIの3条件のうち何個満たされたかを
0/33/66/100で表したヒューリスティックな値(`ai_engine.RuleBasedAIEngine`
参照)。`main.py`が動作していない場合は`503`を返す。

### 取引履歴(trade_history_feed.py)

EA(`ARTEMIS_Bridge.mq5`、v4.00以降)は`HistorySelect()`で直近の決済済み
ポジション(既定30日・最大50件、`InpTradeHistoryDays`/`InpTradeHistoryMaxCount`
で変更可)を`artemis_trade_history.json`へ書き出す(既定10秒間隔、
`InpTradeHistoryIntervalSec`)。`trade_history_feed.py`がこれを読み、
`settings_server.py`の`GET /api/trade-history`がDashboardのTrade/
Analytics画面へ返す(新しい順)。MT5は発注理由を知らないため、AIの判断
理由は含まれない(直近の理由は`GET /api/ai-status`を参照)。DashboardのHome
「Today's Profit」「Win Rate」、Analytics画面の各種統計はすべてこの
取引履歴から計算される(EAの取得範囲内のデータに基づく)。

### Discord通知(discord_notifier.py)

`DISCORD_ENABLED=true`かつ`DISCORD_WEBHOOK_URL`を設定すると、発注が
成功/失敗するたびにDiscordへ通知を送信する(`DISCORD_NOTIFY_ON_TRADE`/
`DISCORD_NOTIFY_ON_ERROR`で個別にON/OFF可能)。外部ライブラリを追加せず
`urllib.request`で直接Webhook URLへPOSTする。送信に失敗してもログに
警告を出すだけで、発注処理そのものには影響しない。これらの設定は
DashboardのSettings画面(「Discord通知」)から変更でき、`.env`と同じく
`config.json`経由でも上書きできる(`settings_schema.FIELDS`を参照)。

## DashboardのSTART/STOP/EMERGENCY STOP(Phase 5)

DashboardのHome画面のSTART/STOPボタンは、`settings_schema.py`のFIELDSに
追加した`BOT_RUN_STATE`(`RUNNING` / `STOPPED` / `EMERGENCY_STOPPED`)を
既存の`GET/POST /api/settings`経由で読み書きするだけで実現している。
新しい専用エンドポイントは追加していない。

- Dashboardのボタンを押すと`POST /api/settings`で`BOT_RUN_STATE`が
  変更され、`config.json`へ保存される。
- `main.py`は`run_once()`の先頭(`config.load_config_json()`の直後)で
  `config.BOT_RUN_STATE`を確認し、`RUNNING`以外の場合は価格取得・AI判断・
  発注を一切行わず、`WAIT`のai_status(「停止中です」/「緊急停止中です」)
  だけを書き出して早期リターンする。プロセス自体(`main.py`のループ、
  および対応するsystemdサービス)は動き続けるため、Dashboardから再度
  `START`を押せば即座に再開する。
- `order_executor.submit_if_needed()`側にも同じチェックを多層防御として
  入れている(通常は`main.py`側で既にスキップされるため到達しないが、
  直接呼び出された場合に備えたもの)。

### なぜsystemdサービスの起動/停止そのものではないのか

`settings_server.py`はデフォルトで認証なし(`SETTINGS_API_TOKEN`未設定)
でも動作するHTTPサーバーであるため、これがsudo/polkit経由でsystemdの
サービスを直接起動・停止できるようにすると、権限昇格の攻撃面になり得る。
そのため、プロセスそのものは常に動かし続けたまま「判断・発注だけを
止める」ソフトポーズ方式を採用している。VPSのSSH/systemdからの本当の
プロセス停止(`sudo systemctl stop artemis-bot`)は、これまで通り
サーバー管理者の操作としてのみ行う。

## 日次サマリー通知(Phase 6)

`DISCORD_ENABLED=true`かつ`DISCORD_NOTIFY_DAILY_SUMMARY=true`の場合、
1日1回、その日(UTC暦日)に決済された取引の損益サマリー(損益合計・
取引数・勝率)をDiscordへ送信する(`daily_summary.py`)。DashboardのSettings
画面の「Discord通知」から`DISCORD_NOTIFY_DAILY_SUMMARY`をON/OFFできる
(`settings_schema.FIELDS`に追加済み、既存の`GET/POST /api/settings`を
そのまま使う)。

- 送信時刻は`DAILY_SUMMARY_HOUR`(既定13、UTC)で指定する。UTC時刻な点に
  注意(既定値はJSTの22時に相当)。JSTでの希望時刻から9を引いた値
  (24時間表記、負になる場合は+24)を`.env`で設定する。
- `main.py`は`run_once()`の先頭で毎サイクル`daily_summary.maybe_send_daily_summary()`
  を呼び出す。実際に送信するのは「指定時刻以降になっていて、かつ今日分を
  まだ送信していない場合」だけで、送信済みかどうかは
  `artemis_daily_summary_state.json`(gitignore対象)に保存され、プロセス
  再起動をまたいでも重複送信しない。
- `BOT_RUN_STATE`がRUNNING以外(STOPPED/EMERGENCY_STOPPED)でもこの
  チェックは動作する(売買を止めていてもその日の結果は送信される)。

## AI判断エンジン: OpenAI/Claude連携(Phase 7)

`AI_ENGINE`を`openai`または`claude`にすると、EMA/RSI/MACDのルールベース
判断(`RuleBasedAIEngine`)の代わりに、実際にOpenAI/AnthropicのAPIを呼び
出してBUY/SELL/WAITを判断させる(`openai_engine.py` / `claude_engine.py`)。
DashboardのSettings画面(「AI判断ロジック」の「判断エンジン」)からも
切り替えられる(`settings_schema.FIELDS`の`AI_ENGINE`)。

### 使い方

1. `.env`に以下のいずれか(または両方)を設定する。

   ```
   AI_ENGINE=openai
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o-mini
   ```

   または

   ```
   AI_ENGINE=claude
   ANTHROPIC_API_KEY=sk-ant-...
   ANTHROPIC_MODEL=claude-sonnet-5
   ```

2. `settings_server.py`・`main.py`を再起動する(または既にDashboardから
   `AI_ENGINE`だけ切り替える場合は、次サイクルの`config.load_config_json()`
   で自動的に反映される)。

APIキーの取得先: OpenAIは https://platform.openai.com/api-keys 、
Anthropicは https://console.anthropic.com/settings/keys 。

### 判断の仕組み

`main.py`が毎サイクル計算する指標(EMA/RSI/MACD、直近の終値10件)を
`ai_engine.describe_market_conditions()`でテキスト化してプロンプトに含め、
「BUY/SELL/WAITのいずれかとreason・confidence(0-100)をJSONで返す」よう
指示する(`ai_engine.LLM_SYSTEM_PROMPT`)。応答は`ai_engine.parse_llm_signal_json()`
で解析し、`Signal`(ルールベースと同じ型)に変換する。main.py側の呼び出し
コードは`RuleBasedAIEngine`と完全に同じで、変更不要。

### 安全設計・コストに関する注意

- **APIキー未設定の場合、該当エンジンは毎回WAITを返す**(発注は一切行われ
  ない)。エラーにはならず、ai_statusの理由欄にキー未設定である旨が表示
  される。
- ネットワークエラー・タイムアウト・不正な形式のレスポンス(JSON以外の
  文章、action値が不正、等)のいずれの場合も例外を送出せず、必ずWAITに
  フォールバックする。外部APIの不具合が誤った発注に直結しないようにする
  ためで、実際の発注可否は引き続き`ENABLE_ORDERS`/`DEMO_ONLY`が最終的に
  ゲートする(`order_executor.py`)。
- **実際に利用ごとに料金が発生する。** 既定の`LOOP_INTERVAL_SECONDS=60`の
  ままだと1日1000回以上APIを呼び出す可能性があるため、コストを抑えたい
  場合は`LOOP_INTERVAL_SECONDS`を長くすることを検討する。
- APIキー自体はセキュリティ上の理由でDashboard(`settings_schema.FIELDS`)
  には含まれず、`.env`でのみ設定する(`GET /api/settings`のレスポンスに
  一切含まれない)。`AI_ENGINE`(どのエンジンを使うか)だけがDashboardから
  変更できる。

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
