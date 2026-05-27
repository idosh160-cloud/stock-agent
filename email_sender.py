# email_sender.py - שולח את המייל הבוקר

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

ACTION_COLORS = {
    "BUY MORE":     ("#064e3b", "#d1fae5"),
    "BUY":          ("#064e3b", "#d1fae5"),
    "HOLD":         ("#1e3a5f", "#dbeafe"),
    "SELL PARTIAL": ("#7c3a00", "#fef3c7"),
    "SELL ALL":     ("#7f1d1d", "#fee2e2"),
}

def portfolio_summary_html(totals):
    us_cur = totals.get("total_us_current_usd", 0)
    us_pnl = totals.get("total_us_pnl_usd", 0)
    us_pnl_pct = totals.get("total_us_pnl_pct", 0)
    il_cur = totals.get("total_il_current_ils", 0)
    il_pnl = totals.get("total_il_pnl_ils", 0)
    il_pnl_pct = totals.get("total_il_pnl_pct", 0)

    def pnl_color(v): return "#059669" if v >= 0 else "#dc2626"
    def sign(v): return "+" if v >= 0 else ""

    return f"""
  <div style="background:white;border-radius:12px;padding:24px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.1)">
    <div style="font-weight:700;font-size:16px;margin-bottom:16px">💼 Portfolio Summary</div>
    <div style="display:flex;gap:16px;flex-wrap:wrap">

      <div style="flex:1;min-width:200px;background:#f8fafc;border-radius:8px;padding:16px;border-left:4px solid #3b82f6">
        <div style="font-size:12px;color:#6b7280;margin-bottom:4px">🇺🇸 US Portfolio</div>
        <div style="font-size:24px;font-weight:700">${us_cur:,.0f}</div>
        <div style="font-size:14px;color:{pnl_color(us_pnl)};font-weight:600">{sign(us_pnl)}${abs(us_pnl):,.0f} ({sign(us_pnl_pct)}{us_pnl_pct}%)</div>
      </div>

      <div style="flex:1;min-width:200px;background:#f8fafc;border-radius:8px;padding:16px;border-left:4px solid #10b981">
        <div style="font-size:12px;color:#6b7280;margin-bottom:4px">🇮🇱 Israeli Portfolio</div>
        <div style="font-size:24px;font-weight:700">₪{il_cur:,.0f}</div>
        <div style="font-size:14px;color:{pnl_color(il_pnl)};font-weight:600">{sign(il_pnl)}₪{abs(il_pnl):,.0f} ({sign(il_pnl_pct)}{il_pnl_pct}%)</div>
      </div>

    </div>
  </div>"""


def rec_row(r, currency="$"):
    action = r.get("action", "HOLD")
    txt_color, bg_color = ACTION_COLORS.get(action, ("#333", "#f3f4f6"))
    pnl = r.get("pnl_dollars") or r.get("pnl_ils", 0)
    pnl_pct = r.get("pnl_pct", 0)
    pnl_color = "#059669" if pnl >= 0 else "#dc2626"
    pnl_sign = "+" if pnl >= 0 else ""
    avg_cost = r.get("avg_cost", 0)
    current_price = r.get("current_price", 0)

    target = r.get("analyst_target")
    upside = r.get("upside_to_target_pct")
    if target:
        target_str = f"${target:.2f}"
        if upside:
            upside_color = "#059669" if upside >= 0 else "#dc2626"
            upside_sign = "+" if upside >= 0 else ""
            target_str += f'<br><span style="font-size:11px;color:{upside_color}">{upside_sign}{upside}%</span>'
    else:
        target_str = "—"

    earnings = r.get("earnings_date", "")
    earnings_str = f'<br><span style="font-size:11px;color:#7c3a00">📅 {earnings}</span>' if earnings else ""

    support = r.get("support_levels", "")
    resistance = r.get("resistance_levels", "")
    entry = r.get("entry_point", "")
    stop = r.get("stop_loss", "")
    trading_html = ""
    if any([support, resistance, entry, stop]):
        trading_html = f"""
        <div style="font-size:11px;margin-top:6px;padding:6px;background:#f8fafc;border-radius:4px;line-height:1.8">
            {"<span style='color:#059669'>🟢 "+support+"</span><br>" if support else ""}
            {"<span style='color:#dc2626'>🔴 "+resistance+"</span><br>" if resistance else ""}
            {"<span style='color:#2563eb'>📍 "+entry+"</span><br>" if entry else ""}
            {"<span style='color:#7c3a00'>🛑 Stop: "+stop+"</span>" if stop else ""}
        </div>"""

    earnings_exp = r.get("earnings_expectations", "")

    return f"""
    <tr style="border-bottom:1px solid #f3f4f6;vertical-align:top">
      <td style="padding:12px 16px;font-weight:700;white-space:nowrap">{r.get('symbol','')}{earnings_str}</td>
      <td style="padding:12px 16px;color:#6b7280;font-size:13px">{r.get('name','')}</td>
      <td style="padding:12px 16px">
        <span style="background:{bg_color};color:{txt_color};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700">{action}</span>
      </td>
      <td style="padding:12px 16px;font-size:13px">
        <span style="color:#6b7280;font-size:11px">avg</span> <strong>{currency}{avg_cost:.2f}</strong><br>
        <span style="color:#6b7280;font-size:11px">now</span> <strong>{currency}{current_price:.2f}</strong>
      </td>
      <td style="padding:12px 16px;font-weight:600">{currency}{r.get('current_value',0):,.0f}</td>
      <td style="padding:12px 16px;color:{pnl_color};font-weight:600">
        {pnl_sign}{currency}{abs(pnl):,.0f}<br>
        <span style="font-size:12px">({pnl_sign}{pnl_pct}%)</span>
      </td>
      <td style="padding:12px 16px;color:#374151;font-size:13px;max-width:220px">
        {r.get('reasoning','')}
        {trading_html}
        {"<div style='font-size:11px;color:#7c3a00;margin-top:4px'>📊 "+earnings_exp+"</div>" if earnings_exp else ""}
      </td>
      <td style="padding:12px 16px;font-size:13px">{target_str}</td>
    </tr>"""


