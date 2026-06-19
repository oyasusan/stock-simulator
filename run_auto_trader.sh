#!/bin/bash
# 自動売買スクリプト起動（monitor.py 実行後に呼び出す）
# 例: cron で "cd ~/finance-system && ./run.sh && ~/stock-simulator/run_auto_trader.sh"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$HOME/stock-simulator/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
  # finance-system の venv で代替
  VENV_PYTHON="$HOME/finance-system/.venv/bin/python"
fi

if [ ! -f "$VENV_PYTHON" ]; then
  echo "[auto_trader] Python 仮想環境が見つかりません"
  exit 1
fi

cd "$SCRIPT_DIR"
"$VENV_PYTHON" "$SCRIPT_DIR/auto_trader.py"
