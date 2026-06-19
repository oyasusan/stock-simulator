#!/bin/bash
# バーチャルトレード・シミュレーター 起動スクリプト
# SDカードはシンボリックリンク非対応のため ~/stock-simulator/.venv を使用
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$HOME/stock-simulator/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
  echo "仮想環境が見つかりません: $VENV_PYTHON"
  echo "以下を実行してセットアップしてください:"
  echo "  cd ~/stock-simulator && python3 -m venv .venv && .venv/bin/pip install -r '$SCRIPT_DIR/requirements.txt'"
  echo ""
  echo "または finance-system の venv を共用する場合:"
  echo "  ln -s ~/finance-system/.venv ~/stock-simulator/.venv"
  exit 1
fi

"$VENV_PYTHON" -m streamlit run "$SCRIPT_DIR/app.py" \
  --server.port 8502 \
  --server.address 0.0.0.0 \
  --server.headless true \
  "$@"
