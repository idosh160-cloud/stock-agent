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

CONFIDENCE_COLORS = {
    "HIGH":   ("#065f46", "#ecfdf5"),
    "MEDIUM": ("#92400e", "#fffbeb"),
    "LOW":    ("#6b7280", "#f3f4f6"),
}


def pnl_color(v):
    return "#059669" if v >= 0 else "#dc2626"


def sign(v):
    return "+" if v >= 0 else ""


def portfolio_summary_html(totals):
    us_cur     = totals.get("total_us_current_usd", 0)
    us_pnl     = totals.get("total_us_pnl_usd", 0)
    us_pnl_pct = totals.get("total_us_pnl_pct", 0)
    il_cur     = totals.get("total_il_current_ils", 0)
    il_pnl     = totals.get("total_il_pnl_ils", 0)
    il_pnl_pct = totals.get("total_il_pnl_pct", 0)

    return f"""
  <div style="background:white;border-radius:12px;padding:24px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
    <div style="font-weight:700;font-size:16px;margin-bottom:16px">💼 Portfolio Summary</div>
    <div style="display:flex;gap:16px;flex-wrap:wrap">
      <div style="flex:1;min-width:200px;background:#f0f9ff;border-radius:8px;padding:16px;border-left:4px solid #3b82f6">
        <div style="font-size:12px;color:#6b7280;margin-bottom:4px">🇺🇸 US Portfolio</div>
        <div style="font-size:26px;font-weight:700">${us_cur:,.0f}</div>
        <div style="font-size:14px;color:{pnl_color(us_pnl)};font-weight:600">{sign(us_pnl)}${abs(us_pnl):,.0f} ({sign(us_pnl_pct)}{us_pnl_pct}%)</div>
      </div>
      <div style="flex:1;min-width:200px;background:#f0fdf4;border-radius:8px;padding:16px;border-left:4px solid #10b981">
        <div style="font-size:12px;color:#6b7280;margin-bottom:4px">🇮🇱 Israeli Portfolio</div>
        <div style="font-size:26px;font-weight:700">₪{il_cur:,.0f}</div>
        <div style="font-size:14px;color:{pnl_color(il_pnl)};font-weight:600">{sign(il_pnl)}₪{abs(il_pnl):,.0f} ({sign(il_pnl_pct)}{il_pnl_pct}%)</div>
      </div>
    </div>
  </div>"""


def signals_html(key_signals):
    """בלוק אותות — ירוק לחיובי, אדום לאזהרה"""
    if not key_signals:
        return ""
    rows = ""
    for s in key_signals:
        if any(w in s.upper() for w in ["WARNING", "SELLING", "CONCERN", "HIGH SHORT", "ELEVATED", "DEBT", "MISS"]):
            color = "#dc2626"
            bg    = "#fff5f5"
            icon  = "⚠️"
        else:
            color = "#059669"
            bg    = "#f0fdf4"
            icon  = "✅"
        rows += f'<div style="background:{bg};border-radius:6px;padding:6px 10px;margin-bottom:4px;font-size:12px;color:{color}">{icon} {s}</div>'
    return f'<div style="margin-top:8px">{rows}</div>'