def table_html(rows_html, title, icon):
    return f"""
  <div style="background:white;border-radius:12px;overflow:hidden;margin-bottom:16px">
    <div style="padding:16px 24px;border-bottom:1px solid #e5e7eb;font-weight:700;font-size:16px">{icon} {title}</div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead>
          <tr style="background:#f9fafb;color:#6b7280;font-size:11px;text-transform:uppercase">
            <th style="padding:10px 16px;text-align:left">Symbol</th>
            <th style="padding:10px 16px;text-align:left">Name</th>
            <th style="padding:10px 16px;text-align:left">Action</th>
            <th style="padding:10px 16px;text-align:left">Price</th>
            <th style="padding:10px 16px;text-align:left">Value</th>
            <th style="padding:10px 16px;text-align:left">P&L</th>
            <th style="padding:10px 16px;text-align:left">Analysis</th>
            <th style="padding:10px 16px;text-align:left">Target</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>"""


def build_html(analysis):
    date_str = datetime.now().strftime("%B %d, %Y")
    totals = analysis.get("portfolio_totals", {})

    us_rows = "".join(rec_row(r, "$") for r in analysis.get("us_recommendations", []))
    il_rows = "".join(rec_row(r, "₪") for r in analysis.get("il_recommendations", []))

    funds_rows = ""
    for f in analysis.get("funds_analysis", []):
        pnl_pct = f.get("index_change_pct", 0)
        pnl_color = "#059669" if pnl_pct >= 0 else "#dc2626"
        pnl_sign = "+" if pnl_pct >= 0 else ""
        rec = f.get("recommendation", "HOLD")
        txt_color, bg_color = ACTION_COLORS.get(rec, ("#333", "#f3f4f6"))
        funds_rows += f"""
        <tr style="border-bottom:1px solid #f3f4f6;vertical-align:top">
          <td style="padding:12px 16px;font-weight:700">{f.get('name','')}</td>
          <td style="padding:12px 16px;color:#6b7280;font-size:13px">↳ {f.get('tracks','')}</td>
          <td style="padding:12px 16px">
            <span style="background:{bg_color};color:{txt_color};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700">{rec}</span>
          </td>
          <td style="padding:12px 16px;font-weight:600">₪{f.get('original_value',0):,.0f}</td>
          <td style="padding:12px 16px;color:{pnl_color};font-weight:600">{pnl_sign}{pnl_pct}% today</td>
          <td style="padding:12px 16px;color:#374151;font-size:13px" colspan="3">{f.get('index_analysis','')}</td>
        </tr>"""

    gem_cards = ""
    for gem in analysis.get("hidden_gems", []):
        price = f"${gem['current_price']:.2f}" if gem.get("current_price") else "N/A"
        gain = gem.get("gain_6mo_pct", 0)
        gain_color = "#059669" if gain >= 0 else "#dc2626"
        gain_sign = "+" if gain >= 0 else ""
        earnings = gem.get("earnings_date", "")
        gem_cards += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px">
            <span style="font-size:17px;font-weight:700">{gem['symbol']}</span>
            <span style="color:#6b7280;font-size:13px">{gem.get('name','')}</span>
            <span style="font-weight:600;color:#059669">{price}</span>
            <span style="font-size:12px;color:{gain_color}">{gain_sign}{gain}% (6mo)</span>
            {"<span style='font-size:11px;color:#7c3a00'>📅 "+earnings+"</span>" if earnings else ""}
          </div>
          <div style="font-size:12px;color:#6b7280;margin-bottom:6px">📂 {gem.get('sector','')}</div>
          <div style="font-size:13px;margin-bottom:4px">💡 {gem.get('why_interesting','')}</div>
          <div style="font-size:13px;margin-bottom:4px">🤖 <b>AI angle:</b> {gem.get('ai_infrastructure_angle','')}</div>
          <div style="font-size:13px;margin-bottom:4px">🚀 <b>Catalyst:</b> {gem.get('catalyst','')}</div>
          <div style="font-size:12px;color:#ef4444">⚠️ {gem.get('risk','')}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,sans-serif;background:#f9fafb;margin:0;padding:0">
