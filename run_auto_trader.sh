#!/bin/bash
# 自動売買スクリプト（systemd タイマーから呼び出す）
# スケジュール: 平日 JST 9:00-15:45 を 15 分ごと（auto-trader.timer）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FINANCE_DIR="$(cd "$SCRIPT_DIR/../finance-system" 2>/dev/null && pwd)"
VENV_PYTHON="$HOME/finance-system/.venv/bin/python"
LOG_FILE="$SCRIPT_DIR/auto_trader.log"

# ── 市場時間チェック（JST 9:00-15:45、平日のみ）────────────────────
DOW=$(date +%u)       # 1=月 ... 7=日
TIME_NUM=$(date +%H%M | sed 's/^0*//')
TIME_NUM=${TIME_NUM:-0}
if [ "$DOW" -ge 6 ] || [ "$TIME_NUM" -lt 900 ] || [ "$TIME_NUM" -gt 1545 ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S JST') [skip] 市場時間外 (DOW=$DOW TIME=$TIME_NUM)" >> "$LOG_FILE"
  exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S JST') [start] 自動売買開始" >> "$LOG_FILE"

# ── data.db を finance-system から同期 ──────────────────────────────
if [ -n "$FINANCE_DIR" ] && [ -f "$FINANCE_DIR/data.db" ]; then
  cp "$FINANCE_DIR/data.db" "$SCRIPT_DIR/data.db"
  echo "$(date '+%Y-%m-%d %H:%M:%S JST') [info] data.db 同期完了: $FINANCE_DIR/data.db" >> "$LOG_FILE"
else
  echo "$(date '+%Y-%m-%d %H:%M:%S JST') [warn] finance-system/data.db が見つかりません" >> "$LOG_FILE"
fi

# ── auto_trader.py 実行 ─────────────────────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S JST') [error] Python 仮想環境が見つかりません: $VENV_PYTHON" >> "$LOG_FILE"
  exit 1
fi

cd "$SCRIPT_DIR"
"$VENV_PYTHON" "$SCRIPT_DIR/auto_trader.py" >> "$LOG_FILE" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S JST') [done] 自動売買完了" >> "$LOG_FILE"
