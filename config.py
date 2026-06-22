"""パス設定とシミュレーター定数"""
from pathlib import Path

_BASE = Path(__file__).parent

# data.db:
#   - GitHub Actions / Streamlit Cloud: リポジトリ内の data.db（ワークフローがコピー）
#   - ローカル開発: finance-system の data.db をフォールバック参照
_LOCAL_DATA_DB   = _BASE / "data.db"
_FINANCE_DATA_DB = _BASE.parent / "finance-system" / "data.db"
DATA_DB_PATH     = _LOCAL_DATA_DB if _LOCAL_DATA_DB.exists() else _FINANCE_DATA_DB

# watchlist.json:
#   - GitHub Actions / Streamlit Cloud: リポジトリ内の watchlist.json
#   - ローカル開発: finance-system の watchlist.json をフォールバック
_LOCAL_WATCHLIST   = _BASE / "watchlist.json"
_FINANCE_WATCHLIST = _BASE.parent / "finance-system" / "watchlist.json"
WATCHLIST_PATH     = _LOCAL_WATCHLIST if _LOCAL_WATCHLIST.exists() else _FINANCE_WATCHLIST

# simulator.db: シミュレーター専用 DB（書き込み可）
SIM_DB_PATH     = _BASE / "simulator.db"

# トレード設定
MANUAL_INITIAL_BALANCE  = 5000.0   # 手動口座 初期資産（円）
AUTO_INITIAL_BALANCE    = 5000.0   # 自動口座 初期資産（円）
AUTO_MAX_BUY_PER_TRADE  = 1000.0   # 自動売買 1回の購入上限（円）— 銘柄分散のため
LOT_SIZE         = 1000.0   # 1ロット = 1,000円
TAKE_PROFIT_RATE = 0.05     # 利益確定 +5%
STOP_LOSS_RATE   = -0.03    # 損切り   -3%
BUY_SIGNALS      = {"strong_buy", "buy"}

# GitHub リポジトリ情報（Streamlit Cloud での workflow dispatch 用）
GITHUB_REPO     = "oyasusan/stock-simulator"
GITHUB_WORKFLOW = "auto_trade.yml"
GITHUB_BRANCH   = "main"
