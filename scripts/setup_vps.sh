#!/usr/bin/env bash
# ARTEMIS VPS セットアップスクリプト(Ubuntu 24.04想定)。
#
# 何をするか:
#   1. mt5_ai_trader/.venv に venv を作成し、requirements.txt を venv内へ
#      インストールする(Ubuntu 24.04のPEP 668=externally-managed-environment
#      制限を回避するため、システムのpythonへは一切インストールしない)。
#   2. dashboard/ で npm install && npm run build を実行する。
#   3. mt5_ai_trader/.env が無ければ .env.example からコピーする(既存の
#      .envは絶対に上書きしない)。
#   4. deploy/systemd/*.service を実際のパス・実行ユーザーに合わせて
#      /etc/systemd/system/ へ配置し、systemctl daemon-reload する
#      (--install-systemd を付けた場合のみ。sudoが必要)。
#
# 使い方:
#   cd /opt/artemis/mt5-ai-trader   # このリポジトリのルート
#   bash scripts/setup_vps.sh                    # venv/npm buildのみ
#   sudo bash scripts/setup_vps.sh --install-systemd   # systemdサービスも登録
#
# 何度実行しても安全(冪等)。既存の.venv/.envは壊さない。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOT_DIR="$REPO_ROOT/mt5_ai_trader"
DASHBOARD_DIR="$REPO_ROOT/dashboard"
VENV_DIR="$BOT_DIR/.venv"
INSTALL_SYSTEMD=0

for arg in "$@"; do
  case "$arg" in
    --install-systemd) INSTALL_SYSTEMD=1 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

echo "== [1/4] Python venv (mt5_ai_trader/.venv) =="
if ! python3 -c "import venv" >/dev/null 2>&1; then
  echo "python3-venv が見つかりません。先に以下を実行してください:" >&2
  echo "  sudo apt-get update && sudo apt-get install -y python3-venv python3-pip" >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  echo "venvを作成しました: $VENV_DIR"
else
  echo "既存のvenvを使用します: $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -r "$BOT_DIR/requirements.txt"
echo "Python依存関係のインストールが完了しました。"

echo "== [2/4] .env の準備 =="
if [ ! -f "$BOT_DIR/.env" ]; then
  cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
  echo "mt5_ai_trader/.env を作成しました(.env.exampleの既定値のまま)。"
  echo "必要に応じて $BOT_DIR/.env を編集してください(SYMBOL/TIMEFRAME/MARKET_DATA_FILE_PATH等)。"
else
  echo "既存の mt5_ai_trader/.env をそのまま使用します(上書きしません)。"
fi

echo "== [3/4] Dashboard ビルド (npm install && npm run build) =="
if ! command -v npm >/dev/null 2>&1; then
  echo "npmが見つかりません。Node.js 20以上を先にインストールしてください。" >&2
  exit 1
fi
(cd "$DASHBOARD_DIR" && npm install && npm run build)
echo "dashboard/dist/ にビルド済み静的ファイルを出力しました。"

if [ "$INSTALL_SYSTEMD" -eq 1 ]; then
  echo "== [4/4] systemd サービス登録 =="
  if [ "$(id -u)" -ne 0 ]; then
    echo "--install-systemd には root 権限が必要です。'sudo bash scripts/setup_vps.sh --install-systemd' で実行してください。" >&2
    exit 1
  fi
  RUN_USER="${SUDO_USER:-$(id -un)}"
  NODE_BIN_DIR="$(dirname "$(command -v node)")"
  for unit in artemis-settings-server artemis-bot artemis-dashboard; do
    src="$REPO_ROOT/deploy/systemd/${unit}.service"
    dst="/etc/systemd/system/${unit}.service"
    sed \
      -e "s#__ARTEMIS_HOME__#${REPO_ROOT}#g" \
      -e "s#__ARTEMIS_USER__#${RUN_USER}#g" \
      -e "s#__NODE_BIN_DIR__#${NODE_BIN_DIR}#g" \
      "$src" > "$dst"
    echo "配置しました: $dst (実行ユーザー: $RUN_USER)"
  done
  systemctl daemon-reload
  systemctl enable --now artemis-settings-server.service
  systemctl enable --now artemis-bot.service
  systemctl enable --now artemis-dashboard.service
  echo "3つのsystemdサービスを有効化・起動しました。"
  echo "状態確認: systemctl status artemis-settings-server artemis-bot artemis-dashboard"
else
  echo "== [4/4] systemd サービス登録はスキップしました =="
  echo "自動起動を設定する場合は 'sudo bash scripts/setup_vps.sh --install-systemd' を実行してください。"
fi

echo ""
echo "セットアップ完了。"
echo "手動起動して動作確認する場合:"
echo "  $VENV_DIR/bin/python $BOT_DIR/settings_server.py"
echo "  $VENV_DIR/bin/python $BOT_DIR/main.py"