def us_stock_card(r):
    """כרטיסייה לכל מניה אמריקאית — עיצוב חדש"""
    action     = r.get("action", "HOLD")
    confidence = r.get("confidence", "MEDIUM")
    txt_color, bg_color   = ACTION_COLORS.get(action, ("#333", "#f3f4f6"))
    ctxt_color, cbg_color = CONFIDENCE_COLORS.get(confidence, ("#6b7280", "#f3f4f6"))

    pnl     = r.get("pnl_dollars", 0) or 0
    pnl_pct = r.get("pnl_pct", 0) or 0
    avg     = r.get("avg_cost", 0)
    price   = r.get("current_price", 0)
    val     = r.get("current_value", 0)
    daily   = r.get("daily_change_pct", 0) or 0

    target  = r.get("analyst_target")
    upside  = r.get("upside_to_target_pct")
    target_str = f"${target:.2f}" if target else "—"
    if upside is not None:
        up_col = "#059669" if upside >= 0 else "#dc2626"
        target_str += f' <span style="color:{up_col};font-size:11px">({sign(upside)}{upside}%)</span>'

    earnings    = r.get("earnings_date", "")
    earnings_exp = r.get("earnings_expectations", "")
    sec_insight  = r.get("sec_insight", "")
    position_advice = r.get("position_advice", "")
    reasoning    = r.get("reasoning", "")

    # אותות מעובדים
    key_signals = r.get("key_signals", [])

    # Support / Resistance / Entry / Stop
    support    = r.get("support_levels", "")
    resistance = r.get("resistance_levels", "")
    entry      = r.get("entry_point", "")
    stop       = r.get("stop_loss", "")

    levels_html = ""
    if any([support, resistance, entry, stop]):
        levels_html = f"""
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
          {"<span style='background:#f0fdf4;color:#059669;padding:3px 8px;border-radius:4px;font-size:11px'>🟢 "+support+"</span>" if support else ""}
          {"<span style='background:#fff5f5;color:#dc2626;padding:3px 8px;border-radius:4px;font-size:11px'>🔴 "+resistance+"</span>" if resistance else ""}
          {"<span style='background:#eff6ff;color:#2563eb;padding:3px 8px;border-radius:4px;font-size:11px'>📍 "+entry+"</span>" if entry else ""}
          {"<span style='background:#fefce8;color:#92400e;padding:3px 8px;border-radius:4px;font-size:11px'>🛑 Stop: "+stop+"</span>" if stop else ""}
        </div>"""

    return f"""
  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.07);border-left:4px solid {bg_color}">

    <!-- שורה עליונה: שם + אקשן + ביטחון -->
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
      <span style="font-size:18px;font-weight:700">{r.get('symbol','')}</span>
      <span style="color:#6b7280;font-size:13px">{r.get('name','')}</span>
      <span style="background:{bg_color};color:{txt_color};padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700">{action}</span>
      <span style="background:{cbg_color};color:{ctxt_color};padding:3px 10px;border-radius:20px;font-size:11px">Confidence: {confidence}</span>
      {"<span style='background:#fef3c7;color:#92400e;padding:3px 8px;border-radius:4px;font-size:11px'>📅 Earnings: "+earnings+"</span>" if earnings else ""}
    </div>

    <!-- נתוני מחיר -->
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px">
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px;min-width:100px">
        <div style="font-size:10px;color:#9ca3af">CURRENT</div>
        <div style="font-size:18px;font-weight:700">${price:.2f}</div>
        <div style="font-size:11px;color:{pnl_color(daily)}">{sign(daily)}{daily:.2f}% today</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px;min-width:100px">
        <div style="font-size:10px;color:#9ca3af">AVG COST</div>
        <div style="font-size:18px;font-weight:700">${avg:.2f}</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px;min-width:100px">
        <div style="font-size:10px;color:#9ca3af">VALUE</div>
        <div style="font-size:18px;font-weight:700">${val:,.0f}</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px;min-width:100px">
        <div style="font-size:10px;color:#9ca3af">P&L</div>
        <div style="font-size:18px;font-weight:700;color:{pnl_color(pnl)}">{sign(pnl)}${abs(pnl):,.0f}</div>
        <div style="font-size:11px;color:{pnl_color(pnl)}">{sign(pnl_pct)}{pnl_pct}%</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px;min-width:100px">
        <div style="font-size:10px;color:#9ca3af">ANALYST TARGET</div>
        <div style="font-size:15px;font-weight:600">{target_str}</div>
      </div>
    </div>

    <!-- אותות -->
    {signals_html(key_signals)}

    <!-- SEC Insight -->
    {"<div style='background:#f0f9ff;border-left:3px solid #3b82f6;padding:8px 12px;border-radius:0 6px 6px 0;margin-top:8px;font-size:12px;color:#1e40af'><b>📄 From 10-Q:</b> "+sec_insight+"</div>" if sec_insight else ""}

    <!-- ניתוח -->
    {"<div style='margin-top:8px;font-size:13px;color:#374151;line-height:1.6'>"+reasoning+"</div>" if reasoning else ""}

    <!-- המלצת פוזיציה -->
    {"<div style='margin-top:8px;background:#fffbeb;border-radius:6px;padding:8px 12px;font-size:12px;color:#92400e;font-weight:600'>💡 "+position_advice+"</div>" if position_advice else ""}

    <!-- Earnings expectations -->
    {"<div style='margin-top:6px;font-size:11px;color:#7c3a00'>📊 "+earnings_exp+"</div>" if earnings_exp else ""}

    <!-- רמות מסחר -->
    {levels_html}

  </div>"""


