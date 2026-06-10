# dashboard.py — דשבורד מניות חי
# הפעלה: python -m streamlit run dashboard.py

import os
import json
import time
import math
from datetime import datetime

import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px

# ── הגדרות ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stock Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR      = os.path.dirname(__file__)
ANALYSIS_FILE = os.path.join(BASE_DIR, "last_analysis.json")
SCAN_FILE     = os.path.join(BASE_DIR, "scan_results.json")
REFRESH_SEC   = 60  # רענון מחירים אוטומטי


# ── עזרים ───────────────────────────────────────────────────────────────
def safe_float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0

def pnl_color(v):
    return "green" if v >= 0 else "red"

def sign(v):
    return "+" if v >= 0 else ""

def load_analysis():
    if not os.path.exists(ANALYSIS_FILE):
        return None
    try:
        with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_scan():
    if not os.path.exists(SCAN_FILE):
        return None
    try:
        with open(SCAN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def fetch_live_prices(symbols):
    """מחירים חיים / סגירה אחרונה"""
    prices = {}
    for sym in symbols:
        try:
            t    = yf.Ticker(sym)
            info = t.info
            p    = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            if p == 0:
                hist = t.history(period="2d")
                p = safe_float(hist["Close"].iloc[-1]) if len(hist) > 0 else 0
            prev = safe_float(info.get("previousClose") or p)
            chg  = round((p - prev) / prev * 100, 2) if prev else 0
            prices[sym] = {"price": round(p, 2), "change_pct": chg}
        except Exception:
            prices[sym] = {"price": 0, "change_pct": 0}
    return prices

def fetch_chart(symbol, period="3mo"):
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


# ── CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .metric-card {
    background: #1e293b; border-radius: 12px; padding: 16px 20px;
    margin-bottom: 12px;
  }
  .ticker { font-size: 22px; font-weight: 700; color: #f1f5f9; }
  .name   { font-size: 13px; color: #94a3b8; margin-bottom: 10px; }
  .badge  {
    display: inline-block; padding: 3px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 700; margin-right: 6px;
  }
  .green  { color: #34d399; }
  .red    { color: #f87171; }
  .gray   { color: #94a3b8; }
  .signal-ok   { background: #064e3b; color: #6ee7b7; padding: 4px 8px; border-radius: 6px; font-size: 12px; margin: 2px 0; display: block; }
  .signal-warn { background: #7f1d1d; color: #fca5a5; padding: 4px 8px; border-radius: 6px; font-size: 12px; margin: 2px 0; display: block; }
</style>
""", unsafe_allow_html=True)


# ── טעינת ניתוח ─────────────────────────────────────────────────────────
analysis = load_analysis()

# ── כותרת ───────────────────────────────────────────────────────────────
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("## 📈 Stock Dashboard")
with col_time:
    st.markdown(f"<div style='text-align:right;color:#94a3b8;padding-top:10px'>{datetime.now().strftime('%d/%m/%Y %H:%M')}</div>", unsafe_allow_html=True)

if analysis is None:
    st.warning("⚠️ אין ניתוח זמין — הרץ את הסוכן קודם (`python run.py` או `python test_email.py`)")
    st.stop()

# ── סיכום שוק ───────────────────────────────────────────────────────────
with st.expander("🌍 סיכום שוק + חדשות", expanded=False):
    st.write(analysis.get("market_summary", ""))
    recap = analysis.get("yesterday_recap", "")
    if recap:
        st.caption(f"⏮ {recap}")
    rumors = analysis.get("rumors_and_contracts", "")
    if rumors:
        st.info(f"🔔 {rumors}")

# ── מניות US — מחירים חיים ──────────────────────────────────────────────
us_recs = analysis.get("us_recommendations", [])
symbols = [r["symbol"] for r in us_recs]

# Auto-refresh
if "last_refresh" not in st.session_state or time.time() - st.session_state.last_refresh > REFRESH_SEC:
    with st.spinner("מרענן מחירים..."):
        st.session_state.live_prices = fetch_live_prices(symbols)
        st.session_state.last_refresh = time.time()

live = st.session_state.get("live_prices", {})

# ── Portfolio Summary — קורא ישירות מ-last_analysis.json ────────────────
totals = analysis.get("portfolio_totals", {})
total_current  = safe_float(totals.get("total_us_current_usd", 0))
total_original = safe_float(totals.get("total_us_original_usd", 0))

# fallback — חשב מהמניות אם totals ריק
if total_current == 0:
    for r in us_recs:
        total_current  += safe_float(r.get("current_value", 0))
        total_original += safe_float(r.get("original_value", 0))

total_pnl     = total_current - total_original
total_pnl_pct = round(total_pnl / total_original * 100, 1) if total_original else 0

st.markdown("### 💼 US Portfolio")
c1, c2, c3 = st.columns(3)
c1.metric("שווי נוכחי", f"${total_current:,.0f}")
c2.metric("עלות מקורית", f"${total_original:,.0f}")
c3.metric("P&L כולל", f"${total_pnl:+,.0f}", delta=f"{total_pnl_pct:+.1f}%")

st.divider()

# ── כרטיסיות מניות ──────────────────────────────────────────────────────
col_refresh = st.columns([1, 4])[0]
if col_refresh.button("🔄 רענן מחירים"):
    with st.spinner("מרענן..."):
        st.session_state.live_prices = fetch_live_prices(symbols)
        st.session_state.last_refresh = time.time()
    st.rerun()

ACTION_COLORS = {
    "BUY MORE": "#065f46", "BUY": "#065f46",
    "HOLD": "#1e3a5f",
    "SELL PARTIAL": "#92400e", "SELL ALL": "#7f1d1d",
}

for r in us_recs:
    sym    = r["symbol"]
    live_price = safe_float(live.get(sym, {}).get("price", 0))
    price  = live_price if live_price > 0 else safe_float(r.get("current_price", 0))
    chg    = safe_float(live.get(sym, {}).get("change_pct") or r.get("daily_change_pct", 0))
    shares = safe_float(r.get("shares", 0))
    avg    = safe_float(r.get("avg_cost", 0))
    val    = safe_float(r.get("current_value", 0)) or price * shares
    pnl    = safe_float(r.get("pnl_dollars", 0)) or val - avg * shares
    pnl_p  = safe_float(r.get("pnl_pct", 0)) or (round(pnl / (avg * shares) * 100, 1) if avg and shares else 0)
    action = r.get("action", "HOLD")
    conf   = r.get("confidence", "MEDIUM")
    target = r.get("analyst_target")
    upside = r.get("upside_to_target_pct")
    signals = r.get("key_signals", [])
    reasoning = r.get("reasoning", "")
    sec_insight = r.get("sec_insight", "")
    position_advice = r.get("position_advice", "")
    ac = ACTION_COLORS.get(action, "#1e293b")

    with st.container():
        st.markdown(f"<div style='border-left:4px solid {ac};background:#1e293b;border-radius:12px;padding:16px 20px;margin-bottom:16px'>", unsafe_allow_html=True)

        # שורה עליונה
        hc1, hc2, hc3 = st.columns([2, 2, 1])
        with hc1:
            st.markdown(f"<span class='ticker'>{sym}</span> <span class='name'>{r.get('name','')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span class='badge' style='background:{ac};color:white'>{action}</span><span class='badge' style='background:#334155;color:#94a3b8'>Confidence: {conf}</span>", unsafe_allow_html=True)
        with hc2:
            chg_col = "#34d399" if chg >= 0 else "#f87171"
            pnl_col = "#34d399" if pnl >= 0 else "#f87171"
            target_html = ""
            if target:
                up_col = "#34d399" if (upside or 0) >= 0 else "#f87171"
                target_html = (
                    "<div><div style='font-size:10px;color:#64748b'>יעד</div>"
                    "<div style='font-size:15px;font-weight:600;color:#93c5fd'>$" + str(target) + "</div>"
                    "<div style='font-size:11px;color:" + up_col + "'>" + sign(upside or 0) + str(upside) + "%</div></div>"
                )
            price_html = (
                "<div style='display:flex;gap:16px;flex-wrap:wrap'>"
                "<div><div style='font-size:10px;color:#64748b'>מחיר</div>"
                "<div style='font-size:20px;font-weight:700;color:#f1f5f9'>$" + f"{price:.2f}" + "</div>"
                "<div style='color:" + chg_col + ";font-size:12px'>" + sign(chg) + f"{chg:.2f}" + "% היום</div></div>"
                "<div><div style='font-size:10px;color:#64748b'>עלות</div>"
                "<div style='font-size:18px;font-weight:600;color:#94a3b8'>$" + f"{avg:.2f}" + "</div></div>"
                "<div><div style='font-size:10px;color:#64748b'>שווי</div>"
                "<div style='font-size:18px;font-weight:600;color:#f1f5f9'>$" + f"{val:,.0f}" + "</div></div>"
                "<div><div style='font-size:10px;color:#64748b'>P&L</div>"
                "<div style='font-size:18px;font-weight:700;color:" + pnl_col + "'>" + sign(pnl) + "$" + f"{abs(pnl):,.0f}" + "</div>"
                "<div style='font-size:11px;color:" + pnl_col + "'>" + sign(pnl_p) + f"{pnl_p}" + "%</div></div>"
                + target_html +
                "</div>"
            )
            st.markdown(price_html, unsafe_allow_html=True)
        with hc3:
            # גרף מיני
            hist = fetch_chart(sym, "1mo")
            if hist is not None and not hist.empty:
                fig = go.Figure(go.Scatter(
                    x=hist.index, y=hist["Close"],
                    line=dict(color="#34d399" if hist["Close"].iloc[-1] >= hist["Close"].iloc[0] else "#f87171", width=2),
                    fill="tozeroy", fillcolor="rgba(52,211,153,0.08)"
                ))
                fig.update_layout(
                    height=80, margin=dict(l=0,r=0,t=0,b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    showlegend=False, xaxis=dict(visible=False), yaxis=dict(visible=False)
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # אותות — נקה HTML אם יש
        if signals:
            import re
            sig_html = ""
            for s in signals:
                s_clean = re.sub(r'<[^>]+>', '', str(s)).strip()
                if not s_clean:
                    continue
                is_warn = any(w in s_clean.upper() for w in ["WARNING","SELLING","CONCERN","HIGH SHORT","ELEVATED","DEBT","MISS","AVOID","LOSS"])
                color = "#f87171" if is_warn else "#6ee7b7"
                bg    = "#1a0a0a" if is_warn else "#0a1a0a"
                icon  = "⚠️" if is_warn else "✅"
                sig_html += f"<div style='background:{bg};border-radius:6px;padding:5px 10px;margin:2px 0;font-size:12px;color:{color}'>{icon} {s_clean}</div>"
            st.markdown(sig_html, unsafe_allow_html=True)

        # SEC insight
        if sec_insight:
            st.markdown(f"<div style='background:#0f172a;border-left:3px solid #3b82f6;padding:8px 12px;border-radius:0 6px 6px 0;margin-top:8px;font-size:12px;color:#93c5fd'>📄 {sec_insight}</div>", unsafe_allow_html=True)

        # ניתוח + המלצת פוזיציה
        if reasoning:
            st.markdown(f"<div style='font-size:13px;color:#cbd5e1;margin-top:8px;line-height:1.6'>{reasoning}</div>", unsafe_allow_html=True)
        if position_advice:
            st.markdown(f"<div style='background:#1c1917;border-radius:6px;padding:8px 12px;font-size:12px;color:#fbbf24;margin-top:6px'>💡 {position_advice}</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

# ── פנינות נסתרות ────────────────────────────────────────────────────────
gems = analysis.get("hidden_gems", [])
if gems:
    st.divider()
    st.markdown("### 💎 פנינות נסתרות")
    gcols = st.columns(min(len(gems), 3))
    for i, gem in enumerate(gems):
        with gcols[i % len(gcols)]:
            price = safe_float(gem.get("current_price", 0))
            gain  = gem.get("gain_6mo_pct", 0)
            st.markdown(f"""
            <div style='background:#1e293b;border-radius:12px;padding:16px;height:100%'>
              <div style='font-size:18px;font-weight:700;color:#f1f5f9'>{gem.get('symbol','')} <span style='font-size:13px;color:#94a3b8'>{gem.get('name','')}</span></div>
              <div style='font-size:20px;font-weight:700;color:#34d399;margin:4px 0'>${price:.2f} <span style='font-size:13px;color:{"#34d399" if gain>=0 else "#f87171"}'>{sign(gain)}{gain}% (6mo)</span></div>
              <div style='font-size:11px;color:#64748b;margin-bottom:8px'>📂 {gem.get('sector','')}</div>
              <div style='font-size:13px;color:#cbd5e1;margin-bottom:6px'>💡 {gem.get('why_interesting','')}</div>
              <div style='font-size:12px;color:#93c5fd'>🤖 {gem.get('ai_infrastructure_angle','')}</div>
              <div style='font-size:12px;color:#34d399;margin-top:4px'>🚀 {gem.get('catalyst','')}</div>
              <div style='font-size:12px;color:#f87171;margin-top:2px'>⚠️ {gem.get('risk','')}</div>
            </div>
            """, unsafe_allow_html=True)

# ── Wildcard ─────────────────────────────────────────────────────────────
wc = analysis.get("wildcard")
if wc:
    st.divider()
    st.markdown("### 🌌 Weekly Wildcard")
    wc_price = safe_float(wc.get("current_price", 0))
    st.markdown(f"""
    <div style='background:linear-gradient(135deg,#0f172a,#1e3a5f);border-radius:12px;padding:20px'>
      <div style='font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px'>Space & Quantum — Weekly Pick</div>
      <div style='font-size:24px;font-weight:700;color:#f1f5f9;margin:6px 0'>{wc.get('symbol','')} <span style='font-size:15px;color:#94a3b8'>{wc.get('name','')}</span> <span style='color:#34d399'>${wc_price:.2f}</span></div>
      <div style='font-size:14px;color:#cbd5e1;line-height:1.7;margin:8px 0'>{wc.get('why_interesting','')}</div>
      <div style='display:flex;gap:10px;flex-wrap:wrap;margin-top:8px'>
        {"<div style='background:rgba(52,211,153,0.15);padding:6px 12px;border-radius:6px;font-size:12px;color:#6ee7b7'>🚀 "+wc['catalyst']+"</div>" if wc.get('catalyst') else ""}
        {"<div style='background:rgba(239,68,68,0.15);padding:6px 12px;border-radius:6px;font-size:12px;color:#fca5a5'>⚠️ "+wc['risk']+"</div>" if wc.get('risk') else ""}
      </div>
    </div>
    """, unsafe_allow_html=True)

# ── הזדמנויות מהסורק ────────────────────────────────────────────────────
st.divider()
st.markdown("### 🎯 הזדמנויות — סריקה שעתית")

scan = load_scan()
sc1, sc2 = st.columns([4, 1])
with sc2:
    if st.button("🔍 סרוק עכשיו", help="מריץ סריקה + Claude (~30 שניות)"):
        with st.spinner("סורק שוק וממתין ל-Claude..."):
            try:
                from scanner import run_scan
                scan = run_scan()
                st.success("✅ סריקה הושלמה")
                st.rerun()
            except Exception as e:
                st.error(f"שגיאה: {e}")

if scan is None:
    st.info("אין תוצאות סריקה עדיין — לחץ 'סרוק עכשיו'")
else:
    scanned_at = scan.get("scanned_at", "")[:16].replace("T", " ")
    portfolio_val = scan.get("portfolio_value", 0)
    with sc1:
        st.caption(f"עודכן: {scanned_at} · שווי תיק: ${portfolio_val:,.0f}")

    summary = scan.get("scan_summary", "")
    if summary:
        st.markdown(f"<div style='background:#1e293b;border-radius:8px;padding:12px 16px;font-size:14px;color:#cbd5e1;margin-bottom:12px'>{summary}</div>", unsafe_allow_html=True)

    # הזדמנויות קנייה
    opportunities = scan.get("opportunities", [])
    if opportunities:
        st.markdown("#### 🟢 קנייה")
        opp_cols = st.columns(min(len(opportunities), 3))
        for i, opp in enumerate(opportunities):
            with opp_cols[i % len(opp_cols)]:
                price  = safe_float(opp.get("current_price", 0))
                amount = opp.get("suggested_amount_usd", 0)
                limit  = opp.get("limit_price", 0)
                rsi    = opp.get("rsi", 0)
                w52    = opp.get("w52_high_pct", 0)
                st.markdown(f"""
                <div style='background:#0f2417;border:1px solid #065f46;border-radius:10px;padding:14px'>
                  <div style='font-size:18px;font-weight:700;color:#34d399'>{opp.get('symbol','')} <span style='font-size:12px;color:#6ee7b7'>{opp.get('action','BUY')}</span></div>
                  <div style='font-size:12px;color:#94a3b8;margin-bottom:6px'>{opp.get('name','')} · {opp.get('theme','')}</div>
                  <div style='font-size:22px;font-weight:700;color:#f1f5f9'>${price:.2f}</div>
                  <div style='font-size:13px;color:#34d399;margin:6px 0'>💰 קנה ${amount:,.0f}</div>
                  <div style='font-size:12px;color:#93c5fd'>📍 Limit: ${limit:.2f}</div>
                  <div style='font-size:11px;color:#64748b;margin-top:4px'>RSI {rsi:.0f} · {w52:+.0f}% מהשיא</div>
                  <div style='font-size:12px;color:#cbd5e1;margin-top:8px;line-height:1.5'>{opp.get('reason','')}</div>
                </div>
                """, unsafe_allow_html=True)

    # המלצות קיצוץ
    trims = scan.get("trim_suggestions", [])
    if trims:
        st.markdown("#### 🔴 קיצוץ מומלץ")
        for t in trims:
            pct = t.get("suggested_sell_pct", 25)
            st.markdown(f"""
            <div style='background:#1a0a0a;border:1px solid #7f1d1d;border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;gap:16px'>
              <div style='font-size:18px;font-weight:700;color:#f87171;min-width:60px'>{t.get('symbol','')}</div>
              <div style='flex:1;font-size:13px;color:#fca5a5'>{t.get('reason','')}</div>
              <div style='font-size:14px;font-weight:700;color:#f87171;white-space:nowrap'>מכור {pct}%</div>
            </div>
            """, unsafe_allow_html=True)

# ── Footer ───────────────────────────────────────────────────────────────
st.divider()
analysis_time = analysis.get("fetched_at", "לא ידוע")
st.caption(f"⚠️ לא ייעוץ פיננסי · נתוני ניתוח מ: {analysis_time} · מחירים מתעדכנים כל {REFRESH_SEC} שניות")

# Auto-rerun
time.sleep(REFRESH_SEC)
st.rerun()
