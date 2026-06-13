# dashboard.py — דשבורד מניות חי
# הפעלה: python -m streamlit run dashboard.py

import os
import json
import time
import math
from datetime import datetime

import hashlib
import hmac
import base64
import urllib.parse
import requests
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

SWING_FILE   = os.path.join(BASE_DIR, "swing_trades.json")
HISTORY_FILE = os.path.join(BASE_DIR, "swing_history.json")

GITHUB_REPO = "idosh160-cloud/stock-agent"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

@st.cache_data(ttl=60)
def _fetch_github_json(filename):
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        headers["Cache-Control"] = "no-cache"
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}",
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            import base64
            return json.loads(base64.b64decode(r.json()["content"]).decode())
    except Exception:
        pass
    return None

def load_crypto():
    data = _fetch_github_json("last_crypto.json")
    if data:
        return data
    if not os.path.exists(CRYPTO_FILE):
        return None
    try:
        with open(CRYPTO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_swings():
    data = _fetch_github_json("swing_trades.json")
    if data is not None:
        return data
    if not os.path.exists(SWING_FILE):
        return []
    try:
        with open(SWING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def load_history():
    data = _fetch_github_json("swing_history.json")
    if data is not None:
        return data
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def fetch_live_prices(symbols, json_fallback=None):
    """מחירים חיים / טרום-מסחר / סגירה אחרונה. אם yfinance נכשל — fallback מה-JSON."""
    prices = {}
    fb = {r["symbol"]: r for r in (json_fallback or [])}
    for sym in symbols:
        try:
            t    = yf.Ticker(sym)
            info = t.info
            pre  = safe_float(info.get("preMarketPrice") or info.get("postMarketPrice"))
            reg  = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            prev = safe_float(info.get("previousClose") or reg)
            if pre > 0:
                p, is_ext = pre, True
            elif reg > 0:
                p, is_ext = reg, False
            else:
                hist  = t.history(period="2d")
                p     = safe_float(hist["Close"].iloc[-1]) if len(hist) > 0 else 0
                is_ext = False
            if p > 0:
                chg = round((p - prev) / prev * 100, 2) if prev else 0
                prices[sym] = {"price": round(p, 2), "change_pct": chg, "extended": is_ext}
                continue
        except Exception:
            pass
        # fallback מה-JSON
        if sym in fb and fb[sym].get("current_price", 0) > 0:
            fp = safe_float(fb[sym]["current_price"])
            prices[sym] = {"price": fp, "change_pct": safe_float(fb[sym].get("daily_change_pct", 0)), "extended": False}
        else:
            prices[sym] = {"price": 0, "change_pct": 0, "extended": False}
    return prices

# ── Kraken direct API ────────────────────────────────────────────────────

def _kraken_keys():
    # נסה st.secrets קודם (Streamlit Cloud / local secrets.toml)
    try:
        k = st.secrets.get("KRAKEN_API_KEY")
        s = st.secrets.get("KRAKEN_PRIVATE_KEY")
        if k and s:
            return k, s
    except Exception:
        pass
    # fallback — קרא ישירות מ-.env
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        k = s = None
        with open(env_path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                key, val = line.split("=", 1)
                if key.strip() == "KRAKEN_API_KEY":
                    k = val.strip()
                elif key.strip() == "KRAKEN_PRIVATE_KEY":
                    s = val.strip()
        return k, s
    except Exception:
        return None, None

def _kraken_private(endpoint: str, data: dict = None) -> dict:
    api_key, api_secret = _kraken_keys()
    if not api_key:
        return {}
    data = data or {}
    data["nonce"] = str(int(time.time() * 1000))
    encoded  = urllib.parse.urlencode(data).encode()
    secret   = api_secret + "=" * (-len(api_secret) % 4)
    decoded  = base64.b64decode(secret)
    msg      = endpoint.encode() + hashlib.sha256(data["nonce"].encode() + encoded).digest()
    sig      = base64.b64encode(hmac.new(decoded, msg, hashlib.sha512).digest()).decode()
    try:
        r = requests.post(
            f"https://api.kraken.com{endpoint}",
            headers={"API-Key": api_key, "API-Sign": sig},
            data=data, timeout=8
        )
        result = r.json()
        if result.get("error"):
            return {}
        return result.get("result", {})
    except Exception:
        return {}

@st.cache_data(ttl=30)
def kraken_get_balance() -> dict:
    import re as _re
    raw = _kraken_private("/0/private/Balance")
    if not raw:
        return {}
    name_map = {
        "ZUSD": "USD", "XXBT": "BTC", "XETH": "ETH", "XXRP": "XRP",
        "USDC": "USDC", "ADA": "ADA", "XADA": "ADA",
    }
    result = {}
    for k, v in raw.items():
        val = float(v)
        if val < 0.00001:
            continue
        # נרמל staking: ETH2.S → ETH, SOL03.S → SOL
        normalized = _re.sub(r'\d*\.S$', '', k)
        normalized = name_map.get(normalized, normalized.lstrip("X"))
        if normalized in ("HOLD", "USD.HOLD"):
            continue
        if normalized in result:
            result[normalized] = round(result[normalized] + val, 8)
        else:
            result[normalized] = round(val, 8)
    return result

@st.cache_data(ttl=30)
def kraken_get_open_orders() -> list:
    raw = _kraken_private("/0/private/OpenOrders")
    orders = raw.get("open", {})
    _PAIR_COIN = {
        "ETHUSDC": "ETH", "XRPUSDC": "XRP", "XBTUSDC": "BTC",
        "SOLUSDC": "SOL", "ADAUSDC": "ADA", "AVAXUSDC": "AVAX",
        "LINKUSDC": "LINK", "DOTUSDC": "DOT", "LTCUSDC": "LTC",
        "BCHUSDC": "BCH", "ALGOUSDC": "ALGO", "ATOMUSDC": "ATOM",
        "XTZUSDC": "XTZ",
    }
    out = []
    for txid, o in orders.items():
        d    = o.get("descr", {})
        pair = d.get("pair", "")
        coin = _PAIR_COIN.get(pair, pair.replace("USDC","").replace("XBT","BTC"))
        out.append({
            "txid":   txid,
            "coin":   coin,
            "side":   d.get("type", ""),
            "price":  float(d.get("price", 0)),
            "volume": float(o.get("vol", 0)),
            "usd":    round(float(o.get("vol", 0)) * float(d.get("price", 0) or 0), 2),
        })
    return out

@st.cache_data(ttl=300)
def kraken_get_avg_costs() -> dict:
    raw = _kraken_private("/0/private/TradesHistory", {"trades": True})
    trades = raw.get("trades", {})
    _PAIR_COIN = {
        "XETHZUSD": "ETH", "ETHUSDC": "ETH", "XXBTZUSD": "BTC", "XBTUSDC": "BTC",
        "XXRPZUSD": "XRP", "XRPUSDC": "XRP", "SOLUSDC": "SOL", "ADAUSDC": "ADA",
        "XADAZUSD": "ADA", "AVAXUSDC": "AVAX", "LINKUSDC": "LINK", "DOTUSDC": "DOT",
        "LTCUSDC": "LTC", "BCHUSDC": "BCH", "ALGOUSDC": "ALGO", "ATOMUSDC": "ATOM",
        "XTZUSDC": "XTZ",
    }
    def pair_to_coin(pair):
        if pair in _PAIR_COIN:
            return _PAIR_COIN[pair]
        for suffix in ("USDC", "ZUSD", "USD"):
            if pair.endswith(suffix):
                return pair[:-len(suffix)].lstrip("X").replace("XBT","BTC")
        return None

    holdings = {}
    for t in sorted(trades.values(), key=lambda x: float(x.get("time", 0))):
        coin = pair_to_coin(t.get("pair",""))
        if not coin:
            continue
        vol, price, side = float(t.get("vol",0)), float(t.get("price",0)), t.get("type","")
        h = holdings.setdefault(coin, {"vol": 0.0, "cost": 0.0})
        if side == "buy":
            h["vol"] += vol; h["cost"] += vol * price
        elif side == "sell" and h["vol"] > 0:
            ratio = min(vol / h["vol"], 1.0)
            h["cost"] -= h["cost"] * ratio
            h["vol"]   = max(0.0, h["vol"] - vol)
    result = {c: round(h["cost"]/h["vol"], 6) for c,h in holdings.items() if h["vol"] > 0.0001 and h["cost"] > 0}
    # מזג עם מחירים ידניים (לפוזיציות שנרכשו מחוץ לבוט)
    manual_path = os.path.join(BASE_DIR, "crypto_manual_costs.json")
    try:
        with open(manual_path, encoding="utf-8") as f:
            manual = json.load(f)
        for coin, v in manual.items():
            if coin.startswith("_"):
                continue
            avg = v.get("avg_cost", 0) if isinstance(v, dict) else float(v)
            if avg and avg > 0 and coin not in result:
                result[coin] = avg
    except Exception:
        pass
    return result

@st.cache_data(ttl=15)
def kraken_get_prices(coins: tuple) -> dict:
    _COIN_PAIR = {
        "BTC": "XBTUSDC", "ETH": "ETHUSDC", "XRP": "XRPUSDC",
        "SOL": "SOLUSDC", "ADA": "ADAUSDC", "AVAX": "AVAXUSDC",
        "LINK": "LINKUSDC", "DOT": "DOTUSDC", "LTC": "LTCUSDC",
        "BCH": "BCHUSDC", "ALGO": "ALGOUSDC", "ATOM": "ATOMUSDC", "XTZ": "XTZUSDC",
        "DOGE": "XDGUSDC", "XMR": "XMRUSDC", "BNB": "BNBUSDC",
        "TON": "TONUSDC", "SHIB": "SHIBUSDC", "MANA": "MANAUSDC", "VET": "VETUSDC",
    }
    needed = {c: _COIN_PAIR[c] for c in coins if c in _COIN_PAIR}
    if not needed:
        return {}
    try:
        r   = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={','.join(needed.values())}", timeout=8)
        res = r.json().get("result", {})
        out = {}
        for coin, kpair in needed.items():
            t = res.get(kpair, {})
            if t:
                p, o = float(t["c"][0]), float(t["o"])
                out[coin] = {
                    "price":      p,
                    "change_pct": round((p - o) / o * 100, 2) if o else 0,
                    "high_24h":   float(t["h"][1]),
                    "low_24h":    float(t["l"][1]),
                    "vol_24h":    float(t["v"][1]),
                }
        return out
    except Exception:
        return {}

def fetch_kraken_prices(pairs: dict) -> dict:
    """מחירים חיים מ-Kraken API פומבי. pairs = {"BTC": "XBTUSDC", ...}"""
    try:
        pair_str = ",".join(pairs.values())
        r = requests.get(
            f"https://api.kraken.com/0/public/Ticker?pair={pair_str}",
            timeout=6
        )
        data = r.json().get("result", {})
        prices = {}
        for coin, kpair in pairs.items():
            ticker = data.get(kpair) or data.get(kpair.upper())
            if ticker:
                prices[coin] = {
                    "price": float(ticker["c"][0]),
                    "high":  float(ticker["h"][1]),
                    "low":   float(ticker["l"][1]),
                    "vol":   float(ticker["v"][1]),
                    "change_pct": round((float(ticker["c"][0]) - float(ticker["o"])) / float(ticker["o"]) * 100, 2)
                        if float(ticker["o"]) else 0,
                }
        return prices
    except Exception:
        return {}

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
        ts            = datetime.now().strftime("%Y-%m-%d %H:%M")
        balance       = crypto.get("balance", {})
        portfolio_usd = crypto.get("portfolio_usd", 0)
        usdc          = crypto.get("usdc", 0)
        signals       = crypto.get("signals", [])
        open_orders   = crypto.get("open_orders", [])
        trades        = crypto.get("recent_trades", [])
        params        = crypto.get("params", {})

        # ── נתוני Kraken: private (balance/orders/avg) + public (מחירים) ──
        # Private — balance ופקודות
        live_balance = kraken_get_balance()
        if live_balance:
            live_orders = kraken_get_open_orders()
            avg_costs   = kraken_get_avg_costs()
        else:
            # fallback לנתוני JSON
            raw_bal   = crypto.get("balance", {})
            name_map  = {"XXBT":"BTC","XETH":"ETH","XXRP":"XRP"}
            live_balance = {name_map.get(k,k): round(float(v),8)
                            for k,v in raw_bal.items()
                            if float(v) > 0.00001 and "." not in k}
            live_orders = open_orders
            avg_costs   = {}

        # Public — מחירים חיים לכל מטבע בבאלנס (תמיד, ללא auth)
        non_stable  = [c for c in live_balance if c not in ("USDC","USD")]
        live_prices = kraken_get_prices(tuple(sorted(non_stable)))

        usdc          = safe_float(live_balance.get("USDC", 0)) + safe_float(live_balance.get("USD", 0))
        portfolio_usd = usdc + sum(
            safe_float(live_balance.get(c, 0)) * live_prices.get(c, {}).get("price", 0)
            for c in non_stable
        )
        live_crypto = live_prices

        # ── בנה פוזיציות מבאלנס חי ──────────────────────────────────────
        pos_map = {}
        for coin, qty in live_balance.items():
            if coin in ("USDC","USD") or safe_float(qty) < 0.00001:
                continue
            px     = live_prices.get(coin, {})
            price_now = px.get("price", 0)
            qty_f  = safe_float(qty)
            val    = round(qty_f * price_now, 2)
            avg    = avg_costs.get(coin)
            pnl_usd = round((price_now - avg) * qty_f, 2) if avg else None
            pnl_pct = round((price_now - avg) / avg * 100, 2) if avg else None
            pos_map[coin] = {
                "coin": coin, "qty": qty_f, "price": price_now,
                "value": val, "avg_cost": avg,
                "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                "change_24h": px.get("change_pct", 0),
                "high_24h":   px.get("high_24h", 0),
                "low_24h":    px.get("low_24h", 0),
                "pending_qty": 0, "pending_usd": 0,
            }
        for o in live_orders:
            coin = o.get("coin","")
            if o.get("side") != "buy" or not coin:
                continue
            if coin not in pos_map:
                pos_map[coin] = {
                    "coin": coin, "qty": 0, "price": safe_float(o.get("price",0)),
                    "value": 0, "avg_cost": None, "pnl_usd": None, "pnl_pct": None,
                    "change_24h": 0, "high_24h": 0, "low_24h": 0,
                    "pending_qty": 0, "pending_usd": 0,
                }
            pos_map[coin]["pending_qty"] += safe_float(o.get("volume",0))
            pos_map[coin]["pending_usd"] += safe_float(o.get("usd",0))
        positions = sorted(pos_map.values(), key=lambda x: x["value"] + x["pending_usd"], reverse=True)

        invested_usd  = sum(p["value"] + p.get("pending_usd", 0) for p in positions)
        today_str     = datetime.now().strftime("%Y-%m-%d")
        today_pnl     = sum(safe_float(t.get("usd", 0)) * (1 if t.get("action") == "SELL" else -1)
                            for t in trades if t.get("date", "")[:10] == today_str)
        today_count   = sum(1 for t in trades if t.get("date", "")[:10] == today_str)

        # ── כותרת + רענון ────────────────────────────────────────────────
        hdr_l, hdr_r = st.columns([4, 1])
        with hdr_l:
            invested_label = f"${invested_usd:,.2f}" if invested_usd > 0 else "—"
            change_24h_str = ""
            if live_crypto:
                weighted_chg = sum(
                    live_crypto[c]["change_pct"] * pos_map[c]["value"]
                    for c in live_crypto if c in pos_map and pos_map[c]["value"] > 0
                )
                total_val = sum(pos_map[c]["value"] for c in live_crypto if c in pos_map)
                if total_val > 0:
                    avg_chg = weighted_chg / total_val
                    chg_color = "#34d399" if avg_chg >= 0 else "#f87171"
                    change_24h_str = f"<span style='font-size:15px;color:{chg_color};margin-left:10px'>{'+' if avg_chg>=0 else ''}{avg_chg:.2f}% היום</span>"
            st.markdown(f"""
            <div style='background:linear-gradient(135deg,#0f172a,#1e1f3a);border-radius:16px;padding:20px 24px;margin-bottom:8px;border:1px solid #1e293b'>
              <div style='font-size:11px;color:#475569;text-transform:uppercase;letter-spacing:3px;margin-bottom:6px'>Crypto Portfolio</div>
              <div style='display:flex;align-items:baseline;gap:10px'>
                <span style='font-size:40px;font-weight:900;color:#f1f5f9'>${portfolio_usd:,.2f}</span>
                {change_24h_str}
              </div>
              <div style='display:flex;gap:24px;margin-top:12px'>
                <div><span style='color:#475569;font-size:11px'>מושקע</span><br><span style='color:#94a3b8;font-weight:600'>{invested_label}</span></div>
                <div><span style='color:#475569;font-size:11px'>USDC פנוי</span><br><span style='color:#94a3b8;font-weight:600'>${usdc:,.2f}</span></div>
                <div><span style='color:#475569;font-size:11px'>עסקאות היום</span><br><span style='color:#94a3b8;font-weight:600'>{today_count}</span></div>
                <div><span style='color:#475569;font-size:11px'>עודכן</span><br><span style='color:#94a3b8;font-size:12px'>{ts}</span></div>
              </div>
            </div>
            """.replace("{portfolio_usd:,.2f}", f"{portfolio_usd:,.2f}"), unsafe_allow_html=True)
        with hdr_r:
            st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
            if st.button("🔄 רענן", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
            st.caption("live · 15ש' cache")

        # ── פוזיציות ─────────────────────────────────────────────────────
        if positions:
            st.markdown("---")
            st.markdown("#### 💼 פוזיציות")
            COLS_PER_ROW = 4
            pos_cols = []
            for i, p in enumerate(positions):
                col_idx = i % COLS_PER_ROW
                if col_idx == 0:
                    row_items = positions[i:i + COLS_PER_ROW]
                    pos_cols = st.columns(len(row_items))
                with pos_cols[col_idx]:
                    coin        = p["coin"]
                    qty         = p["qty"]
                    price_p     = p["price"]
                    val         = p["value"]
                    avg         = p["avg_cost"]
                    pnl_usd     = p["pnl_usd"]
                    pnl_pct     = p["pnl_pct"]
                    pending_qty = p.get("pending_qty", 0)
                    pending_usd = p.get("pending_usd", 0)
                    chg24  = p.get("change_24h", 0) or 0
                    high24 = p.get("high_24h", 0) or 0
                    low24  = p.get("low_24h", 0) or 0

                    pnl_color = "#34d399" if (pnl_usd or 0) >= 0 else "#f87171"
                    pnl_bg    = "#082318" if (pnl_usd or 0) >= 0 else "#230808"
                    chg_color = "#34d399" if chg24 >= 0 else "#f87171"
                    coin_icons = {"BTC": "₿", "ETH": "Ξ", "XRP": "✕", "ADA": "₳"}
                    icon = coin_icons.get(coin, "●")

                    pending_html = f"""
                    <div style='background:#1c1c0a;border:1px dashed #854d0e;border-radius:8px;padding:8px 12px;margin-top:8px'>
                      <div style='font-size:10px;color:#854d0e;font-weight:600;margin-bottom:4px'>⏳ ממתין למילוי</div>
                      <div style='display:flex;justify-content:space-between'>
                        <span style='color:#fbbf24;font-size:12px'>{pending_qty:.6f} {coin}</span>
                        <span style='color:#fbbf24;font-size:12px;font-weight:700'>${pending_usd:,.2f}</span>
                      </div>
                    </div>""" if pending_qty > 0 else ""

                    avg_val_str = f"${avg:,.4f}" if avg else "לא ידוע"
                    avg_color   = "#94a3b8" if avg else "#475569"
                    avg_row = f"<div style='display:flex;justify-content:space-between;margin-top:5px;padding-top:5px;border-top:1px solid #1e293b'><span style='color:#475569;font-size:10px'>כניסה ממוצעת</span><span style='color:{avg_color};font-size:11px'>{avg_val_str}</span></div>"

                    pnl_html = f"""
                    <div style='background:{pnl_bg};border-radius:8px;padding:8px 12px;margin-top:8px;display:flex;justify-content:space-between'>
                      <div>
                        <div style='color:#475569;font-size:10px'>P&L</div>
                        <div style='color:{pnl_color};font-size:14px;font-weight:700'>{'+' if (pnl_usd or 0)>=0 else ''}${abs(pnl_usd):,.2f}</div>
                      </div>
                      <div style='text-align:right'>
                        <div style='color:#475569;font-size:10px'>&nbsp;</div>
                        <div style='color:{pnl_color};font-size:14px;font-weight:700'>{'+' if (pnl_pct or 0)>=0 else ''}{pnl_pct:.1f}%</div>
                      </div>
                    </div>""" if pnl_usd is not None else ""

                    high_low = f"<div style='display:flex;justify-content:space-between;margin-top:4px'><span style='color:#475569;font-size:10px'>24H L: ${low24:,.2f}</span><span style='color:#475569;font-size:10px'>H: ${high24:,.2f}</span></div>" if high24 else ""

                    st.markdown(f"""
                    <div style='background:#1e293b;border-radius:16px;padding:18px;border:1px solid #334155;margin-bottom:4px'>
                      <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>
                        <span style='font-size:26px;font-weight:900;color:#f1f5f9'>{icon} {coin}</span>
                        <div style='text-align:right'>
                          <div style='font-size:20px;font-weight:700;color:#e2e8f0'>${price_p:,.4f}</div>
                          <div style='font-size:11px;color:{chg_color}'>{'+' if chg24>=0 else ''}{chg24:.2f}% היום</div>
                        </div>
                      </div>
                      {high_low}
                      <div style='background:#0f172a;border-radius:10px;padding:12px;margin-top:10px'>
                        <div style='display:flex;justify-content:space-between'>
                          <span style='color:#475569;font-size:11px'>כמות מוחזקת</span>
                          <span style='color:#e2e8f0;font-size:13px;font-weight:600'>{qty:.6f} {coin}</span>
                        </div>
                        <div style='display:flex;justify-content:space-between;margin-top:6px'>
                          <span style='color:#475569;font-size:11px'>שווי נוכחי</span>
                          <span style='color:#f1f5f9;font-size:16px;font-weight:800'>${val:,.2f}</span>
                        </div>
                        {avg_row}
                      </div>
                      {pnl_html}
                      {pending_html}
                    </div>
                    """, unsafe_allow_html=True)

        # ── אנליזה לכל מטבע ──────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 📊 אנליזה שוק")
        sig_cols = st.columns(len(signals)) if signals else []
        for i, s in enumerate(signals):
            with sig_cols[i]:
                action     = s["action"]
                rsi        = s["rsi"]
                price_s    = s["price"]
                coin       = s["coin"]
                buy_score  = s.get("buy_score", 0)
                sell_score = s.get("sell_score", 0)
                ma50       = s.get("ma50", 0)
                ma200      = s.get("ma200", 0)
                support    = s.get("support", 0)
                resistance = s.get("resistance", 0)
                reasons    = s.get("reasons", [])

                rsi_pct   = min(max(rsi, 0), 100)
                rsi_color = "#f87171" if rsi < 40 else "#34d399" if rsi > 60 else "#fbbf24"
                action_color = "#34d399" if "BUY" in action else "#f87171" if "SELL" in action else "#64748b"
                action_bg    = "#064e3b" if "BUY" in action else "#7f1d1d" if "SELL" in action else "#1e293b"
                score_bars = "".join([
                    f"<div style='width:{min(buy_score/6*100,100):.0f}%;height:4px;background:#34d399;border-radius:2px;margin-bottom:2px'></div>",
                    f"<div style='width:{min(sell_score/6*100,100):.0f}%;height:4px;background:#f87171;border-radius:2px'></div>",
                ])
                reasons_html = "".join([
                    f"<div style='font-size:10px;color:#64748b;margin:1px 0'>• {r}</div>"
                    for r in reasons[:4]
                ])

                st.markdown(f"""
                <div style='background:#1e293b;border-radius:14px;padding:16px;border:1px solid #334155'>
                  <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'>
                    <span style='font-size:20px;font-weight:900;color:#f1f5f9'>{coin}</span>
                    <span style='background:{action_bg};color:{action_color};padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700'>{action}</span>
                  </div>
                  <div style='font-size:22px;font-weight:700;color:#e2e8f0;margin-bottom:10px'>${price_s:,.4f}</div>

                  <div style='background:#0f172a;border-radius:8px;padding:10px 12px;margin-bottom:10px'>
                    <div style='display:flex;justify-content:space-between;margin-bottom:4px'>
                      <span style='color:#64748b;font-size:11px'>RSI</span>
                      <span style='color:{rsi_color};font-size:13px;font-weight:700'>{rsi:.1f}</span>
                    </div>
                    <div style='background:#1e293b;border-radius:4px;height:6px;overflow:hidden'>
                      <div style='width:{rsi_pct:.0f}%;height:100%;background:{rsi_color};border-radius:4px'></div>
                    </div>
                    <div style='display:flex;justify-content:space-between;margin-top:8px'>
                      <span style='color:#64748b;font-size:10px'>MA50: ${ma50:,.0f}</span>
                      <span style='color:#64748b;font-size:10px'>MA200: ${ma200:,.0f}</span>
                    </div>
                  </div>

                  <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
                    <div style='text-align:center'>
                      <div style='font-size:10px;color:#64748b'>ציון קנייה</div>
                      <div style='font-size:18px;font-weight:700;color:#34d399'>{buy_score}</div>
                    </div>
                    <div style='text-align:center'>
                      <div style='font-size:10px;color:#64748b'>תמיכה</div>
                      <div style='font-size:12px;font-weight:600;color:#94a3b8'>${support:,.2f}</div>
                    </div>
                    <div style='text-align:center'>
                      <div style='font-size:10px;color:#64748b'>התנגדות</div>
                      <div style='font-size:12px;font-weight:600;color:#94a3b8'>${resistance:,.2f}</div>
                    </div>
                    <div style='text-align:center'>
                      <div style='font-size:10px;color:#64748b'>ציון מכירה</div>
                      <div style='font-size:18px;font-weight:700;color:#f87171'>{sell_score}</div>
                    </div>
                  </div>
                  {score_bars}
                  <div style='margin-top:8px'>{reasons_html}</div>
                </div>
                """, unsafe_allow_html=True)

        # ── עסקאות אחרונות ────────────────────────────────────────────────
        st.markdown("---")
        tab_trades, tab_history = st.tabs(["🔄 עסקאות אחרונות", "📋 היסטוריה"])
        with tab_trades:
         if trades:
            all_trades = list(reversed(trades))[:15]
            for t in all_trades:
                action  = t.get("action", "")
                coin    = t.get("coin", "")
                price_t = t.get("price", 0)
                vol     = t.get("volume", 0)
                usd     = t.get("usd", 0)
                rsi_t   = t.get("rsi", 0)
                dt      = t.get("date", "")[:16].replace("T", " ")
                pnl     = t.get("pnl_pct")
                bscore  = t.get("buy_score", "")
                is_today = t.get("date", "")[:10] == today_str

                color     = "#34d399" if action == "BUY" else "#f87171"
                bg        = "#0a1f14" if action == "BUY" else "#1f0a0a"
                today_tag = "<span style='background:#1e3a5f;color:#93c5fd;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px'>היום</span>" if is_today else ""
                pnl_html  = f"<span style='color:{'#34d399' if (pnl or 0)>=0 else '#f87171'};font-size:12px;font-weight:600'>{'+' if (pnl or 0)>=0 else ''}{pnl:.1f}%</span>" if pnl is not None else ""

                tc1, tc2 = st.columns([3, 1])
                with tc1:
                    st.markdown(f"""
                    <div style='background:{bg};border:1px solid {'#065f46' if action=='BUY' else '#7f1d1d'};
                                border-radius:10px;padding:12px 16px;margin-bottom:6px'>
                      <span style='color:{color};font-weight:800;font-size:14px'>{'▲' if action=='BUY' else '▼'} {action} {coin}</span>
                      {today_tag}
                      <div style='color:#94a3b8;font-size:12px;margin-top:4px'>{vol:.6f} {coin} @ ${price_t:,.4f}</div>
                      <div style='color:#475569;font-size:11px;margin-top:2px'>RSI {rsi_t:.0f} · ציון {bscore} · {dt[11:]}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with tc2:
                    st.markdown(f"""
                    <div style='background:{bg};border:1px solid {'#065f46' if action=='BUY' else '#7f1d1d'};
                                border-radius:10px;padding:12px 16px;margin-bottom:6px;text-align:right'>
                      <div style='color:#f1f5f9;font-size:15px;font-weight:700'>${usd:.2f}</div>
                      {pnl_html}
                    </div>
                    """, unsafe_allow_html=True)
         else:
            st.info("אין עסקאות עדיין — הבוט ימתין לסיגנל.")
        with tab_history:
            history = load_history()
            if not history:
                st.info("אין עסקאות בארכיון עדיין.")
            else:
                wins   = [h for h in history if h.get("status") == "closed_profit"]
                losses = [h for h in history if h.get("status") == "closed_loss"]
                total_pnl = sum(h.get("pnl_usd", 0) or 0 for h in history if h.get("status","").startswith("closed"))
                wr = round(len(wins) / max(len(wins)+len(losses), 1) * 100)

                # סיכום עליון
                hc1, hc2, hc3, hc4 = st.columns(4)
                hc1.metric("סה\"כ עסקאות", len(history))
                hc2.metric("Win Rate", f"{wr}%")
                hc3.metric("רווח כולל", f"${total_pnl:+.2f}")
                hc4.metric("✅ / ❌", f"{len(wins)} / {len(losses)}")

                st.markdown("---")

                for h in reversed(history):
                    status    = h.get("status", "")
                    coin      = h.get("coin", "")
                    entry     = h.get("entry_price", 0)
                    close_p   = h.get("close_price", 0) or 0
                    pnl_u     = h.get("pnl_usd", 0) or 0
                    pnl_p     = h.get("pnl_pct", 0) or 0
                    collat    = h.get("collateral", 0)
                    leveraged = h.get("leveraged", False)
                    dt_open   = h.get("date_open", "")[:16].replace("T", " ")
                    dt_close  = (h.get("date_close") or "")[:16].replace("T", " ") or "—"
                    reason    = h.get("reasoning", "")[:120]

                    is_profit = status == "closed_profit"
                    is_cancel = status == "cancelled"
                    color  = "#34d399" if is_profit else ("#94a3b8" if is_cancel else "#f87171")
                    bg     = "#0a1f14" if is_profit else ("#1a1a1a" if is_cancel else "#1f0a0a")
                    border = "#065f46" if is_profit else ("#334155" if is_cancel else "#7f1d1d")
                    icon   = "✅" if is_profit else ("⚪" if is_cancel else "❌")
                    lev    = " 2x" if leveraged else ""
                    pnl_sign = "+" if pnl_u >= 0 else ""
                    reason_html = "<div style='color:#475569;font-size:11px;margin-top:8px'>" + reason + "</div>" if reason else ""

                    html = (
                        "<div style='background:" + bg + ";border:1px solid " + border + ";border-radius:12px;padding:14px 18px;margin-bottom:8px'>"
                        "<div style='display:flex;justify-content:space-between;align-items:center'>"
                        "<span style='color:" + color + ";font-size:16px;font-weight:800'>" + icon + lev + " " + coin + "</span>"
                        "<span style='color:#475569;font-size:11px'>$" + str(int(collat)) + " collateral</span>"
                        "<span style='color:" + color + ";font-size:16px;font-weight:800'>" + pnl_sign + "$" + f"{pnl_u:.2f}" + " · " + pnl_sign + f"{pnl_p:.1f}" + "%</span>"
                        "</div>"
                        "<div style='display:flex;gap:20px;margin-top:10px;flex-wrap:wrap'>"
                        "<div><div style='color:#475569;font-size:10px'>כניסה</div><div style='color:#94a3b8;font-size:12px'>$" + f"{entry:.4f}" + "</div></div>"
                        "<div><div style='color:#475569;font-size:10px'>סגירה</div><div style='color:#94a3b8;font-size:12px'>$" + f"{close_p:.4f}" + "</div></div>"
                        "<div><div style='color:#475569;font-size:10px'>נפתחה</div><div style='color:#94a3b8;font-size:12px'>" + dt_open + "</div></div>"
                        "<div><div style='color:#475569;font-size:10px'>נסגרה</div><div style='color:#94a3b8;font-size:12px'>" + dt_close + "</div></div>"
                        "</div>"
                        + reason_html +
                        "</div>"
                    )
                    st.markdown(html, unsafe_allow_html=True)

        # ── פקודות Limit פתוחות ───────────────────────────────────────────
        if live_orders:
            st.markdown("---")
            buys  = [o for o in live_orders if o.get("side") == "buy"]
            sells = [o for o in live_orders if o.get("side") == "sell"]
            st.markdown(f"#### ⏳ פקודות Limit ממתינות &nbsp;<span style='color:#94a3b8;font-size:13px'>({len(buys)} קנייה · {len(sells)} מכירה)</span>", unsafe_allow_html=True)
            oc1, oc2 = st.columns(2)
            for idx, o in enumerate(sells + buys):
                col = oc1 if idx % 2 == 0 else oc2
                side  = o.get("side", "")
                color = "#34d399" if side == "buy" else "#f87171"
                bg    = "#0a1f14" if side == "buy" else "#1f0a0a"
                with col:
                    st.markdown(f"""
                    <div style='background:{bg};border:1px solid {'#065f46' if side=='buy' else '#7f1d1d'};
                                border-radius:10px;padding:12px 16px;margin-bottom:8px'>
                      <div style='display:flex;justify-content:space-between;align-items:center'>
                        <span style='color:{color};font-weight:700;text-transform:uppercase;font-size:13px'>{'▲ BUY' if side=='buy' else '▼ SELL'} {o.get('coin','')}</span>
                        <span style='color:#f1f5f9;font-weight:700;font-size:15px'>${o.get('price',0):,.4f}</span>
                      </div>
                      <div style='color:#64748b;font-size:11px;margin-top:4px'>{o.get('volume',0):.6f} · ${o.get('usd',0):.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)

        # ── Swing Trades ──────────────────────────────────────────────────
        swings     = load_swings()
        open_sw    = [t for t in swings if t.get("status") == "open"]
        closed_sw  = [t for t in reversed(swings) if t.get("status", "").startswith("closed")]
        wins       = [t for t in closed_sw if t.get("status") == "closed_profit"]
        losses     = [t for t in closed_sw if t.get("status") == "closed_loss"]
        total_pnl  = sum(safe_float(t.get("pnl_usd", 0)) for t in closed_sw)

        st.markdown("---")
        sw_header, sw_stats = st.columns([3, 2])
        with sw_header:
            st.markdown("#### 🎲 Swing Trades — סיבובים תנודתיים")
        with sw_stats:
            if closed_sw:
                wr = round(len(wins) / len(closed_sw) * 100)
                pnl_color = "green" if total_pnl >= 0 else "red"
                st.markdown(
                    f"<div style='text-align:right;padding-top:6px'>"
                    f"<span style='color:#94a3b8;font-size:12px'>סה\"כ סגורים: {len(closed_sw)} | "
                    f"✅ {len(wins)} ❌ {len(losses)} | "
                    f"Win rate: {wr}% | </span>"
                    f"<span style='color:{'#34d399' if total_pnl>=0 else '#f87171'};font-weight:700'>"
                    f"P&L: {'+' if total_pnl>=0 else ''}${total_pnl:.2f}</span></div>",
                    unsafe_allow_html=True
                )

        st.caption("🤖 Claude בוחר אלטקוינים תנודתיים פעם בשעה · יעד +5% · stop -2% · $100 לעסקה · מינוף 2x · 19 מטבעות")
        if open_sw:
            st.markdown("**פתוחות:**")
            sw_cols = st.columns(min(len(open_sw), 3))
            for i, t in enumerate(open_sw):
                with sw_cols[i % 3]:
                    coin      = t["coin"]
                    entry     = t["entry_price"]
                    target    = t["target_price"]
                    stop      = t["stop_price"]
                    current   = t.get("current_price", entry)
                    pnl_pct   = t.get("pnl_pct", 0) or 0
                    pnl_usd   = t.get("pnl_usd", 0) or 0
                    reasoning = t.get("reasoning", "")
                    conf      = t.get("confidence", "")
                    dt_open   = t.get("date_open", "")[:16].replace("T", " ")

                    pnl_col = "#34d399" if pnl_pct >= 0 else "#f87171"
                    pnl_bg  = "#082318" if pnl_pct >= 0 else "#230808"
                    # progress: 0% = stop, 100% = target
                    full_range = target - stop
                    progress   = ((current - stop) / full_range * 100) if full_range else 50
                    progress   = max(0, min(100, progress))
                    prog_color = "#34d399" if progress > 50 else "#fbbf24" if progress > 25 else "#f87171"
                    conf_colors = {"HIGH": "#064e3b", "MEDIUM": "#92400e", "LOW": "#4b5563"}
                    conf_bg = conf_colors.get(conf, "#1e293b")

                    MARGIN_ELIGIBLE = {"ETH","SOL","XRP","LTC","BCH","LINK","DOT","ADA","AVAX","BNB","DOGE","XMR","TON"}
                    lev_badge = "<span style='background:#1e3a5f;color:#93c5fd;padding:2px 7px;border-radius:8px;font-size:10px;margin-right:4px'>2x</span>" if coin in MARGIN_ELIGIBLE else ""
                    st.markdown(f"""
                    <div style='background:#1e293b;border-radius:14px;padding:16px;border:1px solid #334155;margin-bottom:8px'>
                      <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px'>
                        <span style='font-size:20px;font-weight:900;color:#f1f5f9'>{lev_badge}{coin}</span>
                        <span style='background:{conf_bg};color:white;padding:2px 8px;border-radius:10px;font-size:10px'>{conf}</span>
                      </div>
                      <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
                        <div><div style='color:#475569;font-size:10px'>כניסה</div><div style='color:#94a3b8;font-size:12px'>${entry:.4f}</div></div>
                        <div style='text-align:center'><div style='color:#475569;font-size:10px'>כעת</div><div style='color:#f1f5f9;font-size:14px;font-weight:700'>${current:.4f}</div></div>
                        <div style='text-align:right'><div style='color:#475569;font-size:10px'>יעד</div><div style='color:#34d399;font-size:12px'>${target:.4f}</div></div>
                      </div>
                      <div style='background:#0f172a;border-radius:6px;height:6px;margin-bottom:8px'>
                        <div style='width:{progress:.0f}%;height:100%;background:{prog_color};border-radius:6px'></div>
                      </div>
                      <div style='display:flex;justify-content:space-between;margin-bottom:8px'>
                        <span style='color:#f87171;font-size:10px'>stop ${stop:.4f}</span>
                        <span style='color:#475569;font-size:10px'>{progress:.0f}% ליעד</span>
                        <span style='color:#34d399;font-size:10px'>+5% = ${target:.4f}</span>
                      </div>
                      <div style='background:{pnl_bg};border-radius:8px;padding:6px 10px;display:flex;justify-content:space-between'>
                        <span style='color:{pnl_col};font-size:13px;font-weight:700'>{'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%</span>
                        <span style='color:{pnl_col};font-size:13px;font-weight:700'>{'+' if pnl_usd>=0 else ''}${pnl_usd:.2f}</span>
                      </div>
                      <div style='font-size:11px;color:#64748b;margin-top:8px;line-height:1.5'>{reasoning[:120]}</div>
                      <div style='font-size:10px;color:#334155;margin-top:4px'>{dt_open}</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            last_scan_file = os.path.join(BASE_DIR, "last_swing_scan.txt")
            last_scan = open(last_scan_file).read().strip() if os.path.exists(last_scan_file) else "לא רץ עדיין"
            st.caption(f"אין פוזיציות פתוחות כרגע — סריקה אחרונה: {last_scan}")

        if closed_sw[:5]:
            with st.expander(f"📋 {len(closed_sw)} סינגים סגורים"):
                for t in closed_sw[:10]:
                    is_win   = t.get("status") == "closed_profit"
                    color    = "#34d399" if is_win else "#f87171"
                    bg       = "#0a1f14" if is_win else "#1f0a0a"
                    icon     = "✅" if is_win else "❌"
                    pnl      = t.get("pnl_usd", 0) or 0
                    pnl_pct  = t.get("pnl_pct", 0) or 0
                    dt_close = (t.get("date_close") or "")[:16].replace("T", " ")
                    entry    = t.get("entry_price", 0)
                    close_p  = t.get("close_price", 0)
                    st.markdown(f"""
                    <div style='background:{bg};border:1px solid {'#065f46' if is_win else '#7f1d1d'};border-radius:8px;
                                padding:10px 14px;margin-bottom:5px;display:flex;justify-content:space-between;align-items:center'>
                      <div>
                        <span style='color:{color};font-weight:700'>{icon} {t['coin']}</span>
                        <span style='color:#64748b;font-size:11px;margin-left:8px'>${entry:.4f} → ${(close_p or 0):.4f}</span>
                      </div>
                      <div style='text-align:right'>
                        <span style='color:{color};font-weight:700'>{'+' if pnl>=0 else ''}${pnl:.2f} ({'+' if pnl_pct>=0 else ''}{pnl_pct:.1f}%)</span>
                        <div style='color:#334155;font-size:10px'>{dt_close}</div>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

        # ── פרמטרים ──────────────────────────────────────────────────────
        with st.expander("⚙️ פרמטרים (אוטו-כוונון שבועי)"):
            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("RSI קנייה", params.get("RSI_BUY", 45))
            pc2.metric("RSI מכירה", params.get("RSI_SELL", 58))
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
            market_summary = analysis.get("market_summary", "")
            if market_summary and "JSON parse error" not in market_summary and "Data unavailable" not in market_summary:
                st.write(market_summary)
            else:
                st.caption("⏳ סיכום שוק יתעדכן בריצה הבאה של הסוכן")
            recap = analysis.get("yesterday_recap", "")
            if recap and "JSON parse error" not in recap:
                st.caption(f"⏮ {recap}")
            rumors = analysis.get("rumors_and_contracts", "")
            if rumors and "JSON parse error" not in rumors:
                st.info(f"🔔 {rumors}")

        us_recs = analysis.get("us_recommendations", [])
        symbols = [r["symbol"] for r in us_recs]

        if "last_refresh" not in st.session_state or time.time() - st.session_state.last_refresh > REFRESH_SEC:
            with st.spinner("מרענן מחירים..."):
                st.session_state.live_prices = fetch_live_prices(symbols, us_recs)
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
                st.session_state.live_prices = fetch_live_prices(symbols, us_recs)
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
