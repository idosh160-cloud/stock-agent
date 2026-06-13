"""
swing_trader.py — מסחר תנודתי חכם עם Claude
כל שעה: Claude בוחר מטבעות + xStocks לסיבובים קצרים
כל 15 דק': בודק פוזיציות פתוחות — מוכר ב-+5% (קריפטו) / +2% (מניות) או עוצר ב-2%/-1%
"""
import os
import json
import logging
import requests
from datetime import datetime

DIR          = os.path.dirname(os.path.abspath(__file__))
SWING_FILE   = os.path.join(DIR, "swing_trades.json")
HISTORY_FILE = os.path.join(DIR, "swing_history.json")

SWING_USD         = 100    # דולר לכל עסקה קריפטו (collateral — שולטים ב-$200 עם מינוף 2x)
SWING_USD_STOCK   = 75     # דולר לכל עסקת מניה (ללא מינוף)
TARGET_PCT        = 0.05   # +5% יעד רווח קריפטו
TARGET_PCT_STOCK  = 0.07   # +7% יעד רווח xStocks — מניות תנודתיות יכולות לעשות הרבה יותר
STOP_PCT          = 0.02   # -2% עצור הפסד קריפטו
STOP_PCT_STOCK    = 0.015  # -1.5% עצור הפסד xStocks
MAX_OPEN          = 6      # פוזיציות פתוחות מקסימום
MAX_BUDGET        = 600    # תקציב מקסימלי לסווינגים
LEVERAGE          = 2      # מינוף x2 על כל קנייה (Kraken margin) — לא למניות

# מטבעות שקרקן מאפשר עליהם margin trading
MARGIN_ELIGIBLE = {"ETH", "SOL", "XRP", "LTC", "BCH", "LINK", "DOT", "ADA", "AVAX", "BNB", "DOGE", "XMR", "TON"}

# Pairs שאומתו ב-Kraken + מינימום נפח + דיוק מחיר
CANDIDATES = {
    "ETH":  {"pair": "ETHUSDC",  "min_vol": 0.004, "price_dec": 2},
    "SOL":  {"pair": "SOLUSDC",  "min_vol": 0.06,  "price_dec": 2},
    "XRP":  {"pair": "XRPUSDC",  "min_vol": 10,    "price_dec": 4},
    "ADA":  {"pair": "ADAUSDC",  "min_vol": 20,    "price_dec": 6},
    "AVAX": {"pair": "AVAXUSDC", "min_vol": 0.5,   "price_dec": 3},
    "LINK": {"pair": "LINKUSDC", "min_vol": 0.55,  "price_dec": 5},
    "DOT":  {"pair": "DOTUSDC",  "min_vol": 3.9,   "price_dec": 4},
    "LTC":  {"pair": "LTCUSDC",  "min_vol": 0.1,   "price_dec": 3},
    "BCH":  {"pair": "BCHUSDC",  "min_vol": 0.01,  "price_dec": 2},
    "ALGO": {"pair": "ALGOUSDC", "min_vol": 41,    "price_dec": 5},
    "ATOM": {"pair": "ATOMUSDC", "min_vol": 2.5,   "price_dec": 4},
    "XTZ":  {"pair": "XTZUSDC",  "min_vol": 13,    "price_dec": 5},
    "BNB":  {"pair": "BNBUSDC",  "min_vol": 0.07,  "price_dec": 2},
    "TON":  {"pair": "TONUSDC",  "min_vol": 3,     "price_dec": 4},
    "SHIB": {"pair": "SHIBUSDC", "min_vol": 500000,"price_dec": 8},
    "MANA": {"pair": "MANAUSDC", "min_vol": 20,    "price_dec": 5},
    "VET":  {"pair": "VETUSDC",  "min_vol": 100,   "price_dec": 6},
    "XMR":  {"pair": "XMRUSDC",  "min_vol": 0.05,  "price_dec": 2},
    "DOGE": {"pair": "XDGUSDC",  "min_vol": 50,    "price_dec": 5},
}

