"""Slack 通知（売買イベント用）"""
import json
import os
import urllib.request
import urllib.error

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

_ACTION_META = {
    "buy":         ("🛒", "買い"),
    "sell_tp":     ("✅", "利確"),
    "sell_sl":     ("🛑", "損切"),
    "sell_manual": ("💰", "手動売り"),
}


def _post(payload: dict) -> bool:
    if not WEBHOOK_URL:
        print("[notifier] SLACK_WEBHOOK_URL が未設定のため通知をスキップ")
        return False
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            WEBHOOK_URL, data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.URLError as e:
        print(f"[notifier] Slack 送信エラー: {e}")
        return False


def notify_trade(
    action: str,
    mode: str,
    ticker: str,
    price: float,
    qty: int,
    pnl: float | None = None,
    balance: float | None = None,
) -> None:
    """売買実行を Slack に通知する。

    action: "buy" | "sell_tp" | "sell_sl" | "sell_manual"
    mode:   "auto" | "manual"
    """
    emoji, label = _ACTION_META.get(action, ("📌", action))
    mode_label = "自動" if mode == "auto" else "手動"
    code = ticker.replace(".T", "")

    lines = [f"{emoji} *{mode_label}売買 — {label}*"]
    lines.append(f"銘柄: `{code}`　価格: *¥{price:,.1f}*　ロット: *{qty}*")
    if pnl is not None:
        sign = "+" if pnl >= 0 else ""
        lines.append(f"損益: *{sign}¥{pnl:,.0f}*")
    if balance is not None:
        lines.append(f"残高: ¥{balance:,.0f}")

    _post({"channel": "#trading", "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
    ]})