def il_stock_card(r):
    """כרטיסייה למניה ישראלית"""
    action     = r.get("action", "HOLD")
    confidence = r.get("confidence", "MEDIUM")
    txt_color, bg_color = ACTION_COLORS.get(action, ("#333", "#f3f4f6"))

    pnl     = r.get("pnl_ils", 0) or 0
    pnl_pct = r.get("pnl_pct", 0) or 0
    avg     = r.get("avg_cost", 0)
    price   = r.get("current_price", 0)
    val     = r.get("current_value", 0)
    daily   = r.get("daily_change_pct", 0) or 0

    support    = r.get("support_levels", "")
    resistance = r.get("resistance_levels", "")
    reasoning  = r.get("reasoning", "")
    position_advice = r.get("position_advice", "")

    levels_html = ""
    if any([support, resistance]):
        levels_html = f"""
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
          {"<span style='background:#f0fdf4;color:#059669;padding:3px 8px;border-radius:4px;font-size:11px'>🟢 "+support+"</span>" if support else ""}
          {"<span style='background:#fff5f5;color:#dc2626;padding:3px 8px;border-radius:4px;font-size:11px'>🔴 "+resistance+"</span>" if resistance else ""}
        </div>"""

    return f"""
  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.07);border-left:4px solid {bg_color}">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
      <span style="font-size:18px;font-weight:700">{r.get('symbol','')}</span>
      <span style="color:#6b7280;font-size:13px">{r.get('name','')}</span>
      <span style="background:{bg_color};color:{txt_color};padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700">{action}</span>
      <span style="font-size:11px;color:#6b7280">Confidence: {confidence}</span>
    </div>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px">
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px">
        <div style="font-size:10px;color:#9ca3af">CURRENT</div>
        <div style="font-size:18px;font-weight:700">₪{price:.2f}</div>
        <div style="font-size:11px;color:{pnl_color(daily)}">{sign(daily)}{daily:.2f}% today</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px">
        <div style="font-size:10px;color:#9ca3af">AVG COST</div>
        <div style="font-size:18px;font-weight:700">₪{avg:.2f}</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px">
        <div style="font-size:10px;color:#9ca3af">VALUE</div>
        <div style="font-size:18px;font-weight:700">₪{val:,.0f}</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:10px 16px">
        <div style="font-size:10px;color:#9ca3af">P&L</div>
        <div style="font-size:18px;font-weight:700;color:{pnl_color(pnl)}">{sign(pnl)}₪{abs(pnl):,.0f}</div>
        <div style="font-size:11px;color:{pnl_color(pnl)}">{sign(pnl_pct)}{pnl_pct}%</div>
      </div>
    </div>
    {"<div style='font-size:13px;color:#374151;line-height:1.6;margin-bottom:6px'>"+reasoning+"</div>" if reasoning else ""}
    {"<div style='background:#fffbeb;border-radius:6px;padding:8px 12px;font-size:12px;color:#92400e;font-weight:600'>💡 "+position_advice+"</div>" if position_advice else ""}
    {levels_html}
  </div>"""


