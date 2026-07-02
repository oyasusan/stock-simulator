#!/usr/bin/env python3
"""
自動売買ロジック（単体スクリプト）

monitor.py の定期実行（15分ごと）後に呼び出す想定:
  python monitor.py --mode intraday && python auto_trader.py

data.db からシグナル・株価を読み込み（READ-ONLY）、
simulator.db の自動口座で売買を実行する。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DATA_DB_PATH, BUY_SIGNALS, TAKE_PROFIT_RATE, STOP_LOSS_RATE, LOT_SIZE, AUTO_MAX_BUY_PER_TRADE
from simulator_db import init_db, get_positions, get_wallet, execute_buy, execute_sell
from notifier import notify_trade


def load_latest_quotes() -> list[dict]:
    """data.db から各銘柄の最新クォートを READ-ONLY で取得"""
    if not DATA_DB_PATH.exists():
        print(f"[auto_trader] data.db が見つかりません: {DATA_DB_PATH}")
        return []
    conn = sqlite3.connect(f"file:{DATA_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT q.*
            FROM quotes q
            INNER JOIN (
                SELECT ticker, MAX(fetched_at) AS max_time
                FROM quotes GROUP BY ticker
            ) t ON q.ticker = t.ticker AND q.fetched_at = t.max_time
        """).fetchall()
    except sqlite3.OperationalError as e:
        print(f"[auto_trader] data.db に quotes テーブルが存在しません: {e}")
        conn.close()
        return []
    conn.close()
    return [dict(r) for r in rows]


def run():
    init_db()
    quotes = load_latest_quotes()
    if not quotes:
        return

    quote_map = {q["ticker"]: q for q in quotes}
    print(f"[auto_trader] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
          f"対象銘柄: {len(quotes)}")

    # ── 1. 既存ポジションの TP / SL チェック ─────────────────────────
    for pos in get_positions("auto"):
        q = quote_map.get(pos["ticker"])
        if not q or q.get("price") is None:
            continue
        current = q["price"]
        change  = (current - pos["buy_price"]) / pos["buy_price"]

        if change >= TAKE_PROFIT_RATE:
            pnl, msg = execute_sell("auto", pos["id"], current)
            print(f"  [利確] {pos['ticker']}  {change*100:+.1f}%  {msg}")
            new_balance = get_wallet("auto").get("balance")
            notify_trade("sell_tp", "auto", pos["ticker"], current, pos["qty"], pnl, new_balance)
        elif change <= STOP_LOSS_RATE:
            pnl, msg = execute_sell("auto", pos["id"], current)
            print(f"  [損切] {pos['ticker']}  {change*100:+.1f}%  {msg}")
            new_balance = get_wallet("auto").get("balance")
            notify_trade("sell_sl", "auto", pos["ticker"], current, pos["qty"], pnl, new_balance)

    # ── 2. 買いシグナルのエントリー ──────────────────────────────────
    # TP/SL 後の最新残高・保有銘柄を取得
    wallet       = get_wallet("auto")
    balance      = wallet.get("balance", 0.0)
    held_tickers = {p["ticker"] for p in get_positions("auto")}

    # strong_buy を先に処理する
    sorted_quotes = sorted(
        quotes,
        key=lambda q: 0 if q.get("signal") == "strong_buy" else 1,
    )
    for q in sorted_quotes:
        if q.get("signal") not in BUY_SIGNALS:
            continue
        ticker = q["ticker"]
        price  = q.get("price")
        if not price or ticker in held_tickers:
            continue

        max_qty = int(AUTO_MAX_BUY_PER_TRADE // LOT_SIZE)
        qty = min(int(balance // LOT_SIZE), max_qty)
        if qty < 1:
            print(f"  [残高不足] {ticker} スキップ  残高: ¥{balance:.0f}")
            break

        ok, msg = execute_buy("auto", ticker, price, qty)
        if ok:
            print(f"  [買い] {msg}")
            balance      -= qty * LOT_SIZE
            held_tickers.add(ticker)
            notify_trade("buy", "auto", ticker, price, qty, balance=balance)

    print("[auto_trader] 完了")


if __name__ == "__main__":
    run()
