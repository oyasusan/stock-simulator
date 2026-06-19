"""バーチャルトレード・シミュレーター - Streamlit ダッシュボード"""
import json
import math
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

_JST = timezone(timedelta(hours=9))


def to_jst(ts: str) -> str:
    """UTC の ISO タイムスタンプ文字列を JST 表示文字列に変換する。
    タイムゾーン情報がない場合は UTC として扱う。
    """
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return ts

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    DATA_DB_PATH, WATCHLIST_PATH, LOT_SIZE, TAKE_PROFIT_RATE, STOP_LOSS_RATE,
    GITHUB_REPO, GITHUB_WORKFLOW, GITHUB_BRANCH,
)
from simulator_db import (
    init_db, get_wallet, get_positions, get_trade_history, get_wallet_history,
    execute_buy, execute_sell, reset_account,
)

# ── ページ設定 ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="バーチャルトレード",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container { padding: 3rem 0.5rem 2rem; }
[data-testid="stMetricValue"] { font-size: 1.1rem; }
[data-testid="stMetricDelta"] { font-size: 0.8rem; }
thead tr th { background: #1e1e2e !important; }
.stButton > button {
    width: 100%;
    border-radius: 8px;
    font-weight: bold;
}
.buy-btn  > button { background-color: #e74c3c; color: white; border: none; }
.sell-btn > button { background-color: #3498db; color: white; border: none; }
</style>
""", unsafe_allow_html=True)

# ── 初期化 ────────────────────────────────────────────────────────────
init_db()

# ── GitHub workflow dispatch（手動売買の永続化）──────────────────────

def _github_token() -> str:
    """Streamlit secrets から GitHub トークンを取得"""
    try:
        return st.secrets.get("GITHUB_TOKEN", "")
    except Exception:
        return ""


def dispatch_trade(mode: str, ticker: str = "", qty: int = 1, position_id: int = 0) -> bool:
    """GitHub Actions workflow_dispatch で手動売買を予約する。

    Streamlit secrets に GITHUB_TOKEN（workflow スコープ必須）が必要。
    約60-120秒後にトレードが実行され simulator.db がコミットされる。
    """
    import json as _json
    token = _github_token()
    if not token:
        return False

    url = (
        f"https://api.github.com/repos/{GITHUB_REPO}"
        f"/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    )
    payload = _json.dumps({
        "ref": GITHUB_BRANCH,
        "inputs": {
            "mode":        mode,
            "ticker":      ticker,
            "qty":         str(qty),
            "position_id": str(position_id),
        },
    }).encode()

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Authorization":        f"Bearer {token}",
            "Accept":               "application/vnd.github+json",
            "Content-Type":         "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 204
    except urllib.error.HTTPError as e:
        st.error(f"GitHub API エラー: HTTP {e.code} — トークンの権限を確認してください")
        return False


def _has_github_token() -> bool:
    return bool(_github_token())


# ── データ読み込み（data.db は READ-ONLY）────────────────────────────

def _resolve_data_db() -> Path:
    """data.db のパスを実行時に解決する（モジュール読み込み時の評価に依存しない）"""
    base = Path(__file__).parent
    local = base / "data.db"
    if local.exists():
        return local
    fallback = base.parent / "finance-system" / "data.db"
    return fallback


def _resolve_watchlist() -> Path:
    base = Path(__file__).parent
    local = base / "watchlist.json"
    if local.exists():
        return local
    return base.parent / "finance-system" / "watchlist.json"


@st.cache_data(ttl=60)
def load_watchlist() -> dict:
    path = _resolve_watchlist()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {i["ticker"]: i for i in cfg["watchlist"]}


@st.cache_data(ttl=60)
def load_latest_quotes() -> pd.DataFrame:
    db = _resolve_data_db()
    if not db.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(db))
    df = pd.read_sql("""
        SELECT q.*
        FROM quotes q
        INNER JOIN (
            SELECT ticker, MAX(fetched_at) AS max_time
            FROM quotes GROUP BY ticker
        ) t ON q.ticker = t.ticker AND q.fetched_at = t.max_time
        ORDER BY q.ticker
    """, conn)
    conn.close()
    return df


def signal_label(s: str | None) -> str:
    return {
        "strong_buy":  "★ 強買",
        "buy":         "▲ 買い",
        "watch":       "● 中立",
        "sell":        "▼ 売り",
        "strong_sell": "▽ 強売",
    }.get(s or "", "-")


def signal_color(s: str | None) -> str:
    return {
        "strong_buy":  "🟢",
        "buy":         "🔼",
        "watch":       "⬜",
        "sell":        "🔽",
        "strong_sell": "🔴",
    }.get(s or "", "")


def fmt_pnl(v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"¥{v:+,.0f}"


def calc_unrealized(pos: dict, quote_map: dict) -> float | None:
    q = quote_map.get(pos["ticker"])
    if not q or q.get("price") is None:
        return None
    cost = pos["qty"] * LOT_SIZE
    proceeds = cost * (q["price"] / pos["buy_price"])
    return proceeds - cost


# ── ウォレットサマリー ────────────────────────────────────────────────

def render_wallet_summary(quote_map: dict):
    m_wallet = get_wallet("manual")
    a_wallet = get_wallet("auto")
    m_positions = get_positions("manual")
    a_positions = get_positions("auto")

    m_unrealized = sum(
        u for p in m_positions
        if (u := calc_unrealized(p, quote_map)) is not None
    )
    a_unrealized = sum(
        u for p in a_positions
        if (u := calc_unrealized(p, quote_map)) is not None
    )

    m_total = m_wallet["balance"] + sum(p["qty"] * LOT_SIZE for p in m_positions)
    a_total = a_wallet["balance"] + sum(p["qty"] * LOT_SIZE for p in a_positions)
    from config import INITIAL_BALANCE
    m_pnl = m_total + m_unrealized - INITIAL_BALANCE
    a_pnl = a_total + a_unrealized - INITIAL_BALANCE

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("手動 残高", f"¥{m_wallet['balance']:,.0f}",
              delta=f"含み損益 ¥{m_unrealized:+,.0f}" if m_positions else None)
    c2.metric("自動 残高", f"¥{a_wallet['balance']:,.0f}",
              delta=f"含み損益 ¥{a_unrealized:+,.0f}" if a_positions else None)
    c3.metric("手動 総損益", fmt_pnl(m_pnl),
              delta=f"ポジ {len(m_positions)}件" if m_positions else None)
    c4.metric("自動 総損益", fmt_pnl(a_pnl),
              delta=f"ポジ {len(a_positions)}件" if a_positions else None)


# ── Tab1: ダッシュボード ──────────────────────────────────────────────

def render_dashboard(quote_map: dict):
    st.subheader("資産推移")
    days = st.slider("表示期間（日）", 1, 30, 7, key="dash_days")

    m_hist = get_wallet_history("manual", days=days)
    a_hist = get_wallet_history("auto",   days=days)

    if not m_hist and not a_hist:
        st.info("取引履歴がまだありません。手動で売買するか、自動売買を実行してください。")
        return

    def _to_jst_series(series: pd.Series) -> pd.Series:
        return pd.to_datetime(series, utc=True).dt.tz_convert(_JST)

    fig = go.Figure()
    if m_hist:
        m_df = pd.DataFrame(m_hist)
        fig.add_trace(go.Scatter(
            x=_to_jst_series(m_df["recorded_at"]), y=m_df["balance"],
            name="手動口座", line=dict(color="#e74c3c", width=2),
        ))
    if a_hist:
        a_df = pd.DataFrame(a_hist)
        fig.add_trace(go.Scatter(
            x=_to_jst_series(a_df["recorded_at"]), y=a_df["balance"],
            name="自動口座", line=dict(color="#3498db", width=2),
        ))

    from config import INITIAL_BALANCE
    fig.add_hline(
        y=INITIAL_BALANCE,
        line_dash="dash", line_color="rgba(255,255,255,0.3)",
        annotation_text=f"初期 ¥{INITIAL_BALANCE:.0f}",
    )
    fig.update_layout(
        paper_bgcolor="#1a1a2e", plot_bgcolor="#0f0f1e",
        font=dict(color="#cccccc"),
        legend=dict(orientation="h", y=1.05),
        height=320,
        margin=dict(l=40, r=20, t=40, b=30),
        yaxis=dict(tickprefix="¥", tickformat=",.0f"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 自動売買のルール説明
    st.markdown(
        f"> **自動売買ルール**: 買い/強買シグナル点灯 → 全額買い  |  "
        f"+{TAKE_PROFIT_RATE*100:.0f}% で利確  |  "
        f"{STOP_LOSS_RATE*100:.0f}% で損切り"
    )


# ── Tab2: 手動トレード ────────────────────────────────────────────────

def render_manual_trade(df_quotes: pd.DataFrame, watchlist: dict):
    wallet = get_wallet("manual")
    balance = wallet["balance"]
    positions = get_positions("manual")
    held = {p["ticker"]: p for p in positions}

    has_token = _has_github_token()

    # Streamlit Cloud では workflow dispatch 経由でトレード実行
    # ローカル開発では直接 DB に書き込む
    is_cloud = has_token

    st.subheader(f"手動口座  残高: ¥{balance:,.0f}")

    if not has_token:
        st.info(
            "**ローカルモード**: トレードは即時実行されます。\n\n"
            "Streamlit Cloud で利用する場合は Secrets に `GITHUB_TOKEN` を設定してください。"
        )
    else:
        st.caption("注文は GitHub Actions 経由で実行されます（反映まで約1〜2分）")

    if df_quotes.empty:
        st.warning("株価データがありません。")
        return

    # 銘柄セレクター
    ticker_opts = {
        f"{watchlist.get(t, {}).get('name', t)} ({t.replace('.T','')})": t
        for t in df_quotes["ticker"].tolist()
    }
    sel_label  = st.selectbox("銘柄を選択", list(ticker_opts.keys()), key="manual_ticker")
    sel_ticker = ticker_opts[sel_label]

    row = df_quotes[df_quotes["ticker"] == sel_ticker].iloc[0]
    price  = row["price"]
    signal = row.get("signal")

    # 銘柄情報
    info_c1, info_c2, info_c3 = st.columns(3)
    info_c1.metric("現在値", f"¥{price:,.1f}",
                   delta=f"{row['change_pct']:+.2f}%" if pd.notna(row.get("change_pct")) else None)
    info_c2.metric("シグナル", signal_color(signal) + " " + signal_label(signal))
    rsi_v = row.get("rsi")
    info_c3.metric("RSI", f"{rsi_v:.0f}" if pd.notna(rsi_v) else "-")

    st.markdown("---")

    max_qty = int(balance // LOT_SIZE)
    col_buy, col_sell = st.columns(2)

    # ── 買い注文 ───────────────────────────────────────────────────────
    with col_buy:
        st.markdown("#### 買い注文")
        qty_buy = st.number_input(
            "ロット数（1ロット=¥1,000）", min_value=1,
            max_value=max(1, max_qty), value=1,
            step=1, key="buy_qty",
        )
        cost = qty_buy * LOT_SIZE
        st.caption(f"コスト: ¥{cost:,.0f}  /  残高: ¥{balance:,.0f}")

        if st.button(f"🔴 買い {sel_ticker.replace('.T','')}", key="btn_buy",
                     disabled=(max_qty < 1)):
            if is_cloud:
                ok = dispatch_trade("manual_buy", ticker=sel_ticker, qty=qty_buy)
                if ok:
                    st.success(
                        f"注文受付: {sel_ticker} {qty_buy}ロット — "
                        "約1〜2分後に GitHub Actions が実行します。"
                        "反映後にページを更新してください。"
                    )
                # エラーは dispatch_trade 内で表示済み
            else:
                ok, msg = execute_buy("manual", sel_ticker, price, qty_buy)
                if ok:
                    st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(msg)

    # ── 売り注文 ───────────────────────────────────────────────────────
    with col_sell:
        st.markdown("#### 売り注文")
        if sel_ticker in held:
            pos = held[sel_ticker]
            unrealized = calc_unrealized(pos, {sel_ticker: {"price": price}})
            change_pct = (price - pos["buy_price"]) / pos["buy_price"] * 100
            st.caption(
                f"保有: {pos['qty']}ロット @ ¥{pos['buy_price']:,.1f}\n"
                f"含み損益: {fmt_pnl(unrealized)}  ({change_pct:+.1f}%)"
            )
            if st.button(f"🔵 売り {sel_ticker.replace('.T','')}", key="btn_sell"):
                if is_cloud:
                    ok = dispatch_trade("manual_sell", position_id=pos["id"])
                    if ok:
                        st.success(
                            f"売り注文受付: {sel_ticker} — "
                            "約1〜2分後に GitHub Actions が実行します。"
                        )
                else:
                    pnl, msg = execute_sell("manual", pos["id"], price)
                    if pnl is not None:
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.caption("この銘柄は保有していません")
            st.button("🔵 売り（保有なし）", key="btn_sell_na", disabled=True)


# ── Tab3: 保有銘柄 ────────────────────────────────────────────────────

def render_positions(quote_map: dict, watchlist: dict):
    for mode, label in [("manual", "手動"), ("auto", "自動")]:
        positions = get_positions(mode)
        wallet = get_wallet(mode)
        st.subheader(f"{label}口座  保有銘柄  (残高: ¥{wallet['balance']:,.0f})")

        if not positions:
            st.info(f"{label}口座に保有銘柄はありません。")
            continue

        rows = []
        for p in positions:
            q = quote_map.get(p["ticker"], {})
            current = q.get("price")
            cost = p["qty"] * LOT_SIZE
            if current:
                unrealized = cost * (current / p["buy_price"]) - cost
                change_pct = (current - p["buy_price"]) / p["buy_price"] * 100
                tp_price   = p["buy_price"] * (1 + abs(TAKE_PROFIT_RATE))
                sl_price   = p["buy_price"] * (1 + STOP_LOSS_RATE)
            else:
                unrealized = None
                change_pct = None
                tp_price = sl_price = None

            rows.append({
                "銘柄":       watchlist.get(p["ticker"], {}).get("name", p["ticker"]),
                "コード":     p["ticker"].replace(".T", ""),
                "取得価格":   f"¥{p['buy_price']:,.1f}",
                "現在値":     f"¥{current:,.1f}" if current else "-",
                "数量(ロット)": p["qty"],
                "コスト":     f"¥{cost:,.0f}",
                "含み損益":   fmt_pnl(unrealized),
                "損益率":     f"{change_pct:+.1f}%" if change_pct is not None else "-",
                "利確目標":   f"¥{tp_price:,.1f}" if tp_price else "-",
                "損切ライン": f"¥{sl_price:,.1f}" if sl_price else "-",
                "取得日時":   to_jst(p["bought_at"]),
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # 手動口座のみ: 個別売却ボタン
        if mode == "manual":
            st.markdown("**手動売却**")
            is_cloud = _has_github_token()
            for p in positions:
                q = quote_map.get(p["ticker"], {})
                current = q.get("price")
                name = watchlist.get(p["ticker"], {}).get("name", p["ticker"])
                btn_label = f"売却: {name}  @ ¥{current:,.1f}" if current else f"売却: {name}（価格取得不可）"
                if st.button(btn_label, key=f"sell_pos_{p['id']}", disabled=not current):
                    if is_cloud:
                        ok = dispatch_trade("manual_sell", position_id=p["id"])
                        if ok:
                            st.success(f"売り注文受付: {name} — 約1〜2分後に実行されます")
                    else:
                        pnl, msg = execute_sell("manual", p["id"], current)
                        if pnl is not None:
                            st.success(msg)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(msg)


# ── Tab4: 取引履歴 ────────────────────────────────────────────────────

def render_history(watchlist: dict):
    mode_sel = st.radio("口座", ["全て", "手動", "自動"], horizontal=True, key="hist_mode")
    mode_map = {"全て": None, "手動": "manual", "自動": "auto"}
    trades = get_trade_history(mode=mode_map[mode_sel], limit=200)

    if not trades:
        st.info("取引履歴がありません。")
        return

    rows = []
    for t in trades:
        rows.append({
            "日時":   to_jst(t["traded_at"]),
            "口座":   "手動" if t["mode"] == "manual" else "自動",
            "銘柄":   watchlist.get(t["ticker"], {}).get("name", t["ticker"]),
            "コード": t["ticker"].replace(".T", ""),
            "売買":   "🔴 買" if t["action"] == "buy" else "🔵 売",
            "価格":   f"¥{t['price']:,.1f}",
            "数量(ロット)": t["qty"],
            "金額":   f"¥{t['qty'] * LOT_SIZE:,.0f}",
            "損益":   fmt_pnl(t["pnl"]),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=500)

    # 集計
    sell_trades = [t for t in trades if t["action"] == "sell" and t["pnl"] is not None]
    if sell_trades:
        total_pnl = sum(t["pnl"] for t in sell_trades)
        wins = sum(1 for t in sell_trades if t["pnl"] > 0)
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("確定損益合計", fmt_pnl(total_pnl))
        c2.metric("勝率",
                  f"{wins/len(sell_trades)*100:.0f}%" if sell_trades else "-",
                  delta=f"{wins}勝 {len(sell_trades)-wins}敗")
        c3.metric("取引回数", f"{len(sell_trades)}回")


# ── メイン ────────────────────────────────────────────────────────────

st.title("🎯 バーチャルトレード・シミュレーター")

watchlist  = load_watchlist()
df_quotes  = load_latest_quotes()

if not df_quotes.empty:
    last_update = to_jst(df_quotes["fetched_at"].max())
    st.caption(f"株価最終更新: {last_update}  （15分ごと自動更新）")

quote_map = (
    df_quotes.set_index("ticker")[["price", "signal", "change_pct", "rsi"]]
    .to_dict(orient="index")
    if not df_quotes.empty else {}
)

# ウォレットサマリー（常時表示）
render_wallet_summary(quote_map)

st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["📊 ダッシュボード", "✋ 手動トレード", "📂 保有銘柄", "📋 取引履歴"])

with tab1:
    render_dashboard(quote_map)

with tab2:
    if df_quotes.empty:
        st.warning("data.db にデータがありません。monitor.py を実行してください。")
    else:
        render_manual_trade(df_quotes, watchlist)

with tab3:
    render_positions(quote_map, watchlist)

with tab4:
    render_history(watchlist)

# ── サイドバー: アカウントリセット ────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 設定")
    st.markdown("---")
    st.markdown("**アカウントリセット**")
    st.warning("リセットすると全ポジション・履歴が削除されます。")
    if st.button("手動口座をリセット", key="reset_manual"):
        reset_account("manual")
        st.cache_data.clear()
        st.success("手動口座をリセットしました")
        st.rerun()
    if st.button("自動口座をリセット", key="reset_auto"):
        reset_account("auto")
        st.cache_data.clear()
        st.success("自動口座をリセットしました")
        st.rerun()
    st.markdown("---")
    st.markdown("**自動売買ルール**")
    st.markdown(
        f"- 買い: 強買/買いシグナル\n"
        f"- 利確: +{TAKE_PROFIT_RATE*100:.0f}%\n"
        f"- 損切: {STOP_LOSS_RATE*100:.0f}%\n"
        f"- 単位: ¥{LOT_SIZE:,.0f}/ロット"
    )