def gem_card(gem):
    price = f"${gem['current_price']:.2f}" if gem.get("current_price") else "N/A"
    gain  = gem.get("gain_6mo_pct", 0)
    gain_col  = "#059669" if gain >= 0 else "#dc2626"
    gain_sign = "+" if gain >= 0 else ""
    earnings  = gem.get("earnings_date", "")

    return f"""
  <div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:12px">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
      <span style="font-size:17px;font-weight:700">{gem.get('symbol','')}</span>
      <span style="color:#6b7280;font-size:13px">{gem.get('name','')}</span>
      <span style="font-weight:700;color:#059669;font-size:15px">{price}</span>
      <span style="font-size:12px;color:{gain_col}">{gain_sign}{gain}% (6mo)</span>
      {"<span style='font-size:11px;color:#7c3a00;background:#fef3c7;padding:2px 8px;border-radius:4px'>📅 "+earnings+"</span>" if earnings else ""}
    </div>
    <div style="font-size:11px;color:#6b7280;margin-bottom:8px">📂 {gem.get('sector','')}</div>
    <div style="font-size:13px;margin-bottom:6px;color:#374151">💡 {gem.get('why_interesting','')}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <div style="background:#f0f9ff;border-radius:6px;padding:6px 10px;font-size:12px;color:#1e40af"><b>🤖 AI Angle:</b> {gem.get('ai_infrastructure_angle','')}</div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">
      <div style="background:#f0fdf4;border-radius:6px;padding:6px 10px;font-size:12px;color:#065f46"><b>🚀 Catalyst:</b> {gem.get('catalyst','')}</div>
      <div style="background:#fff5f5;border-radius:6px;padding:6px 10px;font-size:12px;color:#dc2626"><b>⚠️ Risk:</b> {gem.get('risk','')}</div>
    </div>
  </div>"""


def wildcard_card(w):
    """כרטיסייה למניית הוויילדקארד השבועית — חלל / קוונטום"""
    if not w:
        return ""
    price     = w.get("current_price")
    price_str = f"${price:.2f}" if price else "N/A"
    sector    = w.get("sector", "")
    industry  = w.get("industry", "")
    cat_label = "🚀 Space" if "space" in (sector + industry).lower() or any(
        t in w.get("symbol", "") for t in ["RKLB","ASTS","LUNR","SPCE","KTOS","AJRD","MNTS","VORB","IRDM","MAXR","BKSY","GSAT","RDW"]
    ) else "⚛️ Quantum"

    return f"""
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);border-radius:12px;padding:20px;margin-bottom:12px;color:white">
    <div style="font-size:12px;font-weight:700;opacity:0.6;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">{cat_label} · Weekly Wildcard Pick</div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
      <span style="font-size:22px;font-weight:700">{w.get('symbol','')}</span>
      <span style="opacity:0.8;font-size:14px">{w.get('name','')}</span>
      <span style="font-size:18px;font-weight:700;color:#34d399">{price_str}</span>
    </div>
    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:14px;font-size:13px;line-height:1.7;opacity:0.95">
      {w.get('why_interesting','')}
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
      {"<div style='background:rgba(52,211,153,0.15);border-radius:6px;padding:6px 10px;font-size:12px;color:#6ee7b7'><b>🚀 Catalyst:</b> "+w['catalyst']+"</div>" if w.get('catalyst') else ""}
      {"<div style='background:rgba(239,68,68,0.15);border-radius:6px;padding:6px 10px;font-size:12px;color:#fca5a5'><b>⚠️ Risk:</b> "+w['risk']+"</div>" if w.get('risk') else ""}
    </div>
  </div>"""


def fund_card(f):
    pnl_pct = f.get("index_change_pct", 0)
    pc      = pnl_color(pnl_pct)
    ps      = sign(pnl_pct)
    rec     = f.get("recommendation", "HOLD")
    txt_color, bg_color = ACTION_COLORS.get(rec, ("#333", "#f3f4f6"))

    return f"""
  <div style="background:white;border-radius:12px;padding:16px 20px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,0.06);display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <div style="min-width:180px">
      <div style="font-weight:700;font-size:14px">{f.get('name','')}</div>
      <div style="font-size:11px;color:#6b7280">↳ tracks {f.get('tracks','')}</div>
    </div>
    <span style="background:{bg_color};color:{txt_color};padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700">{rec}</span>
    <div style="font-size:13px;color:{pc};font-weight:600">{ps}{pnl_pct}% today</div>
    <div style="font-size:12px;color:#6b7280">Cost basis: ₪{f.get('original_value',0):,.0f}</div>
    <div style="flex:1;min-width:200px;font-size:13px;color:#374151">{f.get('index_analysis','')}</div>
  </div>"""


