"""パス設定とシミュレーター定数"""
from pathlib import Path

_BASE = Path(__file__).parent

# data.db: finance-system の DB（読み取り専用）
DATA_DB_PATH    = _BASE.parent / "finance-system" / "data.db"
WATCHLIST_PATH  = _BASE.parent / "finance-system" / "watchlist.json"

# simulator.db: シミュレーター専用 DB（書き込み可）
SIM_DB_PATH     = _BASE / "simulator.db"

# トレード設定
INITIAL_BALANCE  = 1000.0   # 初期資産（円）
LOT_SIZE         = 1000.0   # 1ロット = 1,000円
TAKE_PROFIT_RATE = 0.05     # 利益確定 +5%
STOP_LOSS_RATE   = -0.03    # 損切り   -3%
BUY_SIGNALS      = {"strong_buy", "buy"}
