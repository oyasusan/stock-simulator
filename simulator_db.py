"""simulator.db の初期化・接続・CRUD モジュール"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import SIM_DB_PATH, INITIAL_BALANCE, LOT_SIZE


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SIM_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_DDL = [
    """CREATE TABLE IF NOT EXISTS wallets (
        id         INTEGER PRIMARY KEY,
        mode       TEXT    NOT NULL UNIQUE,
        balance    REAL    NOT NULL DEFAULT 1000.0,
        updated_at TEXT    NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS positions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        mode       TEXT    NOT NULL,
        ticker     TEXT    NOT NULL,
        buy_price  REAL    NOT NULL,
        qty        INTEGER NOT NULL,
        bought_at  TEXT    NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS trade_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        mode       TEXT    NOT NULL,
        ticker     TEXT    NOT NULL,
        action     TEXT    NOT NULL,
        price      REAL    NOT NULL,
        qty        INTEGER NOT NULL,
        pnl        REAL,
        traded_at  TEXT    NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS wallet_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        mode        TEXT    NOT NULL,
        balance     REAL    NOT NULL,
        recorded_at TEXT    NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pos_mode   ON positions(mode)",
    "CREATE INDEX IF NOT EXISTS idx_trade_mode ON trade_history(mode, traded_at)",
    "CREATE INDEX IF NOT EXISTS idx_wh_mode    ON wallet_history(mode, recorded_at)",
]


def init_db():
    """テーブル作成と初期ウォレット挿入（冪等）"""
    conn = _conn()
    try:
        for ddl in _DDL:
            conn.execute(ddl)
        conn.commit()
        now = _now()
        conn.execute(
            "INSERT OR IGNORE INTO wallets (id, mode, balance, updated_at) VALUES (1, 'manual', ?, ?)",
            (INITIAL_BALANCE, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO wallets (id, mode, balance, updated_at) VALUES (2, 'auto', ?, ?)",
            (INITIAL_BALANCE, now),
        )
        # 初期残高を wallet_history に記録（初回のみ）
        for mode in ("manual", "auto"):
            cnt = conn.execute(
                "SELECT COUNT(*) FROM wallet_history WHERE mode = ?", (mode,)
            ).fetchone()[0]
            if cnt == 0:
                conn.execute(
                    "INSERT INTO wallet_history (mode, balance, recorded_at) VALUES (?,?,?)",
                    (mode, INITIAL_BALANCE, now),
                )
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    """UTC タイムスタンプを返す（表示時に JST 変換）"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ── 読み取り ─────────────────────────────────────────────────────────

def get_wallet(mode: str) -> dict:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM wallets WHERE mode = ?", (mode,)).fetchone()
    return dict(row) if row else {"mode": mode, "balance": INITIAL_BALANCE}


def get_positions(mode: str) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE mode = ? ORDER BY bought_at DESC", (mode,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_trade_history(mode: str | None = None, limit: int = 200) -> list[dict]:
    init_db()
    with _conn() as conn:
        if mode:
            rows = conn.execute(
                "SELECT * FROM trade_history WHERE mode = ? ORDER BY traded_at DESC LIMIT ?",
                (mode, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_history ORDER BY traded_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_wallet_history(mode: str, days: int = 30) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM wallet_history
               WHERE mode = ?
                 AND recorded_at >= datetime('now', ?)
               ORDER BY recorded_at ASC""",
            (mode, f"-{days} days"),
        ).fetchall()
    return [dict(r) for r in rows]


# ── 書き込み ─────────────────────────────────────────────────────────

def execute_buy(mode: str, ticker: str, price: float, qty: int) -> tuple[bool, str]:
    """qty ロット（1ロット=¥1,000）分の買い注文を実行する。
    戻り値: (成功フラグ, メッセージ)
    """
    cost = qty * LOT_SIZE
    init_db()
    with _conn() as conn:
        wallet = conn.execute(
            "SELECT balance FROM wallets WHERE mode = ?", (mode,)
        ).fetchone()
        if not wallet or wallet["balance"] < cost:
            bal = wallet["balance"] if wallet else 0
            return False, f"残高不足 (残高 ¥{bal:.0f} < コスト ¥{cost:.0f})"
        now = _now()
        conn.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE mode = ?",
            (cost, now, mode),
        )
        conn.execute(
            "INSERT INTO positions (mode, ticker, buy_price, qty, bought_at) VALUES (?,?,?,?,?)",
            (mode, ticker, price, qty, now),
        )
        conn.execute(
            "INSERT INTO trade_history (mode, ticker, action, price, qty, pnl, traded_at) "
            "VALUES (?,?,'buy',?,?,NULL,?)",
            (mode, ticker, price, qty, now),
        )
        new_balance = wallet["balance"] - cost
        conn.execute(
            "INSERT INTO wallet_history (mode, balance, recorded_at) VALUES (?,?,?)",
            (mode, new_balance, now),
        )
    return True, f"買い成功: {ticker} {qty}ロット @ ¥{price:.1f}  コスト ¥{cost:.0f}"


def execute_sell(mode: str, position_id: int, current_price: float) -> tuple[float | None, str]:
    """指定ポジションを売却し (損益, メッセージ) を返す"""
    init_db()
    with _conn() as conn:
        pos = conn.execute(
            "SELECT * FROM positions WHERE id = ? AND mode = ?", (position_id, mode)
        ).fetchone()
        if not pos:
            return None, "ポジションが見つかりません"
        pos = dict(pos)
        cost     = pos["qty"] * LOT_SIZE
        proceeds = cost * (current_price / pos["buy_price"])
        pnl      = proceeds - cost
        now      = _now()
        conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        conn.execute(
            "UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE mode = ?",
            (proceeds, now, mode),
        )
        conn.execute(
            "INSERT INTO trade_history (mode, ticker, action, price, qty, pnl, traded_at) "
            "VALUES (?,?,'sell',?,?,?,?)",
            (mode, pos["ticker"], current_price, pos["qty"], pnl, now),
        )
        wallet = conn.execute(
            "SELECT balance FROM wallets WHERE mode = ?", (mode,)
        ).fetchone()
        conn.execute(
            "INSERT INTO wallet_history (mode, balance, recorded_at) VALUES (?,?,?)",
            (mode, wallet["balance"], now),
        )
    return pnl, f"売り成功: {pos['ticker']}  損益 ¥{pnl:+.0f}"


def reset_account(mode: str):
    """指定モードのアカウントを初期状態にリセット"""
    init_db()
    now = _now()
    with _conn() as conn:
        conn.execute("DELETE FROM positions    WHERE mode = ?", (mode,))
        conn.execute("DELETE FROM trade_history WHERE mode = ?", (mode,))
        conn.execute("DELETE FROM wallet_history WHERE mode = ?", (mode,))
        conn.execute(
            "UPDATE wallets SET balance = ?, updated_at = ? WHERE mode = ?",
            (INITIAL_BALANCE, now, mode),
        )
        conn.execute(
            "INSERT INTO wallet_history (mode, balance, recorded_at) VALUES (?,?,?)",
            (mode, INITIAL_BALANCE, now),
        )