def build_html(analysis):
    date_str = datetime.now().strftime("%B %d, %Y")
    totals   = analysis.get("portfolio_totals", {})

    us_cards   = "".join(us_stock_card(r) for r in analysis.get("us_recommendations", []))
    il_cards   = "".join(il_stock_card(r) for r in analysis.get("il_recommendations", []))
    fund_cards = "".join(fund_card(f) for f in analysis.get("funds_analysis", []))
    gem_cards  = "".join(gem_card(g) for g in analysis.get("hidden_gems", []))
    wc_card    = wildcard_card(analysis.get("wildcard"))

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;margin:0;padding:0">
<div style="max-width:900px;margin:0 auto;padding:20px">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:white;border-radius:16px;padding:28px 32px;margin-bottom:20px">
    <div style="font-size:24px;font-weight:700">📈 Daily Portfolio Report</div>
    <div style="opacity:0.6;font-size:14px;margin-top:4px">{date_str}</div>
  </div>

  <!-- Market Summary -->
  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:12px;border-left:4px solid #3b82f6;box-shadow:0 1px 3px rgba(0,0,0,0.07)">
    <div style="font-weight:700;font-size:15px;margin-bottom:8px">🌍 Market Summary</div>
    <div style="color:#374151;line-height:1.7;font-size:14px">{analysis.get('market_summary','')}</div>
  </div>

  <!-- Yesterday -->
  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:12px;border-left:4px solid #8b5cf6;box-shadow:0 1px 3px rgba(0,0,0,0.07)">
    <div style="font-weight:700;font-size:15px;margin-bottom:8px">⏮ Yesterday's Recap</div>
    <div style="color:#374151;line-height:1.7;font-size:14px">{analysis.get('yesterday_recap','')}</div>
  </div>

  <!-- Rumors -->
  <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:20px;margin-bottom:20px">
    <div style="font-weight:700;color:#92400e;font-size:15px;margin-bottom:8px">🔔 Rumors & Contracts</div>
    <div style="color:#78350f;line-height:1.7;font-size:14px">{analysis.get('rumors_and_contracts','No notable rumors today.')}</div>
  </div>

  <!-- Portfolio Totals -->
  {portfolio_summary_html(totals)}

  <!-- US Stocks -->
  <div style="font-weight:700;font-size:17px;margin:20px 0 12px">🇺🇸 US Portfolio</div>
  {us_cards}

  <!-- Israeli Stocks -->
  <div style="font-weight:700;font-size:17px;margin:20px 0 12px">🇮🇱 Israeli Stocks</div>
  {il_cards}

  <!-- Funds -->
  <div style="font-weight:700;font-size:17px;margin:20px 0 12px">📊 Israeli Funds</div>
  {fund_cards}

  <!-- Hidden Gems -->
  <div style="font-weight:700;font-size:17px;margin:20px 0 12px">💎 Hidden Gems</div>
  {gem_cards}

  <!-- Wildcard -->
  {('<div style="font-weight:700;font-size:17px;margin:20px 0 12px">🌌 Weekly Wildcard</div>' + wc_card) if wc_card else ""}

  <!-- Footer -->
  <div style="text-align:center;color:#9ca3af;font-size:11px;margin-top:24px;padding-bottom:16px">
    ⚠️ AI-generated analysis. Not financial advice. · {date_str}
  </div>

</div>
</body></html>"""


def send_email(analysis):
    env_path = r"C:\Users\User\Documents\stock_agent\.env"
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if v:
                        os.environ[k] = v
    except Exception:
        pass

    sender    = os.getenv("GMAIL_USER")
    password  = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL", sender)

    if not sender or not password:
        print("חסר GMAIL_USER או GMAIL_APP_PASSWORD")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 Daily Stock Report · {datetime.now().strftime('%b %d, %Y')}"
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(build_html(analysis), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"מייל נשלח ל-{recipient}")
        return True
    except Exception as e:
        print(f"שגיאה בשליחת מייל: {e}")
        return False
