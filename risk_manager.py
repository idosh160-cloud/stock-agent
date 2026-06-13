"""
risk_manager.py — שומר סף לכל החלטת מסחר
קרקן הוא מקור האמת. כל עסקה עוברת דרך כאן לפני ביצוע.
"""
import os
import json
import logging
from datetime import datetime, date

DIR = os.path.dirname(os.path.abspath(__file__))
DRAWDOWN_FILE = os.path.join(DIR, "daily_drawdown.json")

# ── חוקים קשיחים ────────────────────────────────────────────────────────────
MAX_PORTFOLIO_RISK_PCT = 0.20   # לא יותר מ-20% מהתיק בסיכון בו-זמנית
MAX_SINGLE_ASSET_PCT   = 0.25   # לא יותר מ-25% מהתיק בנכס אחד
MAX_DAILY_DRAWDOWN_PCT = 0.10   # kill-switch: עצור הכל אם ירדנו 10% ביום
MIN_FREE_MARGIN_USD    = 30     # תמיד שמור $30 מרג'ין פנוי כרזרבה


def _load_drawdown() -> dict:
    today = date.today().isoformat()
    if os.path.exists(DRAWDOWN_FILE):
        try:
            with open(DRAWDOWN_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data
        except Exception:
            pass
    return {"date": today, "start_portfolio": None, "lowest_portfolio": None}


def _save_drawdown(data: dict):
    with open(DRAWDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def update_drawdown(portfolio_usd: float):
    """מעדכן את ה-drawdown היומי. קורא לזה בכל ריצה."""
    data = _load_drawdown()
    if data["start_portfolio"] is None:
        data["start_portfolio"] = portfolio_usd
    if data["lowest_portfolio"] is None or portfolio_usd < data["lowest_portfolio"]:
        data["lowest_portfolio"] = portfolio_usd
    _save_drawdown(data)


def is_kill_switch_active(portfolio_usd: float) -> bool:
    """האם הגענו ל-drawdown יומי מקסימלי? אם כן — עצור הכל."""
    data = _load_drawdown()
    start = data.get("start_portfolio")
    if not start:
        return False
    drawdown_pct = (start - portfolio_usd) / start
    if drawdown_pct >= MAX_DAILY_DRAWDOWN_PCT:
        logging.warning(f"[RiskManager] KILL SWITCH — drawdown {drawdown_pct:.1%} >= {MAX_DAILY_DRAWDOWN_PCT:.1%}")
        return True
    return False


def get_portfolio_exposure(open_trades: list, portfolio_usd: float) -> dict:
    """
    מחשב חשיפה אמיתית של התיק.
    מחזיר מידע מלא על מצב הסיכון.
    """
    total_collateral = sum(t.get("usd", 0) for t in open_trades if t.get("status") == "open")
    by_asset = {}
    for t in open_trades:
        if t.get("status") != "open":
            continue
        coin = t["coin"]
        by_asset[coin] = by_asset.get(coin, 0) + t.get("usd", 0)

    exposure_pct = total_collateral / portfolio_usd if portfolio_usd else 0

    asset_pcts = {coin: usd / portfolio_usd for coin, usd in by_asset.items()} if portfolio_usd else {}

    return {
        "total_collateral":  total_collateral,
        "exposure_pct":      round(exposure_pct, 3),
        "by_asset":          by_asset,
        "asset_pcts":        asset_pcts,
        "portfolio_usd":     portfolio_usd,
        "num_positions":     len([t for t in open_trades if t.get("status") == "open"]),
    }


def can_open_position(coin: str, trade_usd: float, margin_headroom: float,
                      exposure: dict, portfolio_usd: float) -> tuple[bool, str]:
    """
    האם מותר לפתוח פוזיציה חדשה?
    מחזיר (True/False, סיבה).
    """
    # kill-switch יומי
    if is_kill_switch_active(portfolio_usd):
        return False, "Kill switch פעיל — drawdown יומי חצה 10%"

    # חשיפה כוללת
    new_exposure_pct = (exposure["total_collateral"] + trade_usd) / portfolio_usd
    if new_exposure_pct > MAX_PORTFOLIO_RISK_PCT:
        return False, f"חשיפה כוללת תגיע ל-{new_exposure_pct:.0%} > מקסימום {MAX_PORTFOLIO_RISK_PCT:.0%}"

    # חשיפה לנכס בודד
    current_asset_usd = exposure["by_asset"].get(coin, 0)
    new_asset_pct = (current_asset_usd + trade_usd) / portfolio_usd
    if new_asset_pct > MAX_SINGLE_ASSET_PCT:
        return False, f"חשיפה ל-{coin} תגיע ל-{new_asset_pct:.0%} > מקסימום {MAX_SINGLE_ASSET_PCT:.0%}"

    # מרג'ין פנוי
    if margin_headroom < MIN_FREE_MARGIN_USD + trade_usd / 5:
        return False, f"מרג'ין פנוי ${margin_headroom:.0f} לא מספיק (מינימום ${MIN_FREE_MARGIN_USD})"

    return True, "OK"


def get_weakest_position(open_trades: list) -> dict | None:
    """
    מחזיר את הפוזיציה הכי חלשה לרוטציה.
    חלשה = P&L הכי נמוך + רחוקה מה-target.
    """
    candidates = [
        t for t in open_trades
        if t.get("status") == "open" and not t.get("is_stock")
    ]
    if not candidates:
        return None

    def weakness_score(t):
        pnl = t.get("pnl_pct", 0)
        entry = t.get("entry_price", 1)
        target = t.get("target_price", entry)
        current = t.get("current_price", entry)
        progress = (current - entry) / (target - entry) if target != entry else 0
        return pnl - (progress * 10)  # נמוך יותר = חלש יותר

    return min(candidates, key=weakness_score)


def build_portfolio_summary(exposure: dict, open_trades: list, margin_used: float, margin_headroom: float) -> str:
    """בונה תיאור תיק מלא לפרומפט קלוד."""
    lines = [
        f"Portfolio: ${exposure['portfolio_usd']:.0f} | Exposure: {exposure['exposure_pct']:.0%} of portfolio",
        f"Margin used: ${margin_used:.0f} | Margin headroom: ${margin_headroom:.0f}",
        f"Open positions ({exposure['num_positions']}):",
    ]
    for t in open_trades:
        if t.get("status") != "open":
            continue
        pnl = t.get("pnl_pct", 0)
        entry = t.get("entry_price", 0)
        target = t.get("target_price", 0)
        current = t.get("current_price", entry)
        progress = round((current - entry) / (target - entry) * 100) if target != entry else 0
        asset_pct = exposure["asset_pcts"].get(t["coin"], 0)
        lines.append(
            f"  {t['coin']}: P&L={pnl:+.1f}% | progress to target={progress}% | "
            f"portfolio_weight={asset_pct:.0%} | usd=${t.get('usd',0):.0f}"
        )

    # drawdown יומי
    dd = _load_drawdown()
    if dd.get("start_portfolio"):
        daily_dd = (dd["start_portfolio"] - exposure["portfolio_usd"]) / dd["start_portfolio"]
        lines.append(f"Daily drawdown: {daily_dd:+.1%} (limit: -{MAX_DAILY_DRAWDOWN_PCT:.0%})")

    return "\n".join(lines)
