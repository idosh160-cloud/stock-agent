"""
daily_report.py — מייל סיכום יומי בעברית (RTL) על פעילות הבוט.
לא קורא ל-Claude — רק קורא קבצים ושולח מייל. אפס טוקנים.
"""
import os
import json
import smtplib
import logging
from datetime import datetime, date
from email.mime.text import MIMEText

DIR          = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(DIR, "swing_history.json")
SWING_FILE   = os.path.join(DIR, "swing_trades.json")
SENT_FLAG    = os.path.join(DIR, "last_daily_report.txt")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _side_he(t):
    return "שורט 📉" if t.get("side") == "short" else "לונג 📈"


def _pnl_color(v):
    return "#16a34a" if v >= 0 else "#dc2626"


def build_daily_html(portfolio_usd: float = 0) -> tuple[str, str]:
    """בונה (subject, html) לסיכום היומי. הכל מהקבצים — בלי Claude."""
    today = date.today().isoformat()
    history = _load(HISTORY_FILE)
    trades  = _load(SWING_FILE)

    # עסקאות שנסגרו היום
    closed_today = [
        h for h in history
        if isinstance(h.get("date_close"), str) and h["date_close"][:10] == today
    ]
    day_pnl = round(sum(h.get("pnl_usd", 0) for h in closed_today), 2)

    # פוזיציות פתוחות עכשיו
    open_now = [t for t in trades if t.get("status") == "open"]

    # edge כולל
    wins = [h for h in history if h.get("pnl_usd", 0) > 0]
    total_trades = len(history)
    win_rate = round(len(wins) / total_trades * 100) if total_trades else 0
    total_pnl = round(sum(h.get("pnl_usd", 0) for h in history), 2)
    expectancy = round(total_pnl / total_trades, 2) if total_trades else 0

    # ── בניית כרטיסיות ──
    def card(inner, accent="#3b82f6"):
        return (f'<div style="background:#ffffff;border-radius:12px;padding:16px 18px;'
                f'margin-bottom:12px;border-right:4px solid {accent};'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.08)">{inner}</div>')

    # עסקאות היום
    if closed_today:
        rows = ""
        for h in closed_today:
            pnl = h.get("pnl_usd", 0)
            col = _pnl_color(pnl)
            icon = "✅" if pnl >= 0 else "🔴"
            rows += (f'<div style="display:flex;justify-content:space-between;'
                     f'padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:14px">'
                     f'<span>{icon} <b>{h.get("coin","")}</b> {_side_he(h)}</span>'
                     f'<span style="color:{col};font-weight:700">{pnl:+.2f}$ '
                     f'({h.get("pnl_pct",0):+.1f}%)</span></div>')
        closed_html = card(
            f'<div style="font-weight:700;font-size:15px;margin-bottom:8px">'
            f'🔄 עסקאות שנסגרו היום ({len(closed_today)})</div>{rows}'
            f'<div style="margin-top:8px;font-size:15px;font-weight:700;'
            f'color:{_pnl_color(day_pnl)}">סה"כ היום: {day_pnl:+.2f}$</div>',
            accent="#16a34a" if day_pnl >= 0 else "#dc2626")
    else:
        closed_html = card(
            '<div style="font-weight:700;font-size:15px;margin-bottom:4px">😴 לא נסגרו עסקאות היום</div>'
            '<div style="color:#64748b;font-size:13px">הבוט החזיק פוזיציות או לא מצא הזדמנות ששווה כניסה.</div>',
            accent="#94a3b8")

    # פוזיציות פתוחות
    if open_now:
        rows = ""
        for t in open_now:
            pnl = t.get("pnl_pct", 0)
            col = _pnl_color(pnl)
            rows += (f'<div style="display:flex;justify-content:space-between;'
                     f'padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:14px">'
                     f'<span><b>{t.get("coin","")}</b> {_side_he(t)}</span>'
                     f'<span style="color:{col};font-weight:700">{pnl:+.1f}%</span></div>')
        open_html = card(
            f'<div style="font-weight:700;font-size:15px;margin-bottom:8px">'
            f'📊 פוזיציות פתוחות עכשיו ({len(open_now)})</div>{rows}',
            accent="#3b82f6")
    else:
        open_html = card(
            '<div style="font-weight:700;font-size:15px">📭 אין פוזיציות פתוחות</div>',
            accent="#94a3b8")

    # edge
    edge_html = card(
        f'<div style="font-weight:700;font-size:15px;margin-bottom:8px">🎯 ביצועים מצטברים</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:14px;padding:4px 0">'
        f'<span>סה"כ עסקאות</span><span style="font-weight:700">{total_trades}</span></div>'
        f'<div style="display:flex;justify-content:space-between;font-size:14px;padding:4px 0">'
        f'<span>אחוז הצלחה</span><span style="font-weight:700">{win_rate}%</span></div>'
        f'<div style="display:flex;justify-content:space-between;font-size:14px;padding:4px 0">'
        f'<span>תוחלת לעסקה</span><span style="font-weight:700;color:{_pnl_color(expectancy)}">{expectancy:+.2f}$</span></div>'
        f'<div style="display:flex;justify-content:space-between;font-size:14px;padding:4px 0">'
        f'<span>רווח/הפסד כולל</span><span style="font-weight:700;color:{_pnl_color(total_pnl)}">{total_pnl:+.2f}$</span></div>',
        accent="#8b5cf6")

    pf_html = ""
    if portfolio_usd:
        pf_html = (f'<div style="text-align:center;margin-bottom:16px">'
                   f'<div style="color:#cbd5e1;font-size:13px">שווי תיק</div>'
                   f'<div style="font-size:30px;font-weight:800;color:#ffffff">${portfolio_usd:,.0f}</div></div>')

    date_str = datetime.now().strftime("%d/%m/%Y")
    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="he"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;
