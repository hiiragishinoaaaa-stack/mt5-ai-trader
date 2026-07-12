# VPSへの常駐デプロイ(Ubuntu 24.04 + Hostinger VPS想定)

ARTEMIS一式(Dashboard / settings_server.py / main.pyのAIボット)をVPS上で
再起動しても自動的に立ち上がる状態にするための手順。MT5自体はWindows専用
アプリケーションのため、Linux VPS上ではWineを使って動かす。

このドキュメントは以下の3つの独立した悩みをまとめて解決する。

1. Ubuntu 24.04で`pip install`が`externally-managed-environment`エラーで
   失敗する(PEP 668) → venvを使う
2. Dashboard / settings_server.py / main.py を再起動後も自動起動させたい
   → systemdサービス化する
3. VPS上でMT5(EA経由の価格取得・発注)を動かしたい → WineでMetaTrader5を
   動かし、Common/Filesのパスを明示的に設定する

## 前提

- Ubuntu 24.04 LTSのVPS(xrdpでGUIログイン可能な状態)
- リポジトリが `/opt/artemis/mt5-ai-trader` にcloneされている(パスが違う
  場合は以下のコマンド中のパスを読み替える)
- Node.js 20以上、Python 3.10以上が入っていること

Node.jsが未インストールの場合:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

## STEP 1: Python venv + Dashboardビルド + .env作成(1コマンド)

`scripts/setup_vps.sh` が以下をまとめて行う。

- `mt5_ai_trader/.venv` にvenvを作成し、そこへ `requirements.txt` を
  インストール(システムのpythonには一切触らないため、PEP 668の
  `externally-managed-environment` エラーを回避できる)
- `mt5_ai_trader/.env` が無ければ `.env.example` からコピー
- `dashboard/` で `npm install && npm run build`

```bash
cd /opt/artemis/mt5-ai-trader
bash scripts/setup_vps.sh
```