# רשימת קריפטו ידועים — כדי לסנן מניות מהם
_KNOWN_CRYPTO = {
    "BTC","ETH","SOL","XRP","ADA","AVAX","LINK","DOT","LTC","BCH","ALGO","ATOM",
    "XTZ","BNB","TON","SHIB","MANA","VET","XMR","DOGE","MATIC","UNI","AAVE","CRV",
    "MKR","COMP","SNX","YFI","SUSHI","GRT","KAVA","MINA","ANKR","OCEAN","SAND",
    "AXS","GALA","ENJ","CHZ","RUNE","NEAR","FLOW","HBAR","EOS","XLM","TRX",
    "THETA","NEO","WAVES","ZIL","QTUM","ONT","ZRX","BAT","OMG","KNC","BAND",
    "STORJ","OXT","CTSI","ALICE","TLM","SXP","REEF","FIL","ICP","LUNA","LUNC",
    "USDT","USDC","DAI","BUSD","TUSD","USDP","FRAX","ZUSD","USD","EUR","GBP",
}


def get_xstock_data() -> list:
    """מושך דינמית את כל ה-xStocks מ-Kraken Futures API"""
    try:
        # שלוף רשימת instruments
        r = requests.get(
            "https://futures.kraken.com/derivatives/api/v3/instruments",
            timeout=15
        )
        instruments = r.json().get("instruments", [])
        # xStocks: PF_TSLAXUSD, PF_NVDAXUSD וכו' — לא קריפטו
        xstock_symbols = [
            i["symbol"] for i in instruments
            if i.get("symbol", "").startswith("PF_")
            and i.get("symbol", "").endswith("XUSD")
            and i.get("tradeable", False)
            and i["symbol"].replace("PF_", "").replace("XUSD", "") not in _KNOWN_CRYPTO
        ]
        if not xstock_symbols:
            logging.info("[xStocks] No xStock instruments found")
            return []

        # שלוף מחירים
        r2 = requests.get(
            "https://futures.kraken.com/derivatives/api/v3/tickers",
            timeout=15
        )
        tickers = {t["symbol"]: t for t in r2.json().get("tickers", [])}

    except Exception as e:
        logging.error(f"[xStocks] fetch failed: {e}")
        return []

    out = []
    for sym in xstock_symbols:
        t = tickers.get(sym)
        if not t:
            continue
        price  = float(t.get("last", 0) or 0)
        open_p = float(t.get("open24h", 0) or 0)
        high   = float(t.get("high24h", 0) or 0)
        low    = float(t.get("low24h", 0) or 0)
        vol    = float(t.get("vol24h", 0) or 0)
        if price == 0 or open_p == 0:
            continue
        vol_usd = round(vol * price, 0)
        if vol_usd < 500:
            continue
        chg    = round((price - open_p) / open_p * 100, 2)
        rng    = round((high - low) / low * 100, 2) if low else 0
        ticker = sym.replace("PF_", "").replace("XUSD", "")
        out.append({
            "coin":        ticker,
            "pair":        sym,
            "price":       price,
            "price_dec":   2,
            "min_vol":     0.001,
            "change_24h":  chg,
            "range_24h":   rng,
            "high_24h":    high,
            "low_24h":     low,
            "volume_usdc": vol_usd,
            "is_stock":    True,
            "is_futures":  True,
        })

    out.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    logging.info(f"[xStocks] Found {len(out)} active xStock pairs")
    return out


# ── File helpers ──────────────────────────────────────────────────────────

def load_swing_trades() -> list:
    if os.path.exists(SWING_FILE):
        try:
            with open(SWING_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_swing_trades(trades: list):
    with open(SWING_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)

def archive_closed_trade(t: dict):
    """מעביר עסקה סגורה לארכיון הקבוע"""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding="utf-8") as f:
                history = json.load(f)
        # בדוק שלא כבר קיים (לפי txid)
        existing_txids = {h.get("txid") for h in history}
        if t.get("txid") in existing_txids:
            return
        history.append({
            "coin":        t["coin"],
            "pair":        t.get("pair", ""),
            "status":      t["status"],
            "leveraged":   t["coin"] in MARGIN_ELIGIBLE,
            "collateral":  t.get("usd", 0),
            "volume":      t.get("volume", 0),
            "entry_price": t.get("entry_price", 0),
            "close_price": t.get("close_price") or t.get("current_price", 0),
            "target_price":t.get("target_price", 0),
            "stop_price":  t.get("stop_price", 0),
            "pnl_usd":     round(t.get("pnl_usd", 0) or 0, 2),
            "pnl_pct":     round(t.get("pnl_pct", 0) or 0, 2),
            "date_open":   t.get("date_open", ""),
            "date_close":  t.get("date_close", ""),
            "reasoning":   t.get("reasoning", ""),
            "confidence":  t.get("confidence", ""),
            "txid":        t.get("txid", ""),
            "close_txid":  t.get("close_txid", ""),
        })
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logging.info(f"[Swing] Archived {t['coin']} → swing_history.json")
    except Exception as e:
        logging.warning(f"[Swing] Archive failed: {e}")


