#!/usr/bin/env python3
"""
手動売買 CLI スクリプト（GitHub Actions の workflow_dispatch から呼び出される）

使い方:
  python manual_trade.py buy 4385.T 2    # 4385.T を 2ロット買い
  python manual_trade.py sell 3          # position_id=3 のポジションを売り
"""
import sys
import sqlite3
from pathlib import Path

from config import DATA_DB_PATH
from simulator_db import init_db, get_positions, get_wallet, execute_buy, execute_sell
from notifier import notify_trade


def get_current_price(ticker: str) -> float | None:
    """data.db から最新株価を取得"""
    if not DATA_DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{DATA_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT price FROM quotes
        WHERE ticker = ?
        ORDER BY fetched_at DESC
        LIMIT 1
    """, (ticker,)).fetchone()
    conn.close()
    return row["price"] if row else None


def cmd_buy(ticker: str, qty: int):
    if not ticker.endswith(".T"):
        ticker += ".T"
    price = get_current_price(ticker)
    if price is None:
        print(f"[manual_trade] {ticker} の株価が取得できません", file=sys.stderr)
        sys.exit(1)
    init_db()
    ok, msg = execute_buy("manual", ticker, price, qty)
    print(f"[manual_trade] {msg}")
    if not ok:
        sys.exit(1)
    new_balance = get_wallet("manual").get("balance")
    notify_trade("buy", "manual", ticker, price, qty, balance=new_balance)


def cmd_sell(position_id: int):
    init_db()
    positions = get_positions("manual")
    pos = next((p for p in positions if p["id"] == position_id), None)
    if not pos:
        print(f"[manual_trade] position_id={position_id} が見つかりません", file=sys.stderr)
        print("  現在の保有:", [(p["id"], p["ticker"]) for p in positions])
        sys.exit(1)
    price = get_current_price(pos["ticker"])
    if price is None:
        print(f"[manual_trade] {pos['ticker']} の株価が取得できません", file=sys.stderr)
        sys.exit(1)
    pnl, msg = execute_sell("manual", position_id, price)
    print(f"[manual_trade] {msg}")
    if pnl is None:
        sys.exit(1)
    new_balance = get_wallet("manual").get("balance")
    notify_trade("sell_manual", "manual", pos["ticker"], price, pos["qty"], pnl, new_balance)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "buy":
        if len(sys.argv) < 4:
            print("使い方: manual_trade.py buy <ticker> <qty>", file=sys.stderr)
            sys.exit(1)
        ticker = sys.argv[2]
        qty    = int(sys.argv[3])
        if qty < 1:
            print(f"qty は 1 以上にしてください: {qty}", file=sys.stderr)
            sys.exit(1)
        cmd_buy(ticker, qty)

    elif action == "sell":
        if len(sys.argv) < 3:
            print("使い方: manual_trade.py sell <position_id>", file=sys.stderr)
            sys.exit(1)
        position_id = int(sys.argv[2])
        cmd_sell(position_id)

    else:
        print(f"不明なアクション: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
