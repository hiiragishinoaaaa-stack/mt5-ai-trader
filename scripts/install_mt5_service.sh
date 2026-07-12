#!/usr/bin/env bash
# ARTEMIS: MT5(Wine)をVPS再起動後も自動起動させるsystemdサービスを登録する。
#
# 前提:
#   - Wine上にMT5が既にインストール・デモ口座ログイン済みであること
#   - ログイン情報が保存されていて、次回起動時に自動的にログインできること
#     (MT5のログイン画面で「パスワードを保存する」が有効になっていること)
#   - ea/ARTEMIS_Bridge.mq5 がチャートに適用済みであること
#   (詳細は docs/VPS_DEPLOYMENT.md の STEP 4 を参照)
#
# 何をするか:
#   1. Xvfb(画面出力を持たない仮想ディスプレイ)をsystemdサービス化する
#   2. MT5をそのXvfb上でWine経由起動するsystemdサービスを登録する
#   これにより、xrdpでログインしていない(=誰もリモートデスクトップに
#   接続していない)状態でも、VPS再起動後にMT5が自動的に起動し続ける。
#
# 重要な注意:
#   - これはXvfbという「新しい」仮想ディスプレイでMT5を起動する。xrdp経由で
#     手動起動したMT5(既存のデスクトップ)とは別のプロセスになる。同じ
#     ターミナルのデータフォルダに対して2つのMT5インスタンスを同時に
#     起動しようとすると、ロックにより起動できないことがある。自動起動を
#     有効にしたら、xrdp側で同じMT5を手動起動しないこと。
#   - Xvfbは画面を描画しないため、xrdp越しにこのMT5の画面を直接見ることは
#     できない。動作確認はログ(journalctl)や、EAが書き出すJSONファイルの
#     更新日時で行う。
#   - この方式はWine+MT5の組み合わせに依存する実験的な構成。うまく動かない
#     場合は、無理せず「VPS再起動後に一度だけxrdpでログインしてMT5を手動起動
#     する」運用に切り替えること(Dashboard/settings_server/AIボットの
#     自動起動には影響しない)。
#
# 使い方:
#   sudo bash scripts/install_mt5_service.sh                          # 自動検出
#   sudo bash scripts/install_mt5_service.sh "/path/to/terminal64.exe" # 明示指定
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "root権限が必要です。'sudo bash scripts/install_mt5_service.sh' で実行してください。" >&2
  exit 1
fi

RUN_USER="${SUDO_USER:-}"
if [ -z "$RUN_USER" ]; then
  echo "実行ユーザーを特定できませんでした。'sudo bash scripts/install_mt5_service.sh' の形で(suではなく)実行してください。" >&2
  exit 1
fi
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
WINE_PREFIX="${WINEPREFIX:-$RUN_HOME/.wine}"

MT5_PATH="${1:-}"
if [ -z "$MT5_PATH" ]; then
  echo "terminal64.exeを自動検索しています ($WINE_PREFIX 以下)..."
  MT5_PATH=$(sudo -u "$RUN_USER" find "$WINE_PREFIX" -iname "terminal64.exe" 2>/dev/null | head -n1)
fi
if [ -z "$MT5_PATH" ] || [ ! -f "$MT5_PATH" ]; then
  echo "terminal64.exeが見つかりませんでした。MT5がインストールされているか確認するか、パスを明示的に指定してください:" >&2
  echo "  sudo bash scripts/install_mt5_service.sh '/home/xxx/.wine/drive_c/Program Files/XXX MT5/terminal64.exe'" >&2
  exit 1
fi

echo "実行ユーザー: $RUN_USER"
echo "WINEPREFIX:   $WINE_PREFIX"
echo "MT5パス:      $MT5_PATH"

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "Xvfbが見つかりません。先にインストールしてください: sudo apt-get install -y xvfb" >&2
  exit 1
fi
if ! command -v wine >/dev/null 2>&1; then
  echo "wineが見つかりません。先にインストールしてください(docs/VPS_DEPLOYMENT.md STEP 4参照)。" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sed \
  -e "s#__ARTEMIS_USER__#${RUN_USER}#g" \
  "$REPO_ROOT/deploy/systemd/artemis-xvfb.service" > /etc/systemd/system/artemis-xvfb.service

sed \
  -e "s#__ARTEMIS_USER__#${RUN_USER}#g" \
  -e "s#__WINE_PREFIX__#${WINE_PREFIX}#g" \
  -e "s#__MT5_TERMINAL_PATH__#${MT5_PATH}#g" \
  "$REPO_ROOT/deploy/systemd/artemis-mt5.service" > /etc/systemd/system/artemis-mt5.service

systemctl daemon-reload
systemctl enable --now artemis-xvfb.service
sleep 2
systemctl enable --now artemis-mt5.service

echo ""
echo "登録が完了しました。"
echo "状態確認:   systemctl status artemis-xvfb artemis-mt5"
echo "ログ確認:   journalctl -u artemis-mt5 -f"
echo ""
echo "MT5起動には数十秒かかることがある。artemis_market_data.json /"
echo "artemis_account_state.json の更新日時が進んでいくかで、EAが正常に"
echo "動いているか確認すること。"