# ── Market data ───────────────────────────────────────────────────────────

def get_candidate_data() -> list:
    """מחזיר רשימת מטבעות עם נתוני שוק, ממוין לפי תנודתיות"""
    pair_str = ",".join(c["pair"] for c in CANDIDATES.values())
    try:
        r = requests.get(
            f"https://api.kraken.com/0/public/Ticker?pair={pair_str}",
            timeout=10
        )
        result = r.json().get("result", {})
    except Exception as e:
        logging.error(f"[Swing] ticker fetch failed: {e}")
        return []

    out = []
    for coin, cfg in CANDIDATES.items():
        t = result.get(cfg["pair"])
        if not t:
            continue
        price  = float(t["c"][0])
        open_p = float(t["o"])
        high   = float(t["h"][1])
        low    = float(t["l"][1])
        vol    = float(t["v"][1])
        if open_p == 0 or price == 0:
            continue
        chg   = round((price - open_p) / open_p * 100, 2)
        rng   = round((high - low) / low * 100, 2) if low else 0
        out.append({
            "coin": coin, "pair": cfg["pair"],
            "price": price, "price_dec": cfg["price_dec"],
            "min_vol": cfg["min_vol"],
            "change_24h": chg, "range_24h": rng,
            "high_24h": high, "low_24h": low,
            "volume_usdc": round(vol * price, 0),
        })

    out.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    return out


def get_current_price(pair: str) -> float:
    try:
        r = requests.get(
            f"https://api.kraken.com/0/public/Ticker?pair={pair}",
            timeout=5
        )
        t = r.json().get("result", {}).get(pair, {})
        return float(t["c"][0]) if t else 0
    except Exception:
        return 0


# ── Claude analysis ───────────────────────────────────────────────────────

def _load_api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return  # כבר מוגדר כמשתנה סביבה (שרת)
    env_path = os.path.join(DIR, ".env")
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() and v.strip() and not os.environ.get(k.strip()):
                        os.environ[k.strip()] = v.strip()
    except Exception:
        pass

def load_performance_summary() -> str:
    try:
        if not os.path.exists(HISTORY_FILE):
            return ""
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        if not history:
            return ""
        wins = [h for h in history if h.get("pnl_usd", 0) > 0]
        losses = [h for h in history if h.get("pnl_usd", 0) <= 0]
        total_pnl = sum(h.get("pnl_usd", 0) for h in history)
        win_rate = len(wins) / len(history) * 100 if history else 0
        coin_pnl = {}
        for h in history:
            coin = h.get("coin", "")
            coin_pnl[coin] = coin_pnl.get(coin, 0) + h.get("pnl_usd", 0)
        best = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)[:3]
        worst = sorted(coin_pnl.items(), key=lambda x: x[1])[:3]
        lines = [
            f"Past performance ({len(history)} trades): win rate {win_rate:.0f}%, total P&L ${total_pnl:.2f}",
            f"Best coins: {', '.join(f'{c}(${p:.2f})' for c,p in best)}",
            f"Worst coins: {', '.join(f'{c}(${p:.2f})' for c,p in worst)}",
        ]
        recent = history[-5:]
        recent_str = ", ".join(f"{h['coin']} {h['status']} ${h.get('pnl_usd',0):.2f}" for h in recent)
        lines.append(f"Last 5 trades: {recent_str}")
        return "\n".join(lines)
    except Exception:
        return ""


