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
CRYPTO_FILE   = os.path.join(BASE_DIR, "last_crypto.json")
REFRESH_SEC   = 60  # רענון מחירים אוטומטי

PORTFOLIO_SHARES = {
    "CIFR": {"shares": 113, "avg_cost": 16.03},
    "FPS":  {"shares": 99,  "avg_cost": 46.61},
    "IBM":  {"shares": 11,  "avg_cost": 314.58},
    "IREN": {"shares": 28,  "avg_cost": 58.95},
    "FORM": {"shares": 8,   "avg_cost": 118.72},
    "DRAM": {"shares": 67,  "avg_cost": 51.97},
}


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

def load_crypto():
    if not os.path.exists(CRYPTO_FILE):
        return None
    try:
        with open(CRYPTO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def fetch_live_prices(symbols):
    """מחירים חיים / טרום-מסחר / סגירה אחרונה"""
    prices = {}
    for sym in symbols:
        try:
            t    = yf.Ticker(sym)
            info = t.info

            # טרום-מסחר / אחרי-מסחר
            pre  = safe_float(info.get("preMarketPrice") or info.get("postMarketPrice"))
            reg  = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            prev = safe_float(info.get("previousClose") or reg)

            if pre > 0:
                p        = pre
                is_ext   = True
            elif reg > 0:
                p        = reg
                is_ext   = False
            else:
                hist = t.history(period="2d")
                p    = safe_float(hist["Close"].iloc[-1]) if len(hist) > 0 else 0
                is_ext = False

            chg = round((p - prev) / prev * 100, 2) if prev else 0
            prices[sym] = {"price": round(p, 2), "change_pct": chg, "extended": is_ext}
        except Exception:
            prices[sym] = {"price": 0, "change_pct": 0, "extended": False}
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


# ── כותרת ───────────────────────────────────────────────────────────────
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("## 📈 Stock & Crypto Dashboard")
with col_time:
    st.markdown(f"<div style='text-align:right;color:#94a3b8;padding-top:10px'>{datetime.now().strftime('%d/%m/%Y %H:%M')}</div>", unsafe_allow_html=True)

tab_stocks, tab_crypto = st.tabs(["📈 מניות US", "₿ קריפטו"])

# ══════════════════════════════════════════════════════════════════════════
# לשונית קריפטו
# ══════════════════════════════════════════════════════════════════════════
with tab_crypto:
    crypto = load_crypto()

    if crypto is None:
        st.info("אין נתוני קריפטו עדיין — הרץ את `python crypto_agent.py` פעם ראשונה.")
    else:
        ts = crypto.get("timestamp", "")[:16].replace("T", " ")
        balance = crypto.get("balance", {})
        portfolio_usd = crypto.get("portfolio_usd", 0)
        usdc = crypto.get("usdc", 0)
        signals = crypto.get("signals", [])
        trades = crypto.get("recent_trades", [])
        params = crypto.get("params", {})

        # ── סיכום ────────────────────────────────────────────────────────
        st.markdown("### ₿ Crypto Portfolio")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("שווי כולל", f"${portfolio_usd:,.2f}")
        mc2.metric("USDC פנוי", f"${usdc:,.2f}")
        mc3.metric("עסקאות היום", str(crypto.get("orders_today", 0)))
        mc4.metric("עודכן", ts)

        st.divider()

        # ── מצב מטבעות ───────────────────────────────────────────────────
        st.markdown("#### מצב נוכחי")
        sig_cols = st.columns(len(signals)) if signals else []
        for i, s in enumerate(signals):
            with sig_cols[i]:
                action = s["action"]
                rsi    = s["rsi"]
                price  = s["price"]
                coin   = s["coin"]
                holding = balance.get(coin, 0)
                holding_usd = holding * price

                rsi_color = "#f87171" if rsi < 35 else "#34d399" if rsi > 65 else "#94a3b8"
                action_color = "#34d399" if action == "BUY" else "#f87171" if action == "SELL" else "#64748b"
                action_bg    = "#064e3b" if action == "BUY" else "#7f1d1d" if action == "SELL" else "#1e293b"

                st.markdown(f"""
                <div style='background:#1e293b;border-radius:12px;padding:16px;text-align:center'>
                  <div style='font-size:24px;font-weight:900;color:#f1f5f9'>{coin}</div>
                  <div style='font-size:20px;font-weight:700;color:#e2e8f0'>${price:,.2f}</div>
                  <div style='margin:8px 0'>
                    <span style='font-size:13px;color:{rsi_color};background:#0f172a;padding:4px 10px;border-radius:6px'>RSI {rsi}</span>
                  </div>
                  <div style='background:{action_bg};color:{action_color};padding:6px 14px;border-radius:20px;font-size:14px;font-weight:700;display:inline-block'>{action}</div>
                  {f"<div style='font-size:11px;color:#64748b;margin-top:8px'>{holding:.6f} {coin}<br>${holding_usd:.2f}</div>" if holding > 0 else ""}
                </div>
                """, unsafe_allow_html=True)

        st.divider()

        # ── היסטוריית עסקאות ─────────────────────────────────────────────
        st.markdown("#### עסקאות אחרונות")
        if trades:
            today_trades = [t for t in reversed(trades) if t.get("date","")[:10] == datetime.now().strftime("%Y-%m-%d")]
            older_trades = [t for t in reversed(trades) if t not in today_trades]
            show_trades  = today_trades + older_trades[:10]

            for t in show_trades:
                action = t.get("action","")
                coin   = t.get("coin","")
                price  = t.get("price", 0)
                vol    = t.get("volume", 0)
                usd    = t.get("usd", 0)
                rsi    = t.get("rsi", 0)
                dt     = t.get("date","")[:16].replace("T"," ")
                pnl    = t.get("pnl_pct")

                icon  = "🟢" if action == "BUY" else "🔴"
                color = "#34d399" if action == "BUY" else "#f87171"
                pnl_str = f" · P&L {pnl:+.1f}%" if pnl is not None else ""

                st.markdown(f"""
                <div style='background:#0f172a;border-left:3px solid {color};border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center'>
                  <div>
                    <span style='color:{color};font-weight:700'>{icon} {action} {coin}</span>
                    <span style='color:#64748b;font-size:12px;margin-left:10px'>{vol:.6f} @ ${price:,.2f}</span>
                    {f"<span style='color:#fbbf24;font-size:12px;margin-left:8px'>{pnl_str}</span>" if pnl is not None else ""}
                  </div>
                  <div style='color:#475569;font-size:12px'>${usd:.2f} · RSI {rsi} · {dt}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("אין עסקאות עדיין — הבוט ימתין לסיגנל RSI.")

        # ── פרמטרים ──────────────────────────────────────────────────────
        with st.expander("⚙️ פרמטרים נוכחיים (אוטו-כוונון שבועי)"):
            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("RSI קנייה", params.get("RSI_BUY", 32))
            pc2.metric("RSI מכירה", params.get("RSI_SELL", 68))
            pc3.metric("מקס עסקה", f"${params.get('MAX_TRADE_USD', 30)}")
            pc4.metric("מקס/יום", params.get("MAX_DAILY_TRADES", 4))

# ══════════════════════════════════════════════════════════════════════════
# לשונית מניות
# ══════════════════════════════════════════════════════════════════════════
with tab_stocks:
    analysis = load_analysis()

    analysis = load_analysis()
    if analysis is None:
        st.warning("⚠️ אין ניתוח זמין — הרץ את הסוכן קודם (`python run.py`)")
    else:
        with st.expander("🌍 סיכום שוק + חדשות", expanded=False):
            st.write(analysis.get("market_summary", ""))
            recap = analysis.get("yesterday_recap", "")
            if recap:
                st.caption(f"⏮ {recap}")
            rumors = analysis.get("rumors_and_contracts", "")
            if rumors:
                st.info(f"🔔 {rumors}")

        us_recs = analysis.get("us_recommendations", [])
        symbols = [r["symbol"] for r in us_recs]

        if "last_refresh" not in st.session_state or time.time() - st.session_state.last_refresh > REFRESH_SEC:
            with st.spinner("מרענן מחירים..."):
                st.session_state.live_prices = fetch_live_prices(symbols)
                st.session_state.last_refresh = time.time()

        live = st.session_state.get("live_prices", {})

        total_current  = 0
        total_original = 0
        for sym, cfg_data in PORTFOLIO_SHARES.items():
            p = safe_float(live.get(sym, {}).get("price", 0))
            if p == 0:
                for r in us_recs:
                    if r.get("symbol") == sym:
                        p = safe_float(r.get("current_price", 0))
                        break
            total_current  += p * cfg_data["shares"]
            total_original += cfg_data["avg_cost"] * cfg_data["shares"]

        total_pnl     = total_current - total_original
        total_pnl_pct = round(total_pnl / total_original * 100, 1) if total_original else 0

        st.markdown("### 💼 US Portfolio")
        c1, c2, c3 = st.columns(3)
        c1.metric("שווי נוכחי", f"${total_current:,.0f}")
        c2.metric("עלות מקורית", f"${total_original:,.0f}")
        c3.metric("P&L כולל", f"${total_pnl:+,.0f}", delta=f"{total_pnl_pct:+.1f}%")

        st.divider()

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

        import re

        def box(label, val_str, sub="", color="#f1f5f9", size="24px"):
            return (
                f"<div style='background:#0f172a;border-radius:10px;padding:10px 16px;min-width:90px'>"
                f"<div style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:1px'>{label}</div>"
                f"<div style='font-size:{size};font-weight:800;color:{color}'>{val_str}</div>"
                f"<div style='font-size:11px;color:{color};opacity:0.8'>{sub}</div>"
                f"</div>"
            )

        for r in us_recs:
            sym      = r["symbol"]
            live_data = live.get(sym, {})
            live_price = safe_float(live_data.get("price", 0))
            is_ext   = live_data.get("extended", False)
            price    = live_price if live_price > 0 else safe_float(r.get("current_price", 0))
            chg      = safe_float(live_data.get("change_pct") or r.get("daily_change_pct", 0))
            cfg_data = PORTFOLIO_SHARES.get(sym, {})
            shares   = safe_float(r.get("shares") or cfg_data.get("shares", 0))
            avg      = safe_float(r.get("avg_cost") or cfg_data.get("avg_cost", 0))
            if shares > 0 and price > 0:
                val      = price * shares
                orig_val = avg * shares
                pnl      = val - orig_val
                pnl_p    = round(pnl / orig_val * 100, 1) if orig_val else 0
            else:
                val      = safe_float(r.get("current_value", 0))
                orig_val = safe_float(r.get("original_value", 0))
                pnl      = safe_float(r.get("pnl_dollars", val - orig_val))
                pnl_p    = safe_float(r.get("pnl_pct", 0))
            action          = r.get("action", "HOLD")
            conf            = r.get("confidence", "MEDIUM")
            target          = r.get("analyst_target")
            upside          = r.get("upside_to_target_pct")
            stock_signals   = r.get("key_signals", [])
            reasoning       = r.get("reasoning", "")
            sec_insight     = r.get("sec_insight", "")
            position_advice = r.get("position_advice", "")
            earnings_date   = r.get("earnings_date", "")
            earnings_exp    = r.get("earnings_expectations", "")
            news_list       = r.get("news", [])[:3] if r.get("news") else []
            ac = ACTION_COLORS.get(action, "#1e293b")

            with st.container():
                st.markdown(f"<div style='border-left:4px solid {ac};background:#1e293b;border-radius:12px;padding:16px 20px;margin-bottom:16px'>", unsafe_allow_html=True)
                hc1, hc2, hc3 = st.columns([2, 2, 1])
                with hc1:
                    ext_badge = "<span style='background:#854d0e;color:#fef08a;padding:2px 7px;border-radius:4px;font-size:10px;margin-left:6px'>טרום-מסחר</span>" if is_ext else ""
                    st.markdown(f"<span style='font-size:28px;font-weight:900;color:#f1f5f9;letter-spacing:1px'>{sym}</span>{ext_badge}<br><span style='color:#e2e8f0;font-size:16px;font-weight:600'>{r.get('name','')}</span>", unsafe_allow_html=True)
                    conf_colors = {"HIGH": "#065f46", "MEDIUM": "#92400e", "LOW": "#4b5563"}
                    cc = conf_colors.get(conf, "#4b5563")
                    st.markdown(f"<span style='background:{ac};color:white;padding:4px 14px;border-radius:20px;font-size:13px;font-weight:700'>{action}</span>&nbsp;<span style='background:{cc};color:white;padding:4px 10px;border-radius:20px;font-size:11px'>{conf}</span>", unsafe_allow_html=True)
                with hc2:
                    chg_col = "#34d399" if chg >= 0 else "#f87171"
                    pnl_col = "#34d399" if pnl >= 0 else "#f87171"
                    price_label_str = "טרום-מסחר" if is_ext else "מחיר נוכחי"
                    chg_sub = (sign(chg)+f"{chg:.2f}% מסגירה אחרונה") if chg != 0 else ""
                    price_html = "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:8px'>"
                    price_html += box(price_label_str, f"${price:.2f}", chg_sub, chg_col, "26px")
                    price_html += box("עלות ממוצעת", f"${avg:.2f}", f"{shares:.0f} מניות", "#94a3b8", "22px")
                    price_html += box("שווי נוכחי", f"${val:,.0f}", "", "#e2e8f0", "22px")
                    price_html += box("רווח/הפסד", sign(pnl)+f"${abs(pnl):,.0f}", sign(pnl_p)+f"{pnl_p}%", pnl_col, "22px")
                    if target:
                        up_col = "#34d399" if (upside or 0) >= 0 else "#f87171"
                        up_dir = "מתחת ליעד" if (upside or 0) >= 0 else "מעל ליעד"
                        price_html += box("יעד אנליסטים", f"${target}", f"{abs(upside or 0):.1f}% {up_dir}", up_col, "20px")
                    price_html += "</div>"
                    st.markdown(price_html, unsafe_allow_html=True)
                    if earnings_date:
                        st.markdown(f"<div style='margin-top:6px;font-size:12px;color:#fbbf24'>📅 דוח רווחים: {earnings_date}{' — '+earnings_exp if earnings_exp else ''}</div>", unsafe_allow_html=True)
                    if news_list:
                        news_html = "<div style='margin-top:6px'>"
                        for n in news_list:
                            title = n.get('headline') or n.get('title','')
                            url   = n.get('url','#')
                            if title:
                                news_html += f"<div style='font-size:11px;color:#64748b;margin:2px 0'>📰 <a href='{url}' target='_blank' style='color:#93c5fd;text-decoration:none'>{title[:80]}</a></div>"
                        news_html += "</div>"
                        st.markdown(news_html, unsafe_allow_html=True)
                with hc3:
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
                if stock_signals:
                    sig_html = ""
                    for s in stock_signals:
                        s_clean = re.sub(r'<[^>]+>', '', str(s)).strip()
                        if not s_clean:
                            continue
                        is_warn = any(w in s_clean.upper() for w in ["WARNING","SELLING","CONCERN","HIGH SHORT","ELEVATED","DEBT","MISS","AVOID","LOSS"])
                        sc = "#f87171" if is_warn else "#6ee7b7"
                        sbg = "#1a0a0a" if is_warn else "#0a1a0a"
                        ic  = "⚠️" if is_warn else "✅"
                        sig_html += f"<div style='background:{sbg};border-radius:6px;padding:5px 10px;margin:2px 0;font-size:12px;color:{sc}'>{ic} {s_clean}</div>"
                    st.markdown(sig_html, unsafe_allow_html=True)
                if sec_insight:
                    st.markdown(f"<div style='background:#0f172a;border-left:3px solid #3b82f6;padding:8px 12px;border-radius:0 6px 6px 0;margin-top:8px;font-size:12px;color:#93c5fd'>📄 {sec_insight}</div>", unsafe_allow_html=True)
                if reasoning:
                    st.markdown(f"<div style='font-size:13px;color:#cbd5e1;margin-top:8px;line-height:1.6'>{reasoning}</div>", unsafe_allow_html=True)
                if position_advice:
                    st.markdown(f"<div style='background:#1c1917;border-radius:6px;padding:8px 12px;font-size:12px;color:#fbbf24;margin-top:6px'>💡 {position_advice}</div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        gems = analysis.get("hidden_gems", [])
        if gems:
            st.divider()
            st.markdown("### 💎 פנינות נסתרות")
            gcols = st.columns(min(len(gems), 3))
            for i, gem in enumerate(gems):
                with gcols[i % len(gcols)]:
                    gp   = safe_float(gem.get("current_price", 0))
                    gain = gem.get("gain_6mo_pct", 0)
                    st.markdown(f"""
                    <div style='background:#1e293b;border-radius:12px;padding:16px;height:100%'>
                      <div style='font-size:18px;font-weight:700;color:#f1f5f9'>{gem.get('symbol','')} <span style='font-size:13px;color:#94a3b8'>{gem.get('name','')}</span></div>
                      <div style='font-size:20px;font-weight:700;color:#34d399;margin:4px 0'>${gp:.2f} <span style='font-size:13px;color:{"#34d399" if gain>=0 else "#f87171"}'>{sign(gain)}{gain}% (6mo)</span></div>
                      <div style='font-size:11px;color:#64748b;margin-bottom:8px'>📂 {gem.get('sector','')}</div>
                      <div style='font-size:13px;color:#cbd5e1;margin-bottom:6px'>💡 {gem.get('why_interesting','')}</div>
                      <div style='font-size:12px;color:#93c5fd'>🤖 {gem.get('ai_infrastructure_angle','')}</div>
                      <div style='font-size:12px;color:#34d399;margin-top:4px'>🚀 {gem.get('catalyst','')}</div>
                      <div style='font-size:12px;color:#f87171;margin-top:2px'>⚠️ {gem.get('risk','')}</div>
                    </div>
                    """, unsafe_allow_html=True)

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

        st.divider()
        st.markdown("### 🎯 הזדמנויות — סריקה ידנית")
        scan = load_scan()
        sc1, sc2 = st.columns([4, 1])
        with sc2:
            if st.button("🔍 סרוק עכשיו"):
                with st.spinner("סורק..."):
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
            with sc1:
                st.caption(f"עודכן: {scanned_at}")
            summary = scan.get("scan_summary", "")
            if summary:
                st.markdown(f"<div style='background:#1e293b;border-radius:8px;padding:12px 16px;font-size:14px;color:#cbd5e1;margin-bottom:12px'>{summary}</div>", unsafe_allow_html=True)
            opportunities = scan.get("opportunities", [])
            if opportunities:
                st.markdown("#### 🟢 קנייה")
                opp_cols = st.columns(min(len(opportunities), 3))
                for i, opp in enumerate(opportunities):
                    with opp_cols[i % len(opp_cols)]:
                        op = safe_float(opp.get("current_price", 0))
                        st.markdown(f"""
                        <div style='background:#0f2417;border:1px solid #065f46;border-radius:10px;padding:14px'>
                          <div style='font-size:18px;font-weight:700;color:#34d399'>{opp.get('symbol','')} <span style='font-size:12px;color:#6ee7b7'>{opp.get('action','BUY')}</span></div>
                          <div style='font-size:12px;color:#94a3b8;margin-bottom:6px'>{opp.get('name','')} · {opp.get('theme','')}</div>
                          <div style='font-size:22px;font-weight:700;color:#f1f5f9'>${op:.2f}</div>
                          <div style='font-size:13px;color:#34d399;margin:6px 0'>💰 קנה ${opp.get('suggested_amount_usd',0):,.0f}</div>
                          <div style='font-size:12px;color:#93c5fd'>📍 Limit: ${opp.get('limit_price',0):.2f}</div>
                          <div style='font-size:11px;color:#64748b;margin-top:4px'>RSI {opp.get('rsi',0):.0f}</div>
                          <div style='font-size:12px;color:#cbd5e1;margin-top:8px;line-height:1.5'>{opp.get('reason','')}</div>
                        </div>
                        """, unsafe_allow_html=True)
            trims = scan.get("trim_suggestions", [])
            if trims:
                st.markdown("#### 🔴 קיצוץ מומלץ")
                for t in trims:
                    st.markdown(f"""
                    <div style='background:#1a0a0a;border:1px solid #7f1d1d;border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;gap:16px'>
                      <div style='font-size:18px;font-weight:700;color:#f87171;min-width:60px'>{t.get('symbol','')}</div>
                      <div style='flex:1;font-size:13px;color:#fca5a5'>{t.get('reason','')}</div>
                      <div style='font-size:14px;font-weight:700;color:#f87171;white-space:nowrap'>מכור {t.get('suggested_sell_pct',25)}%</div>
                    </div>
                    """, unsafe_allow_html=True)

        st.divider()
        analysis_time = analysis.get("fetched_at", "לא ידוע")
        st.caption(f"⚠️ לא ייעוץ פיננסי · נתוני ניתוח מ: {analysis_time} · מחירים מתעדכנים כל {REFRESH_SEC} שניות")

# Auto-rerun
time.sleep(REFRESH_SEC)
st.rerun()