エラーになった場合は先に以下を実行してから再度実行する。

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
```

## STEP 2: mt5_ai_trader/.env を編集する

`scripts/setup_vps.sh` が作成した `mt5_ai_trader/.env` を編集する。
最低限、以下を確認・変更する。

```bash
nano /opt/artemis/mt5-ai-trader/mt5_ai_trader/.env
```

- `SYMBOL` / `TIMEFRAME`: MT5側のEA設定(STEP 4参照)と一致させる
- `SETTINGS_SERVER_HOST=0.0.0.0`: Dashboardからアクセスできるように既定で
  全インターフェース待受(既に既定値なので変更不要)
- `SETTINGS_API_TOKEN`: **VPSは公開IPを持つため、必ず値を設定することを
  強く推奨する**(後述「セキュリティに関する重要な注意」を参照)
- `MARKET_DATA_FILE_PATH` / `ORDER_REQUEST_FILE_PATH` / `ORDER_RESULT_FILE_PATH`:
  Windows環境では`%APPDATA%`から自動検出されるが、Linux上のPythonでは
  自動検出できないため、STEP 4でWineのプレフィックスパスを明示的に設定する
  (下記STEP 4末尾を参照)。

## STEP 3: Dashboard側の接続先を設定する

`dashboard/.env.local` を作成し、DashboardからブラウザがアクセスするVPSの
公開IP・ポートを設定する(ビルド前に設定すること。値はビルド時に埋め込まれる)。

```bash
cd /opt/artemis/mt5-ai-trader/dashboard
cat > .env.local <<'EOF'
VITE_SETTINGS_API_URL=http://<VPSの公開IP>:8787
VITE_SETTINGS_API_TOKEN=<STEP2で設定したSETTINGS_API_TOKENと同じ値>
EOF
npm run build
```

`.env.local`を作成・変更した後は、必ず`npm run build`をやり直すこと
(Viteの環境変数はビルド時に静的に埋め込まれるため、再ビルドしないと
反映されない)。STEP 5でsystemd化した後に変更した場合は
`sudo systemctl restart artemis-dashboard` も忘れずに。

## STEP 4: MT5をWineで動かす(価格取得・発注に必須)

Wineをインストールする。

```bash
sudo dpkg --add-architecture i386
sudo apt-get update
sudo apt-get install -y wine wine32:i386 winetricks
```

xrdpでVPSのデスクトップにログインし、ターミナルから以下を実行してMT5を
インストールする(ブローカーが配布しているMT5インストーラをあらかじめ
VPSへダウンロードしておく)。

```bash
wine ~/Downloads/xxxx5setup.exe
```

インストール後、Wineが作るWindows風フォルダ構成(`~/.wine/drive_c/...`)に
MT5がインストールされる。GUIが起動したら、通常のWindows手順と同様に:

1. デモ口座でログインする
2. `mt5_ai_trader/README.md` の「STEP 1: EAをMT5に配置する」〜
   「STEP 3: ファイルが書き出されているか確認する」と同じ手順で
   `ea/ARTEMIS_Bridge.mq5` をMetaEditor(Wine内)でコンパイルし、チャートに
   適用する(AlgoTrading有効化、InpSymbol/InpTimeframeを`.env`の
   SYMBOL/TIMEFRAMEと一致させる)

MT5(Wine)が書き出すCommon/Filesの実際のパスは、通常は次の場所になる。

```
~/.wine/drive_c/users/<VPSのLinuxユーザー名>/AppData/Roaming/MetaQuotes/Terminal/Common/Files/
```

Windows環境では`%APPDATA%`環境変数からPython側が自動検出するが、Linux上で
動くPython(venv)には`APPDATA`が存在しないため、`mt5_ai_trader/.env`に
このパスを明示的に設定する必要がある。

```bash
# mt5_ai_trader/.env に追記(<user>は実際のLinuxユーザー名に置き換える)
MARKET_DATA_FILE_PATH=/home/<user>/.wine/drive_c/users/<user>/AppData/Roaming/MetaQuotes/Terminal/Common/Files/artemis_market_data.json
ORDER_REQUEST_FILE_PATH=/home/<user>/.wine/drive_c/users/<user>/AppData/Roaming/MetaQuotes/Terminal/Common/Files/artemis_order_request.json
ORDER_RESULT_FILE_PATH=/home/<user>/.wine/drive_c/users/<user>/AppData/Roaming/MetaQuotes/Terminal/Common/Files/artemis_order_result.json
ACCOUNT_STATE_FILE_PATH=/home/<user>/.wine/drive_c/users/<user>/AppData/Roaming/MetaQuotes/Terminal/Common/Files/artemis_account_state.json
```

実際のパスは環境によって多少異なることがあるため、以下で実ファイルを
探してから正確なパスをコピーするのが確実。

```bash
find ~/.wine -iname "artemis_market_data.json" 2>/dev/null
```

**MT5(Wine)は常時ログイン状態で起動し続けている必要がある**(EAが継続的に
ファイルを書き出すため)。xrdpセッションを閉じてもプロセスは残ることが多いが、
再起動しても自動で立ち上がるようにするには次の「STEP 4.5」を参照。

### STEP 4.5: MT5(Wine)自体をVPS再起動後も自動起動させる(実験的)

Dashboard/settings_server.py/AIボットはsystemd化すればVPS再起動後も自動で
立ち上がるが、MT5自体(Wine上のGUIアプリ)は別扱いになる。以下のスクリプトは
画面を持たない仮想ディスプレイ(Xvfb)上でMT5をsystemdサービスとして起動する。

```bash
cd /opt/artemis/mt5-ai-trader
sudo bash scripts/install_mt5_service.sh
```

`terminal64.exe`のパスを自動検出して`artemis-xvfb.service` /
`artemis-mt5.service`の2つを登録・起動する(見つからない場合はパスを
引数で明示的に指定できる。スクリプト内のコメントを参照)。

**注意点(必ず読むこと)**

- MT5がログイン情報を保存していて、次回起動時に自動的に再ログインできる
  状態になっている必要がある(事前にxrdpのGUIから一度ログインし、
  「パスワードを保存する」を有効にしておくこと)
- Xvfbは新しい仮想ディスプレイのため、xrdp側で同じMT5を手動起動した状態と
  併用すると、同じターミナルデータフォルダへの二重起動でロックされ
  失敗することがある。自動起動を有効にしたら、xrdp側で同じMT5を
  同時に開かないこと
- Xvfbは画面出力を持たないため、xrdp越しにこの自動起動MT5の画面を直接見る
  ことはできない。動作確認は`journalctl -u artemis-mt5 -f`や、
  `artemis_market_data.json`等の更新日時で行う
- うまく動かない場合は無理をせず、「VPS再起動後に一度だけxrdpでログインして
  MT5を手動起動する」運用に切り替えてよい(Dashboard/settings_server/AIボット
  の自動起動には影響しない)

## STEP 5: systemdサービス化(自動起動)

STEP 1〜4が終わっていれば(特にDashboardの再ビルドが必要な場合は先に
`npm run build`を実行してから)、以下でDashboard・settings_server.py・
main.pyの3つをsystemdサービスとして登録・起動できる。

```bash
cd /opt/artemis/mt5-ai-trader
sudo bash scripts/setup_vps.sh --install-systemd
```

内部で `deploy/systemd/*.service` を実際のパス・実行ユーザーに置き換えて
`/etc/systemd/system/` に配置し、`systemctl enable --now` する。

状態確認:

```bash
systemctl status artemis-settings-server artemis-bot artemis-dashboard
journalctl -u artemis-bot -f          # AIボットのログをリアルタイム表示
journalctl -u artemis-settings-server -f
```

設定ファイル(`.env`やDashboardの`.env.local`)を変更した後は、該当サービスを
再起動する。

```bash
sudo systemctl restart artemis-settings-server
sudo systemctl restart artemis-bot
sudo systemctl restart artemis-dashboard   # dashboard/.env.local変更時はnpm run buildも先に
```

## STEP 6: ファイアウォール(ポート開放)

Hostinger側のファイアウォール/セキュリティグループと、VPS内の`ufw`の両方で
以下のポートを開ける必要がある。

```bash
sudo ufw allow 5173/tcp   # Dashboard
sudo ufw allow 8787/tcp   # settings_server.py(Bot API)
```

## セキュリティに関する重要な注意

`settings_server.py` は `ENABLE_ORDERS` / `DEMO_ONLY` を含む売買設定を
変更できるAPIである。VPSは公開IP(`76.13.180.239`など)を持つため、
**`SETTINGS_API_TOKEN` を設定しないまま8787番ポートをインターネットに
公開すると、誰でも売買設定を書き換えられる状態になる。** 必ず以下のいずれか
(できれば両方)を行うこと。

1. `mt5_ai_trader/.env` の `SETTINGS_API_TOKEN` に十分ランダムな値を設定し、
   `dashboard/.env.local` の `VITE_SETTINGS_API_TOKEN` にも同じ値を設定する
   (STEP 2・3を参照)
2. `ufw`やHostinger側のファイアウォールで、8787番ポートへのアクセスを
   自分のIPアドレスのみに制限する

```bash
# 例: 自分のIPからのみ8787番を許可する場合
sudo ufw allow from <自分のグローバルIP> to any port 8787 proto tcp
```

## STEP 7: 動作確認チェックリスト

- [ ] `http://<VPSの公開IP>:5173` でDashboardが表示される
- [ ] Dashboard Settings画面で「Bot APIに接続できません」が出ない
      (`curl http://127.0.0.1:8787/api/settings` がVPS内で200を返すか確認)
- [ ] Settings画面で値を変更→保存→`mt5_ai_trader/config.json`が更新される
      (`cat /opt/artemis/mt5-ai-trader/mt5_ai_trader/config.json`)
- [ ] `journalctl -u artemis-bot -f` にMT5からの価格データ取得・AI判断ログが
      流れている(MT5(Wine)側でEAが稼働している場合)
- [ ] DashboardのHome/Trade画面に、モックではなく実際の残高・保有ポジションが
      表示される(`curl http://127.0.0.1:8787/api/account` が200を返すか確認。
      503の場合はMT5/EA側がまだ`artemis_account_state.json`を書き出して
      いない)
- [ ] DashboardのHome/Trade画面にAI判断(BUY/SELL/WAIT)がリアルタイムで
      表示される(`curl http://127.0.0.1:8787/api/ai-status` が200を返すか
      確認。503の場合は`artemis-bot`サービスが動作していない)
- [ ] DashboardのTrade/Analytics画面に、モックではなく実際の取引履歴・
      勝率・プロフィットファクターが表示される(`curl http://127.0.0.1:8787/api/trade-history`
      が200を返すか確認。503の場合はEAが古い場合があるので、`ea/ARTEMIS_Bridge.mq5`
      をv4.00以降に再コンパイル・再適用したか確認する)
- [ ] DashboardのHome画面のSTOPボタンを押すと、`journalctl -u artemis-bot -f`に
      「BOT_RUN_STATE=STOPPED のため判断・発注をスキップします」というログが
      流れ、AI判断表示が「停止中です」になる。STARTを押すと数サイクル後に
      通常のAI判断ログに戻る
- [ ] VPS再起動後、`systemctl status artemis-settings-server artemis-bot artemis-dashboard`
      が3つとも `active (running)` になっている
- [ ] (MT5自動起動を設定した場合)VPS再起動後、`systemctl status artemis-xvfb artemis-mt5`
      も `active (running)` になっている

## トラブルシューティング

| 症状 | 対処 |
| --- | --- |
| `ModuleNotFoundError: No module named 'dotenv'` | システムのpythonで直接`python3 settings_server.py`を実行している。必ず`mt5_ai_trader/.venv/bin/python`(またはsystemdサービス経由)で実行する |
| `pip install`が`externally-managed-environment`で失敗 | `scripts/setup_vps.sh`を使うか、手動なら`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`のようにvenv内へインストールする |
| Dashboardが「Bot APIに接続できません」のまま | `systemctl status artemis-settings-server`で起動しているか確認。`dashboard/.env.local`のVITE_SETTINGS_API_URLがVPSの公開IPになっているか、8787番ポートがファイアウォールで開いているか確認 |
| `main.py`のログに`MARKET_DATA_MAX_STALENESS_SECONDS`超過の警告が出続ける | MT5(Wine)側のEAが稼働していない、またはMARKET_DATA_FILE_PATHがWineの実際のファイルパスと一致していない。`find ~/.wine -iname "artemis_market_data.json"`で実パスを確認して`.env`に設定し直す |
| systemdサービスが`activating (auto-restart)`を繰り返す | `journalctl -u <サービス名> -n 50`でエラー内容を確認。多くは`.env`の設定ミスかvenv/npm buildが未完了 |
| `/api/account`が503を返し続ける | `journalctl -u artemis-mt5 -f`(自動起動を使っている場合)またはxrdpのMT5画面でEAの「エキスパート」タブを確認。EAがまだ起動していないか、ACCOUNT_STATE_FILE_PATHが実際のファイルと一致していない可能性がある |
| `artemis-mt5.service`が起動直後に停止する | ほとんどの場合MT5が自動ログインできていない(パスワード保存が無効、または初回はxrdpでの手動ログインが必要)。一度xrdpでMT5を手動起動してログイン状態を保存してから再度試す |