def analyze_with_claude(candidates: list, open_coins: set, usdc: float, btc_price: float, stock_candidates: list = None, open_positions: list = None) -> dict:
    _load_api_key()
    import anthropic

    crypto_rows = "\n".join([
        f"  [CRYPTO] {c['coin']}: ${c['price']:.4f} | {c['change_24h']:+.1f}% | "
        f"range {c['range_24h']:.1f}% | vol ${c['volume_usdc']:,.0f} | "
        f"H=${c['high_24h']:.4f} L=${c['low_24h']:.4f}"
        for c in candidates[:12]
    ])

    stock_section = ""
    if stock_candidates:
        stock_rows = "\n".join([
            f"  [STOCK] {c['coin']}: ${c['price']:.2f} | {c['change_24h']:+.1f}% | "
            f"range {c['range_24h']:.1f}% | vol ${c['volume_usdc']:,.0f}"
            for c in stock_candidates[:15]
        ])
        stock_section = f"""
xStock candidates (tokenized stocks, spot only, no leverage):
{stock_rows}
Trade size for stocks: ${SWING_USD_STOCK} | Take-profit: +{TARGET_PCT_STOCK*100:.1f}% | Stop-loss: -{STOP_PCT_STOCK*100:.1f}%
Stocks move slower than crypto — look for strong momentum days or pre/post earnings moves.
"""

    skip = ", ".join(open_coins) if open_coins else "none"
    performance = load_performance_summary()
    perf_section = f"\n\nYour historical performance:\n{performance}" if performance else ""

    # פרמטר נוסף: פוזיציות פתוחות לרוטציה
    open_positions_rows = ""
    if open_positions:
        open_positions_rows = "\nCurrently open positions:\n" + "\n".join([
            f"  {p['coin']}: entry=${p['entry_price']:.4f} now=${p.get('current_price', p['entry_price']):.4f} "
            f"P&L={p.get('pnl_pct', 0):+.1f}% | open since {p.get('date_open','')[:10]} | "
            f"target={p.get('target_price',0):.4f} stop={p.get('stop_price',0):.4f}"
            for p in open_positions
        ])

    rotation_instruction = ""
    if open_positions and len(open_positions) >= MAX_OPEN:
        rotation_instruction = f"""
IMPORTANT: Portfolio is FULL ({len(open_positions)}/{MAX_OPEN} positions).
You CAN suggest closing one weak position to open a better opportunity.
Add "close_for_rotation" field with the coin to close IF you find something significantly better.
Only rotate if the new opportunity is clearly superior — don't churn for small differences.
"""

    prompt = f"""You are an expert swing trader covering both crypto and tokenized stocks (xStocks). {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC.

BTC context price: ${btc_price:,.0f}
Available USDC: ${usdc:.2f}
Crypto trade size: ${SWING_USD} each (2x leverage = controls ${SWING_USD*2}) | Take-profit: +5% | Stop-loss: -2%
{open_positions_rows}{perf_section}{rotation_instruction}

Crypto altcoin candidates ranked by 24h movement:
{crypto_rows}
{stock_section}
Your job: Think carefully and pick 0, 1, or 2 assets for a swing trade RIGHT NOW.
You can mix crypto and stocks — pick whatever has the best risk/reward today.

Criteria to look for:
- Strong momentum with room to continue (not exhausted)
- Assets near intraday low that may bounce (dip buy)
- Volume confirming the move
- Clear entry with defined risk

Criteria to avoid:
- Assets that already ran 10%+ and look extended
- Very low volume crypto (under $50k/day) or stocks (under $5k/day)
- Choppy sideways movement
- Rotating out of a position that's already profitable and moving toward target

Return ONLY valid JSON:
{{
  "picks": [
    {{
      "coin": "TSLA",
      "confidence": "HIGH",
      "reasoning": "שתי משפטים בעברית — מה בדיוק אתה רואה ולמה עכשיו"
    }}
  ],
  "close_for_rotation": null,
  "rotation_reason": null,
  "market_read": "משפט אחד בעברית על מצב השוק הכללי כרגע",
  "skip_reason": "למה דחית את השאר (משפט אחד בעברית)"
}}

If nothing looks good — return picks as empty array. Better to miss a trade than to lose money."""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    raw = part
                    break
        last_brace = raw.rfind("}")
        if last_brace != -1:
            raw = raw[:last_brace+1]
        import re
        raw = re.sub(r",\s*}", "}", raw)
        raw = re.sub(r",\s*]", "]", raw)
        return json.loads(raw)
    except Exception as e:
        logging.error(f"[Swing] Claude error: {e}")
        return {"picks": [], "market_read": "", "skip_reason": str(e)}


# ── Main cycles ───────────────────────────────────────────────────────────

def _pair_to_coin(pair: str) -> str:
    """ממיר פאיר של קרקן לשם מטבע. XRPUSDC→XRP, ETHUSDC→ETH"""
    kraken_map = {"XXBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC", "XXLM": "XLM", "XDGE": "DOGE"}
    coin = pair.replace("USDC", "").replace("USD", "")
    return kraken_map.get(coin, coin)