<div style="max-width:960px;margin:0 auto;padding:24px">

  <div style="background:#0f172a;color:white;border-radius:12px;padding:24px 32px;margin-bottom:20px">
    <div style="font-size:22px;font-weight:700">📈 Daily Portfolio Report</div>
    <div style="opacity:0.6;font-size:14px;margin-top:4px">{date_str}</div>
  </div>

  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px;border-left:4px solid #3b82f6">
    <div style="font-weight:700;margin-bottom:8px">🌍 Market Summary</div>
    <div style="color:#374151;line-height:1.6">{analysis.get('market_summary','')}</div>
  </div>

  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px;border-left:4px solid #8b5cf6">
    <div style="font-weight:700;margin-bottom:8px">⏮ Yesterday's Recap</div>
    <div style="color:#374151;line-height:1.6">{analysis.get('yesterday_recap','')}</div>
  </div>

  <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:20px;margin-bottom:16px">
    <div style="font-weight:700;color:#92400e;margin-bottom:8px">🔔 Rumors & Contracts</div>
    <div style="color:#78350f;line-height:1.6">{analysis.get('rumors_and_contracts','No notable rumors today.')}</div>
  </div>

  {portfolio_summary_html(totals)}

  {table_html(us_rows, "US Portfolio", "🇺🇸")}
  {table_html(il_rows, "Israeli Stocks", "🇮🇱")}

  <div style="background:white;border-radius:12px;overflow:hidden;margin-bottom:16px">
    <div style="padding:16px 24px;border-bottom:1px solid #e5e7eb;font-weight:700;font-size:16px">📊 Israeli Funds — Index Analysis</div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead>
          <tr style="background:#f9fafb;color:#6b7280;font-size:11px;text-transform:uppercase">
            <th style="padding:10px 16px;text-align:left">Fund</th>
            <th style="padding:10px 16px;text-align:left">Tracks</th>
            <th style="padding:10px 16px;text-align:left">Signal</th>
            <th style="padding:10px 16px;text-align:left">Cost Basis</th>
            <th style="padding:10px 16px;text-align:left">Index Today</th>
            <th style="padding:10px 16px;text-align:left" colspan="3">Analysis</th>
          </tr>
        </thead>
        <tbody>{funds_rows}</tbody>
      </table>
    </div>
  </div>

  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px">
    <div style="font-weight:700;font-size:16px;margin-bottom:16px">💎 Hidden Gems — AI Infrastructure</div>
    {gem_cards}
  </div>

  <div style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px">
    ⚠️ AI-generated analysis. Not financial advice.<br>{date_str}
  </div>
</div>
</body></html>"""


def send_email(analysis):
    sender = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL", sender)

    if not sender or not password:
        print("❌ חסר GMAIL_USER או GMAIL_APP_PASSWORD")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 Daily Stock Report · {datetime.now().strftime('%b %d, %Y')}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(build_html(analysis), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"✅ מייל נשלח ל-{recipient}")
        return True
    except Exception as e:
        print(f"❌ שגיאה: {e}")
        return False