font-family:'Segoe UI',Arial,sans-serif;direction:rtl;text-align:right">
<div style="max-width:560px;margin:0 auto;padding:20px">
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);
  border-radius:16px;padding:24px;margin-bottom:16px">
    <div style="font-size:20px;font-weight:800;color:#ffffff">🤖 סיכום יומי — בוט הקריפטו</div>
    <div style="color:#94a3b8;font-size:13px;margin-top:2px">{date_str}</div>
    <div style="height:14px"></div>
    {pf_html}
  </div>
  {closed_html}
  {open_html}
  {edge_html}
  <div style="text-align:center;color:#94a3b8;font-size:11px;margin-top:16px">
    דוח אוטומטי · לא ייעוץ השקעות
  </div>
</div></body></html>"""

    subject = f"🤖 סיכום יומי {date_str} — {day_pnl:+.2f}$ היום | {len(open_now)} פוזיציות פתוחות"
    return subject, html


def _send_html(subject: str, html: str) -> bool:
    sender   = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not sender or not password:
        logging.warning("[DailyReport] חסרים פרטי Gmail")
        return False
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = sender
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls(); s.login(sender, password)
            s.sendmail(sender, sender, msg.as_string())
        logging.info("[DailyReport] מייל סיכום יומי נשלח")
        return True
    except Exception as e:
        logging.warning(f"[DailyReport] שליחה נכשלה: {e}")
        return False


def send_daily_if_due(portfolio_usd: float = 0, hour: int = 9) -> bool:
    """שולח את הסיכום היומי פעם ביום בשעה שנקבעה. בלי Claude.
    קורא לזה בכל ריצה — הוא שולח רק אם השעה הגיעה וטרם נשלח היום."""
    now = datetime.now()
    if now.hour < hour:
        return False
    today = date.today().isoformat()
    if os.path.exists(SENT_FLAG):
        try:
            if open(SENT_FLAG, encoding="utf-8").read().strip() == today:
                return False
        except Exception:
            pass
    subject, html = build_daily_html(portfolio_usd)
    ok = _send_html(subject, html)
    if ok:
        try:
            with open(SENT_FLAG, "w", encoding="utf-8") as f:
                f.write(today)
        except Exception:
            pass
    return ok