def get_kraken_state(request_fn) -> dict:
    """
    קרקן הוא מקור האמת — מושך הכל בבת אחת:
    - OpenPositions: פוזיציות מרג'ין פתוחות
    - Balance: יתרות ספוט
    - OpenOrders: פקודות limit פתוחות
    מחזיר dict מאוחד עם כל המידע.
    """
    state = {"margin_positions": {}, "balance": {}, "open_orders": {}}
    try:
        pos = request_fn("/0/private/OpenPositions", private=True)
        for pid, p in pos.items():
            coin = _pair_to_coin(p.get("pair", ""))
            state["margin_positions"][coin] = {
                "pair":   p.get("pair"),
                "vol":    float(p.get("vol", 0)),
                "cost":   float(p.get("cost", 0)),
                "margin": float(p.get("margin", 0)),
                "txid":   p.get("ordertxid", ""),
            }
        logging.info(f"[Kraken] Margin positions: {list(state['margin_positions'].keys())}")
    except Exception as e:
        logging.error(f"[Kraken] OpenPositions failed: {e}")

    try:
        orders = request_fn("/0/private/OpenOrders", private=True)
        for oid, o in orders.get("open", {}).items():
            state["open_orders"][oid] = {
                "pair":      o.get("descr", {}).get("pair", ""),
                "type":      o.get("descr", {}).get("type", ""),
                "ordertype": o.get("descr", {}).get("ordertype", ""),
                "price":     float(o.get("descr", {}).get("price", 0) or 0),
                "vol":       float(o.get("vol", 0)),
            }
        logging.info(f"[Kraken] Open orders: {len(state['open_orders'])}")
    except Exception as e:
        logging.error(f"[Kraken] OpenOrders failed: {e}")

    return state


def sync_trades_with_kraken(trades: list, balance: dict, request_fn=None) -> tuple[list, bool]:
    """
    קרקן הוא מקור האמת — סנכרון דו-כיווני בכל ריצה:
    1. פוזיציה ב-JSON כ-open אבל לא בקרקן → סוגר אוטומטית
    2. פוזיציה בקרקן אבל ב-JSON כ-closed → פותח מחדש
    """
    changed = False
    if not request_fn:
        return trades, changed

    kraken       = get_kraken_state(request_fn)
    margin_coins = set(kraken["margin_positions"].keys())

    # כיוון 1: סגור מה שלא קיים בקרקן
    for t in trades:
        if t.get("status") != "open" or t.get("is_stock"):
            continue
        coin    = t["coin"]
        holding = float(balance.get(coin, 0))
        min_vol = CANDIDATES.get(coin, {}).get("min_vol", 0.001)
        in_margin  = coin in margin_coins
        in_balance = holding >= min_vol * 0.5
        if not in_margin and not in_balance:
            current = get_current_price(t["pair"])
            pnl_pct = round((current - t["entry_price"]) / t["entry_price"] * 100, 2) if current and t["entry_price"] else 0
            t["status"]      = "closed_externally"
            t["date_close"]  = datetime.now().isoformat()
            t["close_price"] = current or t.get("current_price", t["entry_price"])
            t["pnl_pct"]     = pnl_pct
            t["pnl_usd"]     = round(pnl_pct / 100 * t.get("usd", 0), 2)
            changed = True
            logging.warning(f"[Sync] {coin} gone from Kraken → closed_externally | P&L≈{pnl_pct:+.1f}%")
            archive_closed_trade(t)

    # כיוון 2: פתח מחדש מה שקרקן אומר שפתוח אבל JSON לא יודע עליו
    open_coins_in_json = {t["coin"] for t in trades if t.get("status") == "open"}
    for coin, kpos in kraken["margin_positions"].items():
        if coin in open_coins_in_json:
            continue
        # חפש רשומה קיימת בJSON (יכול להיות closed_externally בטעות)
        existing = next((t for t in trades if t["coin"] == coin and t.get("pair") == kpos["pair"]), None)
        if existing:
            existing["status"]     = "open"
            existing["date_close"] = None
            changed = True
            logging.warning(f"[Sync] {coin} IS open in Kraken but was closed in JSON → reopened")
        else:
            # פוזיציה חדשה שהבוט לא פתח — הוסף אותה
            current = get_current_price(kpos["pair"])
            entry   = round(kpos["cost"] / kpos["vol"], 6) if kpos["vol"] else current
            trades.append({
                "coin":         coin,
                "pair":         kpos["pair"],
                "entry_price":  entry,
                "limit_price":  entry,
                "volume":       kpos["vol"],
                "usd":          round(kpos["cost"], 2),
                "target_price": round(entry * (1 + TARGET_PCT), 6),
                "stop_price":   round(entry * (1 - STOP_PCT), 6),
                "date_open":    datetime.now().isoformat(),
                "date_close":   None,
                "status":       "open",
                "confidence":   "MEDIUM",
                "reasoning":    "Restored from Kraken OpenPositions",
                "market_read":  "",
                "current_price":current,
                "pnl_pct":      0.0,
                "pnl_usd":      0.0,
                "txid":         kpos.get("txid", ""),
                "sell_txid":    None,
                "close_price":  None,
                "close_txid":   None,
            })
            changed = True
            logging.warning(f"[Sync] {coin} found in Kraken but missing from JSON → added")

    return trades, changed


def check_open_swings(balance: dict, request_fn) -> list:
    """נקרא כל 15 דקות — בודק אם פוזיציות פתוחות הגיעו ליעד/stop"""
    trades  = load_swing_trades()

    # סנכרון עם קרקן — בודק balance + OpenPositions, סוגר מה שלא קיים
    trades, sync_changed = sync_trades_with_kraken(trades, balance, request_fn)
    changed = sync_changed

    for t in trades:
        if t.get("status") != "open":
            continue

        coin  = t["coin"]
        pair  = t["pair"]
        entry = t["entry_price"]
        vol   = t["volume"]

        if t.get("is_stock") and t.get("is_futures"):
            from kraken_futures import get_futures_price
            current = get_futures_price(pair)
        else:
            current = get_current_price(pair)
        if current == 0:
            continue

        pnl_pct = (current - entry) / entry * 100
        t["current_price"] = round(current, 6)
        t["pnl_pct"]       = round(pnl_pct, 2)
        t["pnl_usd"]       = round((current - entry) * vol, 2)
        changed = True

        reason = None
        if current >= t["target_price"]:
            reason = "profit"
        elif current <= t["stop_price"]:
            reason = "loss"

        if reason:
            cfg       = CANDIDATES.get(coin, {})
            price_dec = cfg.get("price_dec", 4)

            if reason == "profit" and t.get("sell_txid"):
                # כבר יש limit sell פתוח — פשוט סמן כסגור
                t["status"]      = "closed_profit"
                t["date_close"]  = datetime.now().isoformat()
                t["close_price"] = current
                t["close_txid"]  = t["sell_txid"]
                logging.info(f"[Swing] CLOSE PROFIT {coin} @ {current:.4f} (limit already placed)")
                archive_closed_trade(t)
            else:
                # stop-loss — בטל את ה-TP הפתוח ושים market sell
                if t.get("sell_txid"):
                    try:
                        request_fn("/0/private/CancelOrder", {"txid": t["sell_txid"]}, private=True)
                        logging.info(f"[Swing] Cancelled TP order {t['sell_txid']} for {coin}")
                    except Exception as ce:
                        logging.warning(f"[Swing] cancel TP failed: {ce}")

                holding  = float(balance.get(coin, 0))
                sell_vol = min(vol, holding)
                if sell_vol < cfg.get("min_vol", 0.01):
                    logging.warning(f"[Swing] {coin} holding {holding} below min — cannot sell")
                    continue
                lp = round(current * 0.999, price_dec)
                use_lev = coin in MARGIN_ELIGIBLE
                try:
                    stop_params = {
                        "pair": pair, "type": "sell", "ordertype": "limit",
                        "volume": f"{sell_vol:.8f}", "price": f"{lp:.{price_dec}f}",
                    }
                    if use_lev:
                        stop_params["leverage"] = str(LEVERAGE)
                    res  = request_fn("/0/private/AddOrder", stop_params, private=True)
                    txid = list(res.get("txid", ["?"]))[0]
                    t["status"]      = "closed_loss"
                    t["date_close"]  = datetime.now().isoformat()
                    t["close_price"] = current
                    t["close_txid"]  = txid
                    logging.info(f"[Swing] CLOSE STOP {coin} @ {current:.4f} | P&L {pnl_pct:+.1f}% | txid={txid}")
                    archive_closed_trade(t)
                except Exception as e:
                    logging.error(f"[Swing] stop sell failed {coin}: {e}")

    if changed:
        save_swing_trades(trades)
    return trades


def get_margin_used(request_fn) -> float:
    """מחזיר סה"כ margin בשימוש מ-Kraken (בדולרים)"""
    try:
        pos = request_fn("/0/private/OpenPositions", private=True)
        return sum(float(p.get("margin", 0)) for p in pos.values())
    except Exception:
        return 0.0

def run_swing_scan(balance: dict, usdc: float, request_fn, btc_price: float = 0) -> list:
    """נקרא כל שעה — Claude סורק ובוחר מועמדים"""
    trades      = load_swing_trades()
    open_swings = [t for t in trades if t.get("status") == "open"]
    open_coins  = {t["coin"] for t in open_swings}
    open_budget = sum(t.get("usd", 0) for t in open_swings)

    if len(open_swings) >= MAX_OPEN:
        logging.info(f"[Swing] {MAX_OPEN} positions open — checking for rotation opportunity")
    if open_budget >= MAX_BUDGET:
        logging.info(f"[Swing] Budget ${MAX_BUDGET} reached — skipping scan")
        return trades
    if usdc < 10:
        logging.info(f"[Swing] USDC critically low ${usdc:.2f} — skipping scan")
        return trades

    # בדוק margin usage — אם מעל 80% מהתקרה, אל תנסה leverage
    margin_used = get_margin_used(request_fn)
    margin_headroom = max(0, 150 - margin_used)  # ~$150 תקרה לחשבון ~$600
    logging.info(f"[Swing] Margin used: ${margin_used:.0f} | headroom: ${margin_headroom:.0f}")

    candidates = get_candidate_data()
    if not candidates:
        logging.warning("[Swing] No candidate data available")
        return trades

    # שלוף xStocks דינמית
    stock_candidates = get_xstock_data()

    # בנה lookup מהיר לפי coin
    all_candidates_map = {c["coin"]: c for c in candidates}
    for s in stock_candidates:
        all_candidates_map[s["coin"]] = s

    # תמיד קרא לקלוד — גם כשמלא, כדי לאפשר רוטציה
    analysis    = analyze_with_claude(candidates, open_coins, usdc, btc_price, stock_candidates, open_swings)
    market_read = analysis.get("market_read", "")
    skip_reason = analysis.get("skip_reason", "")
    logging.info(f"[Swing] Claude: {market_read} | skipped: {skip_reason}")

    # רוטציה — קלוד ביקש לסגור פוזיציה חלשה כדי לפתוח חדשה
    close_for_rotation = analysis.get("close_for_rotation")
    if close_for_rotation and close_for_rotation in open_coins:
        rotation_reason = analysis.get("rotation_reason", "")
        logging.info(f"[Swing] ROTATION: closing {close_for_rotation} — {rotation_reason}")
        for t in trades:
            if t.get("coin") == close_for_rotation and t.get("status") == "open":
                current = get_current_price(t["pair"])
                if current > 0:
                    cfg_r     = CANDIDATES.get(close_for_rotation, all_candidates_map.get(close_for_rotation, {}))
                    price_dec = cfg_r.get("price_dec", 4)
                    lp        = round(current * 0.999, price_dec)
                    use_lev   = close_for_rotation in MARGIN_ELIGIBLE and not t.get("is_stock")
                    try:
                        if t.get("sell_txid"):
                            request_fn("/0/private/CancelOrder", {"txid": t["sell_txid"]}, private=True)
                        sell_params = {
                            "pair": t["pair"], "type": "sell", "ordertype": "limit",
                            "volume": f"{t['volume']:.8f}", "price": f"{lp:.{price_dec}f}",
                        }
                        if use_lev:
                            sell_params["leverage"] = str(LEVERAGE)
                        res  = request_fn("/0/private/AddOrder", sell_params, private=True)
                        txid = list(res.get("txid", ["?"]))[0]
                        t["status"]      = "closed_loss" if current < t["entry_price"] else "closed_profit"
                        t["date_close"]  = datetime.now().isoformat()
                        t["close_price"] = current
                        t["close_txid"]  = txid
                        t["pnl_pct"]     = round((current - t["entry_price"]) / t["entry_price"] * 100, 2)
                        t["pnl_usd"]     = round((current - t["entry_price"]) * t["volume"], 2)
                        archive_closed_trade(t)
                        open_coins.discard(close_for_rotation)
                        open_swings = [s for s in open_swings if s["coin"] != close_for_rotation]
                        logging.info(f"[Swing] Rotation close {close_for_rotation} @ {current:.4f} P&L={t['pnl_pct']:+.1f}%")
                    except Exception as e:
                        logging.error(f"[Swing] Rotation close failed {close_for_rotation}: {e}")
                break

    slots = MAX_OPEN - len(open_swings)
    for pick in analysis.get("picks", [])[:slots]:
        coin   = pick.get("coin", "")
        reason = pick.get("reasoning", "")
        conf   = pick.get("confidence", "MEDIUM")

        if coin in open_coins:
            continue

        coin_data = all_candidates_map.get(coin)
        if not coin_data:
            logging.warning(f"[Swing] Claude picked {coin} but not found in candidates — skip")
            continue

        is_stock  = coin_data.get("is_stock", False)
        pair      = coin_data["pair"]
        price_dec = coin_data["price_dec"]
        min_v     = coin_data["min_vol"]

        # פרמטרים שונים לפי סוג
        trade_usd  = SWING_USD_STOCK if is_stock else SWING_USD
        target_pct = TARGET_PCT_STOCK if is_stock else TARGET_PCT
        stop_pct   = STOP_PCT_STOCK   if is_stock else STOP_PCT

        # CANDIDATES lookup לקריפטו (לmargining)
        cfg = CANDIDATES.get(coin, {})

        price = coin_data["price"]
        vol   = round(trade_usd / price, 8)

        if vol < min_v:
            logging.warning(f"[Swing] {coin} vol={vol:.6f} < min={min_v} — skip")
            continue

        buy_lp   = round(price * 0.999, price_dec)
        target_p = round(price * (1 + target_pct), price_dec)
        stop_p   = round(price * (1 - stop_pct),   price_dec)
        try:
            if is_stock:
                # ── xStock — דרך Kraken Futures API ──────────────────────
                from kraken_futures import place_futures_order, get_futures_balance
                fut_balance = get_futures_balance()
                if fut_balance < trade_usd:
                    logging.warning(f"[Futures] Insufficient balance ${fut_balance:.2f} < ${trade_usd} for {coin}")
                    continue
                txid      = place_futures_order(pair, "buy",  vol, buy_lp)
                sell_txid = None
                try:
                    sell_txid = place_futures_order(pair, "sell", vol, target_p)
                except Exception as se:
                    logging.warning(f"[Futures] TP order failed {coin}: {se}")
            else:
                # ── קריפטו — דרך Kraken Spot/Margin API ──────────────────
                use_leverage = coin in MARGIN_ELIGIBLE
                buy_params = {
                    "pair": pair, "type": "buy", "ordertype": "limit",
                    "volume": f"{vol:.8f}", "price": f"{buy_lp:.{price_dec}f}",
                }
                if use_leverage:
                    buy_params["leverage"] = str(LEVERAGE)
                try:
                    res = request_fn("/0/private/AddOrder", buy_params, private=True)
                except Exception as margin_e:
                    if "margin" in str(margin_e).lower() and use_leverage:
                        logging.warning(f"[Swing] Margin full for {coin}, retrying without leverage")
                        buy_params.pop("leverage", None)
                        use_leverage = False
                        res = request_fn("/0/private/AddOrder", buy_params, private=True)
                    else:
                        raise
                txid = list(res.get("txid", ["?"]))[0]

                sell_txid = None
                try:
                    sell_params = {
                        "pair": pair, "type": "sell", "ordertype": "limit",
                        "volume": f"{vol:.8f}", "price": f"{target_p:.{price_dec}f}",
                    }
                    if use_leverage:
                        sell_params["leverage"] = str(LEVERAGE)
                    try:
                        sell_res = request_fn("/0/private/AddOrder", sell_params, private=True)
                    except Exception as se2:
                        if "margin" in str(se2).lower():
                            sell_params.pop("leverage", None)
                            sell_res = request_fn("/0/private/AddOrder", sell_params, private=True)
                        else:
                            raise
                    sell_txid = list(sell_res.get("txid", ["?"]))[0]
                    logging.info(f"[Swing] SELL-TP placed {coin} @ {target_p} txid={sell_txid}")
                except Exception as se:
                    logging.warning(f"[Swing] sell-tp failed {coin}: {se}")

            trade = {
                "coin":          coin,
                "pair":          pair,
                "is_stock":      is_stock,
                "entry_price":   price,
                "limit_price":   buy_lp,
                "volume":        vol,
                "usd":           round(vol * price, 2),
                "target_price":  target_p,
                "stop_price":    stop_p,
                "date_open":     datetime.now().isoformat(),
                "date_close":    None,
                "status":        "open",
                "confidence":    conf,
                "reasoning":     reason,
                "market_read":   market_read,
                "current_price": price,
                "pnl_pct":       0.0,
                "pnl_usd":       0.0,
                "txid":          txid,
                "sell_txid":     sell_txid,
                "close_price":   None,
                "close_txid":    None,
            }
            trades.append(trade)
            open_coins.add(coin)
            logging.info(f"[Swing] OPEN {coin} @ {price:.4f} target={target_p} stop={stop_p} | {reason[:80]}")
        except Exception as e:
            logging.error(f"[Swing] buy failed {coin}: {e}")

    save_swing_trades(trades)
    return trades
