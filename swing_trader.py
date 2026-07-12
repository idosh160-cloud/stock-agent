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

try:
    import pandas as pd
    import ta as _ta_lib
    _PANDAS_TA_AVAILABLE = True
except ImportError:
    _PANDAS_TA_AVAILABLE = False
    logging.warning("[Swing] ta library not installed — indicators disabled")

DIR          = os.path.dirname(os.path.abspath(__file__))
SWING_FILE   = os.path.join(DIR, "swing_trades.json")
HISTORY_FILE = os.path.join(DIR, "swing_history.json")
DEBUG_FILE   = os.path.join(DIR, "swing_debug.json")


def _write_debug(d: dict):
    """אבחון סריקה שנדחף לגיט כל שעה — הדרך היחידה לראות מרחוק למה הבוט החליט מה שהחליט"""
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
    except Exception:
        pass

SWING_USD         = 100    # ברירת מחדל לעסקת קריפטו אם Claude לא נתן size_pct
STOCK_MIN_VOL_USD = 5000   # רף נזילות למניה — 20k סינן את רוב ה-xStocks רוב היום; הגודל מוגבל יחסית לנפח בהמשך
SWING_USD_STOCK   = 100    # רצפה לעסקת מניה (נושיונל) — פוזיציות מתחת ל-$100 לא מזיזות את המחט
SWING_MAX_STOCK_USD = 450  # תקרת נושיונל לעסקת מניה (עם מינוף x3 = ~$150 מרג'ין)
MAX_HOLD_HOURS      = 48   # סווינג שעתי/יומי — פוזיציה מעבר לזה בלי התקדמות היא הון תקוע
STALE_EXIT_MIN_PNL  = 1.0  # מתחת ל-+1% אחרי MAX_HOLD_HOURS → סוגרים ומשחררים הון
STOCK_LEVERAGE    = 3      # מינוף יעד על מניות (Perps) — אגרסיבי אך לא פרוע
SWING_PCT_DEFAULT = 0.15   # 15% מהתיק אם אין size_pct מ-Claude
SWING_MIN_USD     = 100    # רצפת גודל פוזיציה — הבעלים לא רוצה עסקאות קטנות שלא משנות כלום
SWING_MAX_USD     = 500    # תקרה לעסקה בודדת
TARGET_PCT        = 0.05   # +5% יעד רווח קריפטו
TARGET_PCT_STOCK  = 0.07   # +7% יעד רווח xStocks — מניות תנודתיות יכולות לעשות הרבה יותר
STOP_PCT          = 0.02   # -2% עצור הפסד קריפטו
STOP_PCT_STOCK    = 0.015  # -1.5% עצור הפסד xStocks
MAX_OPEN          = 8      # פוזיציות פתוחות מקסימום — הועלה מ-6, התיק היה תקוע "מלא" לילה שלם
MAX_BUDGET        = 600    # תקציב מקסימלי לסווינגים
LEVERAGE          = 5      # מינוף x5 על כל קנייה (Kraken margin) — לא למניות

# מטבעות שקרקן מאפשר עליהם margin trading
MARGIN_ELIGIBLE = {"BTC", "ETH", "SOL", "XRP", "LTC", "BCH", "LINK", "DOT", "ADA", "AVAX", "BNB", "DOGE", "XMR", "TON"}

# Pairs שאומתו ב-Kraken + מינימום נפח + דיוק מחיר
CANDIDATES = {
    "BTC":  {"pair": "XBTUSDC",  "min_vol": 0.0001,"price_dec": 1},
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
        if vol_usd < STOCK_MIN_VOL_USD:
            continue   # רף נזילות — דלג על מניות דלילות (מלכודת ביצוע)
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

def _send_trade_alert(subject: str, body: str):
    """שולח מייל קצר על פעולת מסחר."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        sender   = os.environ.get("GMAIL_USER", "")
        password = os.environ.get("GMAIL_APP_PASSWORD", "")
        if not sender or not password:
            return
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = sender
        msg["To"]      = sender
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo()
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, sender, msg.as_string())
        logging.info(f"[Alert] מייל נשלח: {subject}")
    except Exception as e:
        logging.warning(f"[Alert] שליחת מייל נכשלה: {e}")


def archive_closed_trade(t: dict):
    """מעביר עסקה סגורה לארכיון הקבוע"""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding="utf-8") as f:
                history = json.load(f)
        # בדוק שלא כבר קיים — לפי צמד (כניסה, סגירה). אותה כניסה יכולה להירשם
        # כסגורה פעמיים (סגירת-סרק של הסנכרון ואז הסגירה האמיתית) — האמיתית
        # חייבת להיכנס, אחרת ההיסטוריה משקרת (כך ההפסד של DOGE נרשם כרווח)
        existing = {(h.get("txid"), h.get("close_txid")) for h in history}
        if (t.get("txid"), t.get("close_txid")) in existing:
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
            "side":            t.get("side", "long"),
            "entry_rsi":       t.get("entry_rsi"),
            "entry_bb_pct":    t.get("entry_bb_pct"),
            "entry_macd_hist": t.get("entry_macd_hist"),
            "entry_change_24h": t.get("entry_change_24h"),
        })
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logging.info(f"[Swing] Archived {t['coin']} → swing_history.json")
    except Exception as e:
        logging.warning(f"[Swing] Archive failed: {e}")


# ── Market data ───────────────────────────────────────────────────────────

DYNAMIC_MIN_VOL_USD = 30000    # נפח יומי מינימלי ($) למטבע דינמי (USDC נזיל פחות מ-USD)
DYNAMIC_MAX_CANDIDATES = 40    # כמה מטבעות מקסימום להחזיר

# נרמול שמות Kraken פנימיים → שמות סטנדרטיים (עקביות עם שאר המערכת)
_KRAKEN_COIN_NORM = {"XBT": "BTC", "XDG": "DOGE"}


def _build_dynamic_universe() -> dict:
    """מושך את כל זוגות ה-USDC מ-Kraken AssetPairs ובונה מפת מועמדים דינמית.
    מחזיר {coin: {pair, price_dec, min_vol, margin}}. נופל חזרה ל-CANDIDATES אם נכשל."""
    try:
        r = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=12)
        pairs = r.json().get("result", {})
    except Exception as e:
        logging.warning(f"[Swing] AssetPairs fetch failed: {e} — משתמש ברשימה הקבועה")
        return {}

    universe = {}
    for _, info in pairs.items():
        try:
            if info.get("status") != "online":
                continue
            wsname = info.get("wsname", "")
            altname = info.get("altname", "")
            if not wsname or "/" not in wsname:
                continue
            base, quote = wsname.split("/")
            if quote != "USDC":
                continue
            base = _KRAKEN_COIN_NORM.get(base, base)   # XBT→BTC, XDG→DOGE
            # סנן fiat/stablecoins כבסיס
            if base in ("USD","EUR","GBP","CHF","CAD","AUD","JPY","USDT","DAI","USDG","EURC","USDP","TUSD"):
                continue
            margin = bool(info.get("leverage_buy"))
            universe[base] = {
                "pair":      altname,
                "price_dec": int(info.get("pair_decimals", 4)),
                "min_vol":   float(info.get("ordermin", 0) or 0),
                "margin":    margin,
            }
        except Exception:
            continue
    return universe


def get_candidate_data() -> list:
    """מחזיר רשימת מטבעות עם נתוני שוק, ממוין לפי תנודתיות.
    דינמי — כל זוגות ה-USDC בעלי נפח גבוה ב-Kraken (לא רק 19 קבועים)."""
    universe = _build_dynamic_universe()

    # מיזוג: דינמי קודם, ואז משלימים מהרשימה הקבועה אם משהו חסר
    merged = {}
    for coin, cfg in CANDIDATES.items():
        merged[coin] = {"pair": cfg["pair"], "price_dec": cfg["price_dec"],
                        "min_vol": cfg["min_vol"], "margin": coin in MARGIN_ELIGIBLE}
    for coin, cfg in universe.items():
        merged[coin] = cfg

    if not merged:
        return []

    # עדכן את המפות הגלובליות כדי שחיפושי CANDIDATES.get(coin) ו-MARGIN_ELIGIBLE יעבדו לכל המטבעות
    for coin, cfg in merged.items():
        CANDIDATES[coin] = {"pair": cfg["pair"], "min_vol": cfg["min_vol"], "price_dec": cfg["price_dec"]}
        if cfg.get("margin"):
            MARGIN_ELIGIBLE.add(coin)

    # שלוף tickers לכל הזוגות (בקבוצות כדי לא לחרוג מגודל URL)
    pair_list = [cfg["pair"] for cfg in merged.values()]
    result = {}
    for i in range(0, len(pair_list), 60):
        batch = ",".join(pair_list[i:i+60])
        try:
            r = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={batch}", timeout=12)
            result.update(r.json().get("result", {}))
        except Exception as e:
            logging.warning(f"[Swing] ticker batch failed: {e}")

    # מפה הפוכה pair→coin (Kraken יכול להחזיר שם פאיר מנורמל)
    pair_to_coin = {cfg["pair"]: coin for coin, cfg in merged.items()}

    out = []
    for kpair, t in result.items():
        coin = pair_to_coin.get(kpair)
        if not coin:
            # נסה התאמה לפי altname (Kraken לפעמים מחזיר שם שונה)
            coin = next((c for c, cfg in merged.items() if cfg["pair"] in kpair or kpair in cfg["pair"]), None)
        if not coin:
            continue
        cfg = merged[coin]
        try:
            price  = float(t["c"][0]); open_p = float(t["o"])
            high   = float(t["h"][1]); low = float(t["l"][1]); vol = float(t["v"][1])
        except Exception:
            continue
        if open_p == 0 or price == 0:
            continue
        vol_usd = round(vol * price, 0)
        chg   = round((price - open_p) / open_p * 100, 2)
        rng   = round((high - low) / low * 100, 2) if low else 0
        out.append({
            "coin": coin, "pair": cfg["pair"],
            "price": price, "price_dec": cfg["price_dec"], "min_vol": cfg["min_vol"],
            "change_24h": chg, "range_24h": rng,
            "high_24h": high, "low_24h": low, "volume_usdc": vol_usd,
        })

    # סנן נפח נמוך, מיין לפי תנודתיות, החזר את הטופ
    out = [c for c in out if c["volume_usdc"] >= DYNAMIC_MIN_VOL_USD]
    out.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    logging.info(f"[Swing] יקום דינמי: {len(out)} מטבעות מעל ${DYNAMIC_MIN_VOL_USD:,.0f} נפח")
    return out[:DYNAMIC_MAX_CANDIDATES]


def get_ohlcv(pair: str, interval: int = 60, count: int = 50) -> list:
    """שולף נרות OHLCV מ-Kraken. interval בדקות. מחזיר רשימת [time,open,high,low,close,vol]."""
    try:
        r = requests.get(
            f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}",
            timeout=10
        )
        result = r.json().get("result", {})
        key = next((k for k in result if k != "last"), None)
        if not key:
            return []
        candles = result[key][-count:]
        return [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[6])] for c in candles]
    except Exception as e:
        logging.debug(f"[Swing] OHLCV fetch failed for {pair}: {e}")
        return []


def get_indicators(pair: str) -> dict:
    """מחשב RSI-14, MACD(12,26,9), Bollinger(20,2) על נרות שעתיים."""
    if not _PANDAS_TA_AVAILABLE:
        return {}
    candles = get_ohlcv(pair, interval=60, count=60)
    if len(candles) < 26:
        return {}
    try:
        df = pd.DataFrame(candles, columns=["open", "high", "low", "close", "volume"])
        close = df["close"]
        result = {}

        rsi_series = _ta_lib.momentum.RSIIndicator(close, window=14).rsi()
        if not rsi_series.empty:
            result["rsi"] = round(float(rsi_series.iloc[-1]), 1)

        macd_obj = _ta_lib.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
        macd_val = float(macd_obj.macd().iloc[-1])
        signal_val = float(macd_obj.macd_signal().iloc[-1])
        result["macd_hist"] = round(macd_val - signal_val, 6)

        bb_obj = _ta_lib.volatility.BollingerBands(close, window=20, window_dev=2)
        upper = float(bb_obj.bollinger_hband().iloc[-1])
        lower = float(bb_obj.bollinger_lband().iloc[-1])
        current = float(close.iloc[-1])
        if upper != lower:
            result["bb_pct"] = round((current - lower) / (upper - lower) * 100, 1)
        else:
            result["bb_pct"] = 50.0

        return result
    except Exception as e:
        logging.debug(f"[Swing] indicators calc failed for {pair}: {e}")
        return {}


def enrich_with_indicators(candidates: list) -> list:
    """מוסיף RSI/MACD/BB לכל מועמד. שומר על הרשימה המקורית אם pandas-ta לא זמין."""
    if not _PANDAS_TA_AVAILABLE:
        return candidates
    for c in candidates:
        try:
            indicators = get_indicators(c["pair"])
            c.update(indicators)
        except Exception:
            pass
    return candidates


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
        total_pnl = sum(h.get("pnl_usd", 0) for h in history)
        win_rate = len(wins) / len(history) * 100 if history else 0

        # per-coin stats — כל ההיסטוריה (לא נמחק), ועם דגש על האחרונות
        coin_stats = {}
        for h in history:
            coin = h.get("coin", "")
            if not coin:
                continue
            s = coin_stats.setdefault(coin, {"wins": 0, "total": 0, "pnl": 0.0, "recent_pnl": 0.0, "recent_total": 0})
            s["total"] += 1
            s["pnl"]   += h.get("pnl_usd", 0)
            if h.get("pnl_usd", 0) > 0:
                s["wins"] += 1

        # 30 עסקאות אחרונות — משקל גבוה יותר לאחרונות
        recent_30 = history[-30:]
        for h in recent_30:
            coin = h.get("coin", "")
            if coin in coin_stats:
                coin_stats[coin]["recent_pnl"]   += h.get("pnl_usd", 0)
                coin_stats[coin]["recent_total"]  += 1

        # בנה שורה חכמה לכל מטבע — לא רק מספר, אלא באילו *תנאים* הצלחנו/נכשלנו
        def _avg(vals):
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        def _entry_profile(rows):
            """מתאר את תנאי הכניסה הטיפוסיים של קבוצת עסקאות (RSI, כיוון)."""
            if not rows:
                return ""
            rsi = _avg([r.get("entry_rsi") for r in rows])
            longs  = sum(1 for r in rows if r.get("side", "long") != "short")
            shorts = len(rows) - longs
            parts = []
            if rsi is not None:
                parts.append(f"avg entry RSI {rsi}")
            if shorts:
                parts.append(f"{longs}L/{shorts}S")
            return (" [" + ", ".join(parts) + "]") if parts else ""

        coin_lines = []
        for coin, s in sorted(coin_stats.items(), key=lambda x: x[1]["pnl"]):
            rows = [h for h in history if h.get("coin") == coin]
            win_rows  = [h for h in rows if (h.get("pnl_usd") or 0) > 0]
            loss_rows = [h for h in rows if (h.get("pnl_usd") or 0) <= 0]
            n  = s["total"]
            wr = round(len(win_rows) / n * 100) if n else 0
            reliability = "tiny sample" if n < 5 else "some data" if n < 15 else "reliable"
            line = f"  {coin}: {n} trades, {wr}% win, ${s['pnl']:+.2f} ({reliability})"
            # אם יש דפוס ברור — הראה את ההבדל בתנאי הכניסה בין ניצחונות להפסדים
            if win_rows and loss_rows:
                wp = _entry_profile(win_rows)
                lp = _entry_profile(loss_rows)
                if wp or lp:
                    line += f" | wins{wp} vs losses{lp}"
            elif loss_rows and s["pnl"] < -3:
                lp = _entry_profile(loss_rows)
                line += f" | only losses so far{lp} — entries may have been mistimed, NOT proof the coin is bad"
            coin_lines.append(line)

        lines = [
            f"Past performance ({len(history)} trades total): win rate {win_rate:.0f}%, total P&L ${total_pnl:.2f}",
            "Per-coin history — READ THE PATTERN, don't blocklist. A coin that lost money may have been entered at the WRONG conditions (e.g. mid-RSI, chasing). If the CURRENT setup is different/better (e.g. now deeply oversold), it can still be a great trade. Compare the current setup to where past wins vs losses happened:",
        ] + coin_lines

        recent_5 = history[-5:]
        recent_str = ", ".join(f"{h['coin']} {h['status']} ${h.get('pnl_usd',0):+.2f}" for h in recent_5)
        lines.append(f"Last 5 trades: {recent_str}")
        return "\n".join(lines)
    except Exception:
        return ""


def analyze_with_claude(candidates: list, open_coins: set, usdc: float, btc_price: float, stock_candidates: list = None, open_positions: list = None, portfolio_summary: str = "", spot_holdings: list = None) -> dict:
    _load_api_key()
    import anthropic

    top_candidates = enrich_with_indicators(candidates[:10])

    def _indicator_str(c: dict) -> str:
        parts = []
        if "rsi" in c:
            rsi = c["rsi"]
            rsi_note = " (oversold)" if rsi < 35 else " (overbought)" if rsi > 65 else ""
            parts.append(f"RSI={rsi}{rsi_note}")
        if "macd_hist" in c:
            hist = c["macd_hist"]
            parts.append(f"MACD_hist={'+' if hist > 0 else ''}{hist:.4f}")
        if "bb_pct" in c:
            bp = c["bb_pct"]
            bb_note = " (near lower)" if bp < 20 else " (near upper)" if bp > 80 else ""
            parts.append(f"BB%={bp}{bb_note}")
        return " | " + " | ".join(parts) if parts else ""

    crypto_rows = "\n".join([
        f"  [CRYPTO] {c['coin']}: ${c['price']:.4f} | {c['change_24h']:+.1f}% | "
        f"range {c['range_24h']:.1f}% | vol ${c['volume_usdc']:,.0f} | "
        f"H=${c['high_24h']:.4f} L=${c['low_24h']:.4f}"
        + _indicator_str(c)
        for c in top_candidates
    ])

    stock_section = ""
    if stock_candidates:
        stock_rows = "\n".join([
            f"  [STOCK] {c['coin']}: ${c['price']:.2f} | {c['change_24h']:+.1f}% | "
            f"range {c['range_24h']:.1f}% | vol ${c['volume_usdc']:,.0f}"
            for c in stock_candidates[:10]
        ])
        open_stock_n = len([p for p in (open_positions or []) if p.get("is_stock")])
        stock_note = (
            "NOTE: you currently hold ZERO stock positions — an entire asset class is unused. "
            "During US market hours, actively look for a stock setup, don't default to crypto.\n"
        ) if open_stock_n == 0 else ""
        stock_section = f"""
{stock_note}
xStock candidates (tokenized stocks via Kraken Futures Perps — LONG and SHORT, leverage available):
{stock_rows}
Stocks are FULL citizens now — pick them whenever they're the best growth opportunity, same as crypto.
- Size by conviction with "size_pct" (% of portfolio NOTIONAL) just like crypto. DO THE LEVERAGE MATH: stocks run
  on 3x leverage, so a 30% notional position ties up only ~10% of the portfolio as margin. Sizing a stock at 15%
  notional (~5% margin) is timid — MEDIUM+ conviction deserves 25-40% notional. Sub-$100 positions barely move the needle.
- You can go LONG or SHORT on stocks (Perps). Short overbought/exhausted names, long strong momentum/dips.
- IMPORTANT — a stock that already ran +15-30% in a day is NOT "too late", it's a SHORT candidate. Don't just skip pumped stocks (e.g. SPCX +28%) — consider SHORTING the exhausted move (direction:"short") when RSI is extreme/BB% near 100 and momentum is stalling. Mean-reversion after a parabolic stock day is one of the best setups available.
- STILL trade them stock-aware: they move SLOWER and tighter than crypto. A 3% stock day is big.
  · Use tighter bands than crypto: target_pct 0.03-0.08, stop_pct 0.015-0.03, but keep target ≥ 2x stop.
- These tokens trade 24/7 — off-hours moves (overnight momentum, post-earnings drift, news reactions while Wall St is closed) are REAL tradeable setups, not noise. Position size is already capped to the stock's actual liquidity, so don't reject a setup just because the US market is closed. US hours give faster/deeper moves; off-hours favor continuation and drift plays (like the SPCX overnight short).
- Choose stock vs crypto purely on which gives the best risk/reward for GROWTH right now.
"""

    skip = ", ".join(open_coins) if open_coins else "none"
    performance = load_performance_summary()
    perf_section = (
        f"\n\nYour historical performance (USE AS CONTEXT, NOT RULES):\n{performance}"
        f"\nIMPORTANT: Small samples (<5 trades) are statistically meaningless — ignore them."
        f"\nA coin with 0/3 wins may simply have had 3 bad market days. A coin with 4/5 wins isn't guaranteed."
        f"\nIf technical signals are strong enough, enter even a historically weak coin — but require STRONGER confirmation."
        f"\nIf signals are weak/neutral, a poor history is a valid tiebreaker to skip."
    ) if performance else ""

    # פרמטר נוסף: פוזיציות פתוחות לרוטציה
    open_positions_rows = ""
    if open_positions:
        open_positions_rows = "\nCurrently open positions:\n" + "\n".join([
            f"  {p['coin']}: SIZE=${p.get('usd',0):.0f} | entry=${p['entry_price']:.4f} now=${p.get('current_price', p['entry_price']):.4f} "
            f"P&L={p.get('pnl_pct', 0):+.1f}% | open since {p.get('date_open','')[:10]} | "
            f"target={p.get('target_price',0):.4f} stop={p.get('stop_price',0):.4f}"
            for p in open_positions
        ])

    rotation_instruction = ""
    if open_positions:
        full = len(open_positions) >= MAX_OPEN
        rotation_instruction = f"""
CAPITAL IS LIMITED. Before concluding "no liquidity, do nothing" — review the ENTIRE portfolio above.
If you find a clearly better opportunity but margin/USDC is tight (see PORTFOLIO STATUS), you MAY free capital by
closing a WEAKER open position to fund it. Set "close_for_rotation" to that coin and explain in "rotation_reason".
Prefer rotating out of positions that are flat/negative or stalling far from target — never a winner moving toward target.
TINY POSITIONS ARE DEAD WEIGHT: a position sized under ~$100 barely moves the portfolio even when it wins big. If you
still believe in the trade, REBUILD it at proper size: set "close_for_rotation" to that coin AND pick the SAME coin in
"picks" with a real size_pct — the close and the re-entry happen in the same cycle. If you no longer believe in it,
close it and put the capital elsewhere.
{"Portfolio is FULL ("+str(len(open_positions))+"/"+str(MAX_OPEN)+") — you must close one to open a new trade." if full else "Only rotate if the new opportunity is clearly superior — don't churn for small differences."}
"""

    spot_section = ""
    if spot_holdings:
        spot_rows = "\n".join(f"  {s['coin']}: ${s['usd']:.0f}" for s in spot_holdings)
        spot_section = f"""
UNALLOCATED SPOT HOLDINGS — owned outright, NOT part of any managed swing position (no stop, no target, just parked):
{spot_rows}
This is reallocatable capital. A large passive holding should either be your highest-conviction idea or be partially
rotated into better setups — crypto OR stocks. To free capital, set "liquidate_spot": [{{"coin": "ETH", "usd": 150, "reason": "..."}}]
— it sells that much into USDC (available for entries next cycle). Max 2 liquidations, max $300 each. If a holding IS
the best place for the money right now, leave it and say so in skip_reason.
NOTE: while leveraged positions are open, Kraken may lock spot as collateral — a liquidation can be rejected or only
partially fill. If a liquidation keeps failing, don't repeat it every cycle; work with the free USDC instead.
"""

    prompt = f"""You are an expert swing trader covering both crypto and tokenized stocks (xStocks). {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC.

BTC context price: ${btc_price:,.0f}
Available USDC: ${usdc:.2f}
YOUR MANDATE: grow this portfolio aggressively. The owner explicitly accepts full risk on this capital — it's a dedicated aggressive-experiment budget. Safety rails (daily kill-switch at -20%, 50%/asset cap, stop on every trade) are always on — so swing for real gains, don't preserve capital timidly.
- FULLY INVESTED, ALWAYS: the owner's explicit doctrine is that USDC is a conversion medium, NOT a position. Any USDC above a ~$15 fee buffer should be working in a trade. If you're holding cash, your job this cycle is to find its best home — a decent B+ setup with a proper stop ALWAYS beats cash. "Waiting for a better entry" is a position choice you must justify in skip_reason, not a default.
- CONCENTRATE: back your 2-3 best setups with size, don't spread thin across 6 marginal picks.
- SIZE by conviction via "size_pct" (% of portfolio, 10-50). A+ setup (clear trend + volume + indicators aligned) → 40-50. Decent B+ → 15-25. Truly bad → skip.
- SET stop/target per trade via "stop_pct" and "target_pct" (decimals). Match them to the coin's volatility, NOT a fixed rule:
  · A fixed -2% stop on 5x gets wicked out by normal noise — give volatile coins room (stop_pct 0.03-0.05).
  · Let winners run — on strong momentum set target_pct 0.08-0.20, not a tiny +5%. Aim for asymmetric reward:risk (target ≥ 2x stop).
- 5x leverage applies to crypto longs/shorts.

PORTFOLIO STATUS:
{portfolio_summary}
{open_positions_rows}{spot_section}{perf_section}{rotation_instruction}

Crypto altcoin candidates ranked by 24h movement:
{crypto_rows}
{stock_section}
Your job: Think carefully and pick 0, 1, or 2 assets for a swing trade RIGHT NOW.
You can mix crypto and stocks — pick whatever has the best risk/reward today.

You can go LONG or SHORT on crypto:
- LONG ("direction":"long") — profit when price RISES. Use for momentum up / oversold bounce (RSI low, near support, MACD turning up).
- SHORT ("direction":"short") — profit when price FALLS. Use for exhausted/overbought assets (RSI > 70, BB% near 100, ran 10%+ and stalling, MACD turning down).
- SHORT works on BOTH crypto (margin) and stocks (Perps futures).
- Default to "long" if unsure. Only short when there is a clear downside setup — a short in a rising market loses money fast.

Criteria for LONG:
- Strong upward momentum with room to continue (not exhausted)
- Assets near intraday low that may bounce (dip buy)
- Volume confirming the move

Criteria for SHORT:
- Overbought and stalling (RSI > 70, BB% > 85) after a big run
- MACD histogram turning negative
- Rejection at resistance with volume

Criteria to avoid (either direction):
- Very low volume crypto (under $50k/day) or stocks (under $5k/day)
- Choppy sideways movement with no clear edge
- Rotating out of a position that's already profitable and moving toward target

Return ONLY valid JSON:
{{
  "picks": [
    {{
      "coin": "SOL",
      "direction": "long",
      "size_pct": 30,
      "stop_pct": 0.035,
      "target_pct": 0.12,
      "confidence": "HIGH",
      "reasoning": "שתי משפטים בעברית — מה בדיוק אתה רואה, למה עכשיו, ולמה לונג/שורט"
    }}
  ],
  "close_for_rotation": null,
  "liquidate_spot": [],
  "rotation_reason": null,
  "market_read": "משפט אחד בעברית על מצב השוק הכללי כרגע",
  "skip_reason": "למה דחית את השאר (משפט אחד בעברית)"
}}

If nothing looks tradeable at all — return picks as empty array. But remember the mandate: every trade has a stop, so a stopped-out loss is bounded and cheap, while weeks of idle cash compound to a real cost. When in doubt between a decent setup and cash — take the setup."""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=6000,  # חשיבה אדפטיבית נכללת בתקציב — צריך מרווח מעבר ל-JSON עצמו
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},  # הקריאה רצה כל שעה — medium חוסך ~חצי מטוקני החשיבה ($25/M)
            messages=[{"role": "user", "content": prompt}]
        )
        # עם חשיבה מופעלת בלוק הטקסט אינו בהכרח הראשון — חפש אותו במפורש
        raw = next((b.text for b in msg.content if b.type == "text"), "").strip()
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

def _pnl_pct(side: str, entry: float, current: float) -> float:
    """P&L באחוזים לפי כיוון. לונג: רווח כשעולה. שורט: רווח כשיורד."""
    if not entry or not current:
        return 0.0
    if side == "short":
        return round((entry - current) / entry * 100, 2)
    return round((current - entry) / entry * 100, 2)


def _targets_for_side(side: str, entry: float, target_pct: float, stop_pct: float, price_dec: int) -> tuple[float, float]:
    """מחזיר (target_price, stop_price) לפי כיוון.
    לונג: target מעל הכניסה, stop מתחת. שורט: הפוך."""
    if side == "short":
        target = round(entry * (1 - target_pct), price_dec)
        stop   = round(entry * (1 + stop_pct), price_dec)
    else:
        target = round(entry * (1 + target_pct), price_dec)
        stop   = round(entry * (1 - stop_pct), price_dec)
    return target, stop


_COIN_ALIASES = {"XDG": "DOGE", "XBT": "BTC", "XET": "ETH"}

def _pair_to_coin(pair: str) -> str:
    """ממיר פאיר של קרקן לשם מטבע. XRPUSDC→XRP, ETHUSDC→ETH, XDGUSDC→DOGE"""
    kraken_map = {"XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC", "XXLM": "XLM", "XDGE": "DOGE", "XDG": "DOGE"}
    coin = pair.replace("USDC", "").replace("USD", "")
    return kraken_map.get(coin, coin)

def _canonical(coin: str) -> str:
    """נרמל שם מטבע ל-canonical לחיפוש ב-CANDIDATES/MARGIN_ELIGIBLE.
    נדרש לרשומות ישנות שנשמרו עם שם Kraken הפנימי (XDG במקום DOGE וכו')."""
    return _COIN_ALIASES.get(coin, coin)


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
            # קרקן: type="buy" → לונג | type="sell" → שורט
            side = "short" if p.get("type") == "sell" else "long"
            state["margin_positions"][coin] = {
                "pair":   p.get("pair"),
                "vol":    abs(float(p.get("vol", 0))),
                "cost":   abs(float(p.get("cost", 0))),
                "margin": float(p.get("margin", 0)),
                "txid":   p.get("ordertxid", ""),
                "side":   side,
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
        # שורט: הפוזיציה "קיימת" רק במרג'ין, לא ב-balance (אין מטבע ביד)
        side = t.get("side", "long")
        if not in_margin and (side == "short" or not in_balance):
            current = get_current_price(t["pair"])
            pnl_pct = _pnl_pct(side, t["entry_price"], current)
            t["status"]      = "closed_profit" if pnl_pct >= 0 else "closed_loss"
            t["date_close"]  = datetime.now().isoformat()
            t["close_price"] = current or t.get("current_price", t["entry_price"])
            t["pnl_pct"]     = pnl_pct
            t["pnl_usd"]     = round(pnl_pct / 100 * t.get("usd", 0), 2)
            changed = True
            logging.warning(f"[Sync] {coin} נסגר בקרקן | P&L≈{pnl_pct:+.1f}%")
            archive_closed_trade(t)
            if pnl_pct >= 0:
                _send_trade_alert(
                    f"✅ סגירת רווח: {coin}",
                    f"מטבע: {coin}\nיציאה: ${current:.4f}\nכניסה: ${t['entry_price']:.4f}\nרווח: {pnl_pct:+.1f}% (${t['pnl_usd']:+.2f})"
                )
            else:
                _send_trade_alert(
                    f"🔴 סגירה בהפסד: {coin}",
                    f"מטבע: {coin}\nיציאה: ${current:.4f}\nכניסה: ${t['entry_price']:.4f}\nהפסד: {pnl_pct:+.1f}% (${t['pnl_usd']:+.2f})"
                )

    # כיוון 2: פתח מחדש מה שקרקן אומר שפתוח אבל JSON לא יודע עליו
    open_coins_in_json = {t["coin"] for t in trades if t.get("status") == "open"}
    for coin, kpos in kraken["margin_positions"].items():
        if coin in open_coins_in_json:
            continue
        # חפש רשומה קיימת בJSON (יכול להיות closed_externally בטעות)
        existing = next((t for t in trades if t["coin"] == coin and t.get("pair") == kpos["pair"]), None)
        if existing:
            # אם סגרנו אותה בכוונה (יש close_txid — פקודת מכירה עובדת בקרקן),
            # אל תפתח מחדש. הפוזיציה בתהליך סגירה — ממתינה שה-limit יבוצע.
            if existing.get("close_txid"):
                continue
            existing["status"]     = "open"
            existing["date_close"] = None
            changed = True
            logging.warning(f"[Sync] {coin} IS open in Kraken but was closed in JSON → reopened")
        else:
            # פוזיציה חדשה שהבוט לא פתח — הוסף אותה עם הכיוון הנכון מקרקן
            current  = get_current_price(kpos["pair"])
            side     = kpos.get("side", "long")
            entry    = round(kpos["cost"] / kpos["vol"], 6) if kpos["vol"] else current
            pdec     = CANDIDATES.get(coin, {}).get("price_dec", 6)
            target_p, stop_p = _targets_for_side(side, entry, TARGET_PCT, STOP_PCT, pdec)
            trades.append({
                "coin":         coin,
                "pair":         kpos["pair"],
                "side":         side,
                "entry_price":  entry,
                "limit_price":  entry,
                "volume":       kpos["vol"],
                "usd":          round(kpos["cost"], 2),
                "target_price": target_p,
                "stop_price":   stop_p,
                "date_open":    datetime.now().isoformat(),
                "date_close":   None,
                "status":       "open",
                "confidence":   "MEDIUM",
                "reasoning":    f"Restored from Kraken OpenPositions ({side})",
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
            logging.warning(f"[Sync] {coin} ({side}) found in Kraken but missing from JSON → added")

    return trades, changed


def reconcile_stock_trades(trades: list) -> tuple[list, bool]:
    """סנכרון מניות מול Kraken Futures — דו-כיווני:
    1) רשומה 'open' בלי פוזיציה ובלי פקודה בקרקן = רפאים → נסגרת.
    2) גודל הרשומה מסונכרן לגודל האמיתי בקרקן (מילוי חלקי!).
    3) פוזיציה אמיתית בקרקן בלי רשומה = יתומה → מאומצת לניהול (סטופ/יעד/מעקב)."""
    changed = False
    open_stocks = [t for t in trades if t.get("status") == "open" and t.get("is_stock")]
    try:
        from kraken_futures import get_futures_positions, cancel_futures_order, _request
        positions = get_futures_positions()
        pos_syms  = {p.get("symbol") for p in positions}
        try:
            oo = _request("/openorders").get("openOrders", [])
        except Exception:
            oo = []
        order_syms = {o.get("symbol") for o in oo}
    except Exception as e:
        logging.warning(f"[StockSync] לא הצליח למשוך מצב Futures: {e}")
        return trades, changed

    # ── כיוון 3: אימוץ פוזיציות יתומות — קיימות בקרקן, לא מנוהלות אצלנו ──
    # (מילוי חלקי ישן, פקודה ששרדה ניקוי רפאים וכו'. בלי זה הן בלי סטופ לנצח.)
    tracked_syms = {t.get("pair") for t in open_stocks}
    for p in positions:
        sym = str(p.get("symbol", ""))
        if not sym.startswith("PF_") or sym in tracked_syms:
            continue
        if sym in order_syms:
            # יש פקודה תלויה על הסימבול (למשל סגירה שטרם התמלאה) — לא לאמץ מחדש!
            # אימוץ כזה יצר היום רשומת MSTR כפולה עם סגירה כפולה ומייל כפול.
            continue
        ticker = sym.replace("PF_", "").replace("XUSD", "")
        if ticker in _KNOWN_CRYPTO:
            continue  # רק xStocks — קריפטו perps לא מנוהל כאן
        p_size  = abs(float(p.get("size", 0) or 0))
        p_price = float(p.get("price", 0) or 0)
        if p_size <= 0 or p_price <= 0:
            continue
        p_side = "short" if str(p.get("side", "")).lower() == "short" else "long"
        tgt, stp = _targets_for_side(p_side, p_price, TARGET_PCT_STOCK, STOP_PCT_STOCK, 2)
        trades.append({
            "coin": ticker, "pair": sym, "is_stock": True, "is_futures": True,
            "side": p_side, "entry_price": p_price, "limit_price": p_price,
            "volume": p_size, "usd": round(p_size * p_price, 2),
            "target_price": tgt, "stop_price": stp,
            "date_open": datetime.now().isoformat(), "date_close": None,
            "status": "open", "confidence": "MEDIUM",
            "reasoning": "Adopted from Kraken Futures — untracked position (partial fill?)",
            "market_read": "", "current_price": p_price,
            "pnl_pct": 0.0, "pnl_usd": 0.0,
            "txid": "", "sell_txid": None, "close_price": None, "close_txid": None,
        })
        changed = True
        logging.warning(f"[StockSync] {ticker} ({p_side}, {p_size}x${p_price}) קיים בקרקן ללא רשומה → אומץ לניהול")

    for t in open_stocks:
        sym = t.get("pair")
        if sym in pos_syms:
            # פוזיציה קיימת — סנכרן גודל אמיתי (מילוי חלקי משאיר רשומה מנופחת)
            kp = next((p for p in positions if p.get("symbol") == sym), None)
            if kp:
                real = abs(float(kp.get("size", 0) or 0))
                rec  = float(t.get("volume", 0) or 0)
                if real > 0 and rec > 0 and abs(real - rec) > max(1e-6, 0.02 * rec):
                    logging.warning(f"[StockSync] {t.get('coin')} רשום {rec} אבל בקרקן {real} — מסנכרן גודל")
                    t["volume"] = real
                    t["usd"]    = round(real * float(t.get("entry_price", 0) or 0), 2)
                    changed = True
            continue
        if sym in order_syms:
            continue  # פקודת כניסה עדיין ממתינה לביצוע — תקין
        # אין פוזיציה ואין פקודה → רפאים (הפקודה לא בוצעה או נסגרה)
        if t.get("sell_txid"):
            try:
                cancel_futures_order(t["sell_txid"])
            except Exception:
                pass
        t["status"]     = "closed_externally"
        t["date_close"] = datetime.now().isoformat()
        t["close_price"] = t.get("entry_price")
        t["pnl_pct"]    = 0.0
        t["pnl_usd"]    = 0.0
        changed = True
        logging.warning(f"[StockSync] {t.get('coin')} (מניה) לא קיים ב-Kraken — מנקה רפאים")
        archive_closed_trade(t)
    return trades, changed


def check_open_swings(balance: dict, request_fn) -> list:
    """נקרא כל 15 דקות — בודק אם פוזיציות פתוחות הגיעו ליעד/stop"""
    trades  = load_swing_trades()

    # סנכרון עם קרקן — בודק balance + OpenPositions, סוגר מה שלא קיים
    trades, sync_changed = sync_trades_with_kraken(trades, balance, request_fn)
    # סנכרון מניות נפרד (Futures) — מנקה רפאים
    trades, stock_changed = reconcile_stock_trades(trades)
    changed = sync_changed or stock_changed

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

        side    = t.get("side", "long")
        pnl_pct = _pnl_pct(side, entry, current)
        t["current_price"] = round(current, 6)
        t["pnl_pct"]       = pnl_pct
        t["pnl_usd"]       = round((entry - current) * vol, 2) if side == "short" else round((current - entry) * vol, 2)
        changed = True

        # Trailing stop — נעילת רווח: ב-+4% הסטופ עולה לברייק-איבן+1%, ב-+6% עוקב 3% אחרי המחיר.
        # הסטופ רק מתהדק לכיוון הרווח, לעולם לא מתרחב חזרה.
        if side == "long":
            trail = current * 0.97 if pnl_pct >= 6.0 else (entry * 1.01 if pnl_pct >= 4.0 else None)
            if trail and trail > t["stop_price"]:
                t["stop_price"] = round(trail, 6)
                logging.info(f"[Swing] {coin} trailing stop → {t['stop_price']} (P&L {pnl_pct:+.1f}%)")
        else:
            trail = current * 1.03 if pnl_pct >= 6.0 else (entry * 0.99 if pnl_pct >= 4.0 else None)
            if trail and trail < t["stop_price"]:
                t["stop_price"] = round(trail, 6)
                logging.info(f"[Swing] {coin} trailing stop → {t['stop_price']} (P&L {pnl_pct:+.1f}%)")

        # זיהוי יעד/stop לפי כיוון.
        # לונג: יעד מעל הכניסה, stop מתחת. שורט: יעד מתחת, stop מעל.
        reason = None
        if side == "short":
            if current <= t["target_price"]:
                reason = "profit"
            elif current >= t["stop_price"]:
                reason = "loss"
        else:
            if current >= t["target_price"]:
                reason = "profit"
            elif current <= t["stop_price"]:
                reason = "loss"

        # יציאת זמן — פוזיציה שעברה MAX_HOLD_HOURS בלי להגיע לשום מקום תוקעת הון
        # שיכול לעבוד בסטאפ אחר (זה סווינג שעתי/יומי, לא buy&hold)
        if not reason:
            try:
                age_h = (datetime.now() - datetime.fromisoformat(t["date_open"])).total_seconds() / 3600
            except Exception:
                age_h = 0
            if age_h >= MAX_HOLD_HOURS and pnl_pct < STALE_EXIT_MIN_PNL:
                reason = "stale"
                logging.info(f"[Swing] {coin} פתוח {age_h:.0f} שעות עם P&L {pnl_pct:+.1f}% — יציאת זמן")

        if reason:
            cfg       = CANDIDATES.get(_canonical(coin), CANDIDATES.get(coin, {}))
            price_dec = cfg.get("price_dec", 4)

            if reason == "profit" and t.get("sell_txid"):
                # יש כבר פקודת TP עובדת בקרקן ביעד (sell ללונג / buy לשורט).
                # אל תסמן "סגור" לפי מחיר ticker — קרקן יבצע את הפקודה ביעד אמיתי.
                # הסימון כסגור + המייל יקרו דרך הסנכרון כשהפוזיציה באמת תיעלם מקרקן.
                logging.info(f"[Swing] {coin} ({side}) ב-target ${current:.4f} — פקודת TP עובדת בקרקן, ממתין")
                continue
            else:
                # סגירה הפוכה: שורט→buy, לונג→sell
                close_type = "buy" if side == "short" else "sell"
                lp = round(current * (1.001 if side == "short" else 0.999), price_dec)

                # סטטוס וכותרת מייל לפי סיבת הסגירה
                if reason == "stale":
                    new_status  = "closed_stale"
                    alert_title = f"⏰ יציאת זמן (>{MAX_HOLD_HOURS}h): {coin}"
                elif pnl_pct >= 0:
                    new_status  = "closed_profit"
                    alert_title = f"✅ סגירת רווח: {coin}"
                else:
                    new_status  = "closed_loss"
                    alert_title = f"🔴 Stop-Loss: {coin}"

                if t.get("is_stock") and t.get("is_futures"):
                    # ── מניה — דרך Kraken Futures Perps ──────────────────
                    from kraken_futures import place_futures_order, cancel_futures_order
                    if t.get("sell_txid"):
                        try:
                            cancel_futures_order(t["sell_txid"])
                            logging.info(f"[Swing] Cancelled Futures TP {t['sell_txid']} for {coin}")
                        except Exception as ce:
                            logging.warning(f"[Swing] cancel futures TP failed: {ce}")
                    try:
                        # mkt + reduceOnly: ביצוע ודאי, ולעולם לא פותח פוזיציה הפוכה בטעות
                        txid = place_futures_order(pair, close_type, vol, lp, order_type="mkt", reduce_only=True)
                        t["status"]      = new_status
                        t["date_close"]  = datetime.now().isoformat()
                        t["close_price"] = current
                        t["close_txid"]  = txid
                        logging.info(f"[Swing] CLOSE {reason.upper()} {coin} (מניה {side}) @ {current:.4f} | P&L {pnl_pct:+.1f}% | {close_type} txid={txid}")
                        archive_closed_trade(t)
                        _send_trade_alert(
                            f"{alert_title} (מניה)",
                            f"מניה: {coin} ({side})\nיציאה: ${current:.4f}\nכניסה: ${t['entry_price']:.4f}\nP&L: {pnl_pct:+.1f}% (${t['pnl_usd']:+.2f})"
                        )
                    except Exception as e:
                        logging.error(f"[Swing] stock stop close failed {coin}: {e}")
                    continue

                # ── קריפטו — דרך Spot/Margin API ─────────────────────
                if t.get("sell_txid"):
                    try:
                        request_fn("/0/private/CancelOrder", {"txid": t["sell_txid"]}, private=True)
                        logging.info(f"[Swing] Cancelled TP order {t['sell_txid']} for {coin}")
                    except Exception as ce:
                        logging.warning(f"[Swing] cancel TP failed: {ce}")

                use_lev = _canonical(coin) in MARGIN_ELIGIBLE
                if side == "short":
                    close_vol = vol
                else:
                    holding   = float(balance.get(coin, 0))
                    close_vol = vol if use_lev else min(vol, holding)

                if close_vol < cfg.get("min_vol", 0.0000001):
                    logging.warning(f"[Swing] {coin} volume {close_vol} below min — cannot close")
                    continue
                try:
                    stop_params = {
                        "pair": pair, "type": close_type, "ordertype": "limit",
                        "volume": f"{close_vol:.8f}", "price": f"{lp:.{price_dec}f}",
                    }
                    if use_lev:
                        stop_params["leverage"] = str(LEVERAGE)
                    res  = request_fn("/0/private/AddOrder", stop_params, private=True)
                    txid = list(res.get("txid", ["?"]))[0]
                    t["status"]      = new_status
                    t["date_close"]  = datetime.now().isoformat()
                    t["close_price"] = current
                    t["close_txid"]  = txid
                    logging.info(f"[Swing] CLOSE {reason.upper()} {coin} ({side}) @ {current:.4f} | P&L {pnl_pct:+.1f}% | {close_type} txid={txid}")
                    archive_closed_trade(t)
                    _send_trade_alert(
                        alert_title,
                        f"מטבע: {coin} ({side})\nיציאה: ${current:.4f}\nכניסה: ${t['entry_price']:.4f}\nP&L: {pnl_pct:+.1f}% (${t['pnl_usd']:+.2f})"
                    )
                except Exception as e:
                    logging.error(f"[Swing] stop close failed {coin}: {e}")

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

def run_swing_scan(balance: dict, usdc: float, request_fn, btc_price: float = 0, portfolio_usd: float = 0) -> list:
    """נקרא כל שעה — Claude סורק ובוחר מועמדים"""
    from risk_manager import (
        get_portfolio_exposure, can_open_position, get_weakest_position,
        build_portfolio_summary, update_drawdown, is_kill_switch_active
    )

    trades      = load_swing_trades()
    open_swings = [t for t in trades if t.get("status") == "open"]
    open_coins  = {t["coin"] for t in open_swings}

    # מעקב edge — האם האסטרטגיה באמת רווחית? (win-rate + תוחלת לעסקה)
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding="utf-8") as f:
                _hist = json.load(f)
            if _hist:
                _wins = [h for h in _hist if h.get("pnl_usd", 0) > 0]
                _wr   = len(_wins) / len(_hist) * 100
                _tot  = sum(h.get("pnl_usd", 0) for h in _hist)
                _exp  = _tot / len(_hist)
                logging.info(f"[Edge] {len(_hist)} עסקאות | win-rate {_wr:.0f}% | תוחלת ${_exp:+.2f}/עסקה | סהכ ${_tot:+.2f}")
    except Exception:
        pass

    # עדכן drawdown יומי
    if portfolio_usd:
        update_drawdown(portfolio_usd)

    # kill-switch — אם הפסדנו יותר מדי היום, עצור הכל
    if is_kill_switch_active(portfolio_usd):
        logging.warning("[RiskManager] Kill switch active — skipping scan")
        return trades

    if usdc < 10:
        # USDC נמוך אינו סוף פסוק — כסף בארנק Futures עדיין יכול לפתוח מניות
        try:
            from kraken_futures import get_futures_balance as _gfb
            _fut_bal = _gfb()
        except Exception:
            _fut_bal = 0.0
        if _fut_bal < 10:
            logging.info(f"[Swing] USDC critically low ${usdc:.2f} וגם Futures ריק — skipping scan")
            return trades

    margin_used = get_margin_used(request_fn)
    # headroom אמיתי: גם תקרת המרג'ין הסינתטית, וגם כוח הקנייה האמיתי לפי USDC פנוי.
    # אם USDC שלילי/נמוך (פקודות פתוחות תופסות אותו) — אין באמת מקום, גם אם המרג'ין פנוי.
    synthetic_cap   = max(0, 400 - margin_used)   # הועלה מ-200 — המנדט האגרסיבי צריך מקום
    real_buying_pwr = max(0, usdc) * LEVERAGE        # USDC פנוי × מינוף
    margin_headroom = min(synthetic_cap, real_buying_pwr)
    logging.info(f"[Swing] Margin used: ${margin_used:.0f} | USDC ${usdc:.0f} | headroom אמיתי: ${margin_headroom:.0f}")

    # חשיפת תיק מלאה
    exposure = get_portfolio_exposure(open_swings, portfolio_usd or (usdc + sum(t.get("usd",0) for t in open_swings)))

    candidates = get_candidate_data()
    if not candidates:
        logging.warning("[Swing] No candidate data available")
        return trades

    # שלוף xStocks דינמית
    stock_candidates = get_xstock_data()

    # ── תצפית מרחוק — למה הבוט מחליט מה שהוא מחליט (נדחף לגיט כל שעה) ──
    debug = {
        "time":             datetime.now().isoformat(timespec="seconds"),
        "usdc":             round(usdc, 2),
        "portfolio":        round(portfolio_usd or 0, 2),
        "margin_headroom":  round(margin_headroom, 2),
        "open":             [f"{t['coin']} {t.get('side','?')} {t.get('pnl_pct',0):+.1f}%" for t in open_swings],
        "stock_candidates": len(stock_candidates),
        "top_stocks": [
            f"{s['coin']} {s.get('change_24h',0):+.1f}% vol=${s.get('volume_usdc',0):,.0f}"
            for s in sorted(stock_candidates, key=lambda x: -abs(x.get("change_24h", 0)))[:5]
        ],
    }
    # בדיקת חיבור Futures — אם המפתחות חסרים בשרת, שום קוד לא יפתח מניות
    try:
        from kraken_futures import _request as _fut_req
        _flex = _fut_req("/accounts").get("accounts", {}).get("flex", {})
        debug["futures_ok"] = True
        debug["futures_balance"] = round(float(_flex.get("availableMargin", 0) or 0), 2)
    except Exception as _fe:
        debug["futures_ok"] = False
        debug["futures_error"] = str(_fe)[:200]

    # תחזוקת float בארנק Futures — שכניסת מניה לא תיפול על העברה נקודתית
    try:
        if debug.get("futures_ok") and debug.get("futures_balance", 0) < 40 and usdc > 60:
            from kraken_futures import transfer_spot_to_futures
            debug["futures_float_topup"] = bool(transfer_spot_to_futures(50))
    except Exception as _te:
        debug["futures_float_topup"] = f"failed: {str(_te)[:80]}"

    # בנה lookup מהיר לפי coin
    all_candidates_map = {c["coin"]: c for c in candidates}
    for s in stock_candidates:
        all_candidates_map[s["coin"]] = s

    # בנה תמונת תיק מלאה לקלוד
    portfolio_summary = build_portfolio_summary(exposure, open_swings, margin_used, margin_headroom)

    # ── הון ספוט לא מנוהל — מועמד להצרחה (למשל ETH של האסטרטגיה היומית) ──
    # פוזיציות ה-swing ממונפות/Futures ולא יושבות ב-balance; מה שכן — הון חונה.
    spot_holdings = []
    try:
        swing_spot_coins = {t["coin"] for t in open_swings if not t.get("is_stock")}
        for b_coin, b_qty in (balance or {}).items():
            if b_coin in ("USDC", "USD", "ZUSD", "EUR") or float(b_qty) <= 0:
                continue
            if b_coin in swing_spot_coins:
                continue  # ליתר ביטחון — לא מציעים למכור מטבע עם פוזיציית swing חיה
            cd = all_candidates_map.get(b_coin)
            px = cd["price"] if cd else 0
            if not px:
                pair_g = CANDIDATES.get(b_coin, {}).get("pair")
                px = get_current_price(pair_g) if pair_g else 0
            val = float(b_qty) * px
            if val >= 25:
                spot_holdings.append({"coin": b_coin, "qty": float(b_qty), "usd": round(val, 2), "price": px})
        spot_holdings.sort(key=lambda s: -s["usd"])
    except Exception as e:
        logging.warning(f"[Swing] spot holdings calc failed: {e}")
    debug["unallocated_spot"] = [f"{s['coin']} ${s['usd']:.0f}" for s in spot_holdings]

    open_coins_set = {t["coin"] for t in open_swings}

    # סינון חכם — קרא לClaude רק אם יש סיגנל אמיתי
    def _should_call_claude(candidates: list, open_swings: list) -> tuple[bool, str]:
        # פוזיציה עם בעיה — P&L שלילי מעל 1% או קרובה לסטופ
        weak = [t for t in open_swings if t.get("pnl_pct", 0) < -1.0]
        if weak:
            coins = ", ".join(t["coin"] for t in weak)
            return True, f"פוזיציה חלשה: {coins}"
        # אין פוזיציות — צריך לחפש הזדמנויות
        if not open_swings:
            return True, "אין פוזיציות פתוחות — סורק הזדמנויות"

        # יש כסף פנוי לפתוח פוזיציה חדשה? אם כן — ספים רגישים. אם לא — רק סיגנל חזק ששווה רוטציה.
        has_capacity = len(open_swings) < MAX_OPEN and margin_headroom >= (SWING_MIN_USD / LEVERAGE)
        move_thr = 3.0 if has_capacity else 5.0   # מרג'ין מלא → רק תנועה חזקה מאוד שווה רוטציה
        rsi_lo, rsi_hi = (35, 65) if has_capacity else (30, 70)

        # רף נפח — מטבע עם נפח יומי נמוך לא ניתן לסחור בו, אז אין טעם לשאול את Claude עליו
        # (Claude פוסל אותם ממילא — VET בנפח $563 נדחה 6 פעמים רצוף)
        MIN_TRIGGER_VOL = 50000
        tradeable = [c for c in candidates if c.get("volume_usdc", 0) >= MIN_TRIGGER_VOL and c["coin"] not in open_coins_set]

        strong_move = [c for c in tradeable if abs(c.get("change_24h", 0)) >= move_thr]
        if strong_move:
            coins = ", ".join(c["coin"] for c in strong_move[:3])
            tag = "" if has_capacity else " (שקילת רוטציה — מרג'ין מלא)"
            return True, f"תנועה חזקה במטבע חדש: {coins}{tag}"
        extreme_rsi = [c for c in tradeable if c.get("rsi") and (c["rsi"] < rsi_lo or c["rsi"] > rsi_hi)]
        if extreme_rsi:
            coins = ", ".join(c["coin"] for c in extreme_rsi[:3])
            return True, f"RSI קיצוני: {coins}"
        # מניות (xStocks) — הסינון למעלה בודק רק קריפטו; בלעדי זה סטאפ מניות
        # בשעות המסחר בארה"ב לא מגיע לקלוד לעולם. סף נמוך מקריפטו — 3% במניה זה יום גדול
        stock_thr = max(2.0, move_thr - 1.0)
        stock_movers = [
            c for c in (stock_candidates or [])
            if c["coin"] not in open_coins_set and abs(c.get("change_24h", 0)) >= stock_thr
        ]
        if stock_movers:
            coins = ", ".join(c["coin"] for c in stock_movers[:3])
            return True, f"תנועה חזקה במניה: {coins}"
        # דוקטרינת תיק-מושקע-תמיד: USDC הוא צינור המרה, לא עמדה. כל סכום שאפשר
        # לפתוח בו עסקה (מעל מינימום קרקן) מפעיל סריקה — ה-snapshot מונע ספam
        if usdc >= 30 and tradeable and len(open_swings) < MAX_OPEN:
            return True, f"USDC ${usdc:.0f} לא מושקע — מחפש לו בית (תיק מושקע תמיד)"
        return False, "הכל שקט — דולג על קריאה לClaude"

    should_call, call_reason = _should_call_claude(candidates, open_swings)
    debug["call_reason"] = call_reason
    if not should_call:
        logging.info(f"[Swing] {call_reason}")
        debug["claude_called"] = False
        _write_debug(debug)
        return trades

    # בדיקת שינוי-מצב — אל תשאל את Claude שוב על מצב זהה לפעם הקודמת.
    # בונים "תמונת מצב" גסה: מטבע ב-+3% נשאר באותה תמונה כל עוד לא קפץ מדרגה.
    def _build_snapshot(candidates: list, open_swings: list) -> str:
        parts = []
        for t in sorted(open_swings, key=lambda x: x["coin"]):
            state = "weak" if t.get("pnl_pct", 0) < -1.0 else "ok"
            parts.append(f"P:{t['coin']}:{state}")
        open_coins_set = {t["coin"] for t in open_swings}
        for c in sorted(candidates, key=lambda x: x["coin"]):
            if c["coin"] in open_coins_set:
                continue
            chg = c.get("change_24h", 0)
            if abs(chg) >= (2.0 if c.get("is_stock") else 3.0):
                parts.append(f"M:{c['coin']}:{int(chg)}")  # מדרגות של 1%
            rsi = c.get("rsi")
            if rsi and (rsi < 35 or rsi > 65):
                parts.append(f"R:{c['coin']}:{int(rsi // 5 * 5)}")  # מדרגות של 5
        return "|".join(parts)

    # מניות נכללות בתמונת המצב — אחרת שינוי במניה לא נחשב "מצב חדש" וקלוד לא נשאל
    snapshot      = _build_snapshot(candidates + stock_candidates, open_swings)
    snapshot_file = os.path.join(DIR, "last_claude_snapshot.txt")
    last_snapshot = ""
    if os.path.exists(snapshot_file):
        try:
            with open(snapshot_file, encoding="utf-8") as f:
                last_snapshot = f.read().strip()
        except Exception:
            pass

    if snapshot and snapshot == last_snapshot:
        logging.info(f"[Swing] מצב זהה לפעם הקודמת ({call_reason}) — דולג על Claude")
        debug["claude_called"] = False
        debug["skip"] = "snapshot זהה לקריאה הקודמת"
        _write_debug(debug)
        return trades

    # שמור את התמונה החדשה לפני הקריאה
    try:
        with open(snapshot_file, "w", encoding="utf-8") as f:
            f.write(snapshot)
    except Exception:
        pass

    logging.info(f"[Swing] קורא לClaude: {call_reason}")
    analysis    = analyze_with_claude(candidates, open_coins, usdc, btc_price, stock_candidates, open_swings, portfolio_summary, spot_holdings)
    market_read = analysis.get("market_read", "")
    skip_reason = analysis.get("skip_reason", "")
    logging.info(f"[Swing] Claude: {market_read} | skipped: {skip_reason}")
    debug["claude_called"] = True
    debug["market_read"]   = market_read
    debug["skip_reason"]   = skip_reason
    debug["picks"] = [
        f"{p.get('coin')} {p.get('direction','long')} size={p.get('size_pct')}% conf={p.get('confidence')}"
        for p in analysis.get("picks", [])
    ]

    # רוטציה — קלוד ביקש לסגור פוזיציה חלשה כדי לפתוח חדשה
    close_for_rotation = analysis.get("close_for_rotation")
    if close_for_rotation and close_for_rotation in open_coins:
        rotation_reason = analysis.get("rotation_reason", "")
        logging.info(f"[Swing] ROTATION: closing {close_for_rotation} — {rotation_reason}")
        for t in trades:
            if t.get("coin") == close_for_rotation and t.get("status") == "open":
                is_fut_stock = t.get("is_stock") and t.get("is_futures")
                if is_fut_stock:
                    from kraken_futures import get_futures_price
                    current = get_futures_price(t["pair"])
                else:
                    current = get_current_price(t["pair"])
                if current > 0:
                    cfg_r     = CANDIDATES.get(close_for_rotation, all_candidates_map.get(close_for_rotation, {}))
                    price_dec = cfg_r.get("price_dec", 4)
                    r_side    = t.get("side", "long")
                    close_type = "buy" if r_side == "short" else "sell"
                    lp        = round(current * (1.001 if r_side == "short" else 0.999), price_dec)
                    use_lev   = (r_side == "short") or (close_for_rotation in MARGIN_ELIGIBLE and not t.get("is_stock"))
                    try:
                        if is_fut_stock:
                            # ── מניה — סגירה דרך Kraken Futures Perps ──────────
                            from kraken_futures import place_futures_order, cancel_futures_order
                            if t.get("sell_txid"):
                                try:
                                    cancel_futures_order(t["sell_txid"])
                                except Exception as ce:
                                    logging.info(f"[Swing] TP futures כבר בוצע/לא קיים ({close_for_rotation}): {ce}")
                            txid = place_futures_order(t["pair"], close_type, t["volume"], lp, order_type="mkt", reduce_only=True)
                        else:
                            if t.get("sell_txid"):
                                try:
                                    request_fn("/0/private/CancelOrder", {"txid": t["sell_txid"]}, private=True)
                                except Exception as ce:
                                    logging.info(f"[Swing] TP כבר בוצע/לא קיים ({close_for_rotation}): {ce}")
                            sell_params = {
                                "pair": t["pair"], "type": close_type, "ordertype": "limit",
                                "volume": f"{t['volume']:.8f}", "price": f"{lp:.{price_dec}f}",
                            }
                            if use_lev:
                                sell_params["leverage"] = str(LEVERAGE)
                            res  = request_fn("/0/private/AddOrder", sell_params, private=True)
                            txid = list(res.get("txid", ["?"]))[0]
                        pnl_pct_r        = _pnl_pct(r_side, t["entry_price"], current)
                        t["status"]      = "closed_profit" if pnl_pct_r >= 0 else "closed_loss"
                        t["date_close"]  = datetime.now().isoformat()
                        t["close_price"] = current
                        t["close_txid"]  = txid
                        t["pnl_pct"]     = pnl_pct_r
                        t["pnl_usd"]     = round((t["entry_price"] - current) * t["volume"], 2) if r_side == "short" else round((current - t["entry_price"]) * t["volume"], 2)
                        archive_closed_trade(t)
                        open_coins.discard(close_for_rotation)
                        open_swings = [s for s in open_swings if s["coin"] != close_for_rotation]
                        logging.info(f"[Swing] Rotation close {close_for_rotation} @ {current:.4f} P&L={t['pnl_pct']:+.1f}%")
                    except Exception as e:
                        logging.error(f"[Swing] Rotation close failed {close_for_rotation}: {e}")
                else:
                    logging.warning(f"[Swing] Rotation close {close_for_rotation} skipped — no price (futures={is_fut_stock})")
                break

    # ── הצרחת הון — קלוד ביקש לממש החזקת ספוט לא מנוהלת לטובת סטאפים טובים יותר ──
    for liq in (analysis.get("liquidate_spot") or [])[:2]:
        try:
            l_coin = str(liq.get("coin", ""))
            l_usd  = float(liq.get("usd", 0))
            hold   = next((s for s in spot_holdings if s["coin"] == l_coin), None)
            if not hold or l_usd < 25:
                continue
            l_usd  = min(l_usd, 300.0, hold["usd"])
            cfg_l  = CANDIDATES.get(l_coin, {})
            pair_l = cfg_l.get("pair") or all_candidates_map.get(l_coin, {}).get("pair")
            if not pair_l or not hold["price"]:
                continue
            pd_l = cfg_l.get("price_dec", all_candidates_map.get(l_coin, {}).get("price_dec", 4))
            lp   = round(hold["price"] * 0.999, pd_l)   # marketable — מתבצע מיד ליד השוק
            volq = min(round(l_usd / hold["price"], 8), hold["qty"])
            if volq < cfg_l.get("min_vol", 0.0000001):
                continue
            # קרקן נועל חלק מהספוט כבטוחה למינוף → "Insufficient funds" גם כשה-balance מראה מספיק.
            # מנסים בחצאים — מוכרים כמה שקרקן משחרר במקום להיכשל על הכל.
            res, min_v_l = None, cfg_l.get("min_vol", 0.0000001)
            for attempt_vol in (volq, round(volq / 2, 8), round(volq / 4, 8)):
                if attempt_vol < min_v_l:
                    break
                try:
                    res = request_fn("/0/private/AddOrder", {
                        "pair": pair_l, "type": "sell", "ordertype": "limit",
                        "volume": f"{attempt_vol:.8f}", "price": f"{lp:.{pd_l}f}",
                    }, private=True)
                    volq, l_usd = attempt_vol, round(attempt_vol * hold["price"], 2)
                    break
                except Exception as le:
                    if "insufficient" not in str(le).lower():
                        raise
                    logging.info(f"[Swing] liquidate {l_coin}: {attempt_vol} נדחה (בטוחה נעולה) — מנסה חצי")
            if res is None:
                debug.setdefault("order_errors", []).append(f"liq {l_coin}: all sizes rejected (margin collateral lock)")
                continue
            txid_l = list(res.get("txid", ["?"]))[0]
            l_reason = str(liq.get("reason", ""))[:150]
            logging.warning(f"[Swing] LIQUIDATE spot {l_coin} ${l_usd:.0f} (vol {volq}) txid={txid_l} | {l_reason}")
            debug.setdefault("liquidations", []).append(f"{l_coin} ${l_usd:.0f}")
            _send_trade_alert(
                f"🔄 הצרחת הון: מכירת {l_coin}",
                f"מומשו ${l_usd:.0f} מהחזקת ספוט ב-{l_coin} לשחרור הון לעסקאות טובות יותר.\nסיבה: {l_reason}"
            )
        except Exception as e:
            logging.error(f"[Swing] liquidate_spot failed {liq}: {e}")
            debug.setdefault("order_errors", []).append(f"liq {liq.get('coin')}: {str(e)[:100]}")

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
            debug.setdefault("skips", []).append(f"{coin}: not in candidates map")
            continue

        is_stock  = coin_data.get("is_stock", False)
        pair      = coin_data["pair"]
        price_dec = coin_data["price_dec"]
        min_v     = coin_data["min_vol"]

        # stop/target — Claude קובע לכל עסקה לפי תנודתיות; ברירת מחדל אם לא נתן. גבולות הגנה.
        if is_stock:
            # מניות — Claude קובע, אבל בטווח צר (מניות זזות פחות מקריפטו)
            try:
                stop_pct = float(pick.get("stop_pct", STOP_PCT_STOCK))
            except (TypeError, ValueError):
                stop_pct = STOP_PCT_STOCK
            try:
                target_pct = float(pick.get("target_pct", TARGET_PCT_STOCK))
            except (TypeError, ValueError):
                target_pct = TARGET_PCT_STOCK
            stop_pct   = max(0.01, min(0.03, stop_pct))    # stop 1%-3%
            target_pct = max(0.02, min(0.08, target_pct))   # target 2%-8%
        else:
            try:
                stop_pct = float(pick.get("stop_pct", STOP_PCT))
            except (TypeError, ValueError):
                stop_pct = STOP_PCT
            try:
                target_pct = float(pick.get("target_pct", TARGET_PCT))
            except (TypeError, ValueError):
                target_pct = TARGET_PCT
            stop_pct   = max(0.015, min(0.06, stop_pct))   # stop בין 1.5% ל-6%
            target_pct = max(0.04,  min(0.25, target_pct))  # target בין 4% ל-25%

        # גודל דינמי — Claude קובע size_pct (5-40% מהתיק); תקרה גדלה עם התיק
        if is_stock:
            # מניות — גודל לפי שכנוע כמו קריפטו, נושיונל מתחת לתקרה. מינוף נותן חשיפה גדולה ממרג'ין.
            pf = portfolio_usd or usdc or 0
            try:
                size_pct = float(pick.get("size_pct", 20))
            except (TypeError, ValueError):
                size_pct = 20
            size_pct  = max(10.0, min(50.0, size_pct))
            trade_usd = pf * size_pct / 100 if pf else SWING_USD_STOCK
            trade_usd = max(SWING_USD_STOCK, min(SWING_MAX_STOCK_USD, trade_usd))
            # תקרת נזילות — לא יותר מ-10% מהנפח היומי של המניה (מלכודת ביצוע בספר דליל)
            liq_cap   = max(SWING_USD_STOCK, coin_data.get("volume_usdc", 0) * 0.10)
            trade_usd = round(min(trade_usd, liq_cap), 2)
            logging.info(f"[Swing] {coin} (מניה) size_pct={size_pct:.0f}% → נושיונל ${trade_usd:.0f} | מינוף x{STOCK_LEVERAGE} | stop -{stop_pct*100:.1f}% target +{target_pct*100:.1f}%")
        else:
            pf = portfolio_usd or usdc or 0
            try:
                size_pct = float(pick.get("size_pct", SWING_PCT_DEFAULT * 100))
            except (TypeError, ValueError):
                size_pct = SWING_PCT_DEFAULT * 100
            size_pct  = max(10.0, min(50.0, size_pct))   # מנדט אגרסיבי — עד 50%
            # תקרה גדלה עם התיק (50% מהתיק), אבל לא פחות מתקרת הבסיס
            dynamic_max = max(SWING_MAX_USD, pf * 0.5) if pf else SWING_MAX_USD
            trade_usd = pf * size_pct / 100 if pf else SWING_USD
            trade_usd = max(SWING_MIN_USD, min(dynamic_max, trade_usd))
            trade_usd = round(trade_usd, 2)
            logging.info(f"[Swing] {coin} size_pct={size_pct:.0f}% → ${trade_usd:.0f} | stop -{stop_pct*100:.1f}% target +{target_pct*100:.1f}% (תיק ${pf:.0f})")

        # CANDIDATES lookup לקריפטו (לmargining)
        cfg = CANDIDATES.get(coin, {})

        price = coin_data["price"]
        vol   = round(trade_usd / price, 8)

        if is_stock and vol < 1:
            # חלק ממכשירי המניות דורשים חוזים שלמים (precision 0) — שבר חוזה נדחה כ-invalidSize.
            # אם המחיר סביר, קופצים לחוזה שלם אחד; אחרת אין דרך לסחור במניה הזו בגודל שנבחר.
            try:
                from kraken_futures import get_size_precision
                if get_size_precision(pair) == 0:
                    if price <= SWING_MAX_STOCK_USD and price <= trade_usd * 2.5:
                        logging.info(f"[Swing] {coin} דורש חוזים שלמים — מעגל לחוזה 1 (נושיונל ${price:.0f})")
                        vol, trade_usd = 1.0, round(price, 2)
                    else:
                        logging.warning(f"[Swing] {coin} חוזה שלם ${price:.0f} גדול מדי — מדלג")
                        debug.setdefault("order_errors", []).append(f"{coin}: whole-contract ${price:.0f} exceeds size limits")
                        continue
            except Exception:
                pass

        if vol < min_v:
            logging.warning(f"[Swing] {coin} vol={vol:.6f} < min={min_v} — skip")
            debug.setdefault("skips", []).append(f"{coin}: vol {vol:.4f} < min {min_v}")
            continue

        # בדוק risk_manager לפני ביצוע
        if not is_stock:
            from risk_manager import can_open_position, get_weakest_position, get_portfolio_exposure
            ok, reason = can_open_position(coin, trade_usd, margin_headroom, exposure, portfolio_usd or usdc)
            if not ok:
                debug.setdefault("skips", []).append(f"{coin}: risk_manager — {reason[:80]}")
                # אם הסיבה היא מרג'ין — בדוק אם כדאי לסגור פוזיציה חלשה
                if "מרג'ין" in reason:
                    weakest = get_weakest_position(open_swings)
                    if weakest and weakest.get("pnl_pct", 0) < 1.0:
                        logging.info(f"[RiskManager] Margin full — rotating: closing {weakest['coin']} to open {coin}")
                        # סגור את החלשה
                        for t in trades:
                            if t.get("coin") == weakest["coin"] and t.get("status") == "open":
                                cur = get_current_price(t["pair"])
                                if cur > 0:
                                    cfg_w = CANDIDATES.get(weakest["coin"], {})
                                    pd_w  = cfg_w.get("price_dec", 4)
                                    w_side = t.get("side", "long")
                                    w_close_type = "buy" if w_side == "short" else "sell"
                                    lp_w  = round(cur * (1.001 if w_side == "short" else 0.999), pd_w)
                                    try:
                                        if t.get("sell_txid"):
                                            try:
                                                request_fn("/0/private/CancelOrder", {"txid": t["sell_txid"]}, private=True)
                                            except Exception as ce:
                                                logging.info(f"[RiskManager] TP כבר בוצע/לא קיים ({weakest['coin']}): {ce}")
                                        sp = {"pair": t["pair"], "type": w_close_type, "ordertype": "limit",
                                              "volume": f"{t['volume']:.8f}", "price": f"{lp_w:.{pd_w}f}",
                                              "leverage": str(LEVERAGE)}
                                        res = request_fn("/0/private/AddOrder", sp, private=True)
                                        txid_w = list(res.get("txid", ["?"]))[0]
                                        pnl_pct_w       = _pnl_pct(w_side, t["entry_price"], cur)
                                        t["status"]     = "closed_profit" if pnl_pct_w >= 0 else "closed_loss"
                                        t["date_close"] = datetime.now().isoformat()
                                        t["close_price"]= cur
                                        t["close_txid"] = txid_w
                                        t["pnl_pct"]    = pnl_pct_w
                                        archive_closed_trade(t)
                                        open_swings = [s for s in open_swings if s["coin"] != weakest["coin"]]
                                        open_coins.discard(weakest["coin"])
                                        exposure = get_portfolio_exposure(open_swings, portfolio_usd or usdc)
                                        logging.info(f"[RiskManager] Closed {weakest['coin']} @ {cur:.4f} P&L={t['pnl_pct']:+.1f}%")
                                    except Exception as re:
                                        logging.error(f"[RiskManager] Rotation close failed: {re}")
                                        continue
                                break
                    else:
                        logging.info(f"[RiskManager] Margin full but no weak position to rotate — skip {coin}")
                        continue
                else:
                    logging.info(f"[RiskManager] Blocked {coin}: {reason}")
                    continue

        # כיוון העסקה לפי בחירת Claude
        direction = str(pick.get("direction", "long")).lower()
        if direction not in ("long", "short"):
            direction = "long"
        # שורט: בקריפטו רק margin-eligible; במניות (Perps) תמיד אפשרי
        if direction == "short" and not is_stock and coin not in MARGIN_ELIGIBLE:
            logging.info(f"[Swing] {coin} short לא נתמך (קריפטו לא margin-eligible) — מדלג")
            continue

        target_p, stop_p = _targets_for_side(direction, price, target_pct, stop_pct, price_dec)
        # מחיר כניסה אגרסיבי (marketable) — נכנס מיד ליד השוק:
        # לונג קונה מעט מעל (ליד ה-ask), שורט מוכר מעט מתחת (ליד ה-bid). אחרת הפקודה לא נכנסת.
        entry_lp = round(price * (0.998 if direction == "short" else 1.002), price_dec)
        try:
            if is_stock:
                # ── xStock — דרך Kraken Futures Perps (לונג ושורט, עם מינוף) ──
                from kraken_futures import (
                    place_futures_order, get_futures_balance,
                    transfer_spot_to_futures, MAX_TRANSFER_USD
                )
                # מינוף: צריך מרג'ין = נושיונל/מינוף, לא את כל הנושיונל.
                need_margin = trade_usd / STOCK_LEVERAGE
                fut_balance = get_futures_balance()
                if fut_balance < need_margin:
                    shortfall = need_margin - fut_balance
                    to_move   = min(shortfall + 2, MAX_TRANSFER_USD, max(0, usdc) - 10)
                    if to_move >= 10:
                        logging.info(f"[Futures] חסר מרג'ין ${shortfall:.0f} ל-{coin} — מעביר ${to_move:.0f} מ-Spot")
                        transferred = transfer_spot_to_futures(to_move)
                        debug.setdefault("transfers", []).append(f"{coin}: moved ${to_move:.0f} → {'OK' if transferred else 'FAILED'}")
                        if transferred:
                            import time as _t
                            _t.sleep(3)  # המתנה לזיכוי ההעברה
                            fut_balance = get_futures_balance()
                    if fut_balance < need_margin:
                        logging.warning(f"[Futures] אין מספיק מרג'ין ${fut_balance:.2f} < ${need_margin:.2f} ל-{coin} — מדלג")
                        debug.setdefault("skips", []).append(f"{coin}: margin ${fut_balance:.0f} < needed ${need_margin:.0f} (after transfer attempt)")
                        continue
                # לונג: כניסה=buy, TP=sell | שורט: כניסה=sell, TP=buy
                entry_side = "sell" if direction == "short" else "buy"
                tp_side    = "buy"  if direction == "short" else "sell"
                txid      = place_futures_order(pair, entry_side, vol, entry_lp)
                sell_txid = None
                try:
                    sell_txid = place_futures_order(pair, tp_side, vol, target_p)
                except Exception as se:
                    logging.warning(f"[Futures] TP order failed {coin}: {se}")
            else:
                # ── קריפטו — דרך Kraken Spot/Margin API ──────────────────
                # לונג: כניסה=buy, TP=sell | שורט: כניסה=sell, TP=buy
                entry_type = "sell" if direction == "short" else "buy"
                tp_type    = "buy"  if direction == "short" else "sell"
                # שורט מחייב מינוף; לונג מנסה עם מינוף ונופל ל-spot אם אין
                use_leverage = True if direction == "short" else (coin in MARGIN_ELIGIBLE)

                entry_params = {
                    "pair": pair, "type": entry_type, "ordertype": "limit",
                    "volume": f"{vol:.8f}", "price": f"{entry_lp:.{price_dec}f}",
                }
                if use_leverage:
                    entry_params["leverage"] = str(LEVERAGE)
                try:
                    res = request_fn("/0/private/AddOrder", entry_params, private=True)
                except Exception as margin_e:
                    if "margin" in str(margin_e).lower() and direction == "long" and use_leverage:
                        logging.warning(f"[Swing] Margin full for {coin}, retrying without leverage")
                        entry_params.pop("leverage", None)
                        use_leverage = False
                        res = request_fn("/0/private/AddOrder", entry_params, private=True)
                    else:
                        raise
                txid = list(res.get("txid", ["?"]))[0]

                sell_txid = None
                try:
                    tp_params = {
                        "pair": pair, "type": tp_type, "ordertype": "limit",
                        "volume": f"{vol:.8f}", "price": f"{target_p:.{price_dec}f}",
                    }
                    if use_leverage:
                        tp_params["leverage"] = str(LEVERAGE)
                    try:
                        sell_res = request_fn("/0/private/AddOrder", tp_params, private=True)
                    except Exception as se2:
                        if "margin" in str(se2).lower() and direction == "long":
                            tp_params.pop("leverage", None)
                            sell_res = request_fn("/0/private/AddOrder", tp_params, private=True)
                        else:
                            raise
                    sell_txid = list(sell_res.get("txid", ["?"]))[0]
                    logging.info(f"[Swing] TP ({tp_type}) placed {coin} @ {target_p} txid={sell_txid}")
                except Exception as se:
                    logging.warning(f"[Swing] tp order failed {coin}: {se}")

            trade = {
                "coin":          coin,
                "pair":          pair,
                "is_stock":      is_stock,
                "is_futures":    is_stock,
                "side":          direction,
                "entry_price":   price,
                "limit_price":   entry_lp,
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
                # תנאי כניסה — לניתוח דינמי של "באילו תנאים הצלחנו/נכשלנו" בכל מטבע
                "entry_rsi":       coin_data.get("rsi"),
                "entry_bb_pct":    coin_data.get("bb_pct"),
                "entry_macd_hist": coin_data.get("macd_hist"),
                "entry_change_24h": coin_data.get("change_24h"),
            }
            trades.append(trade)
            open_coins.add(coin)
            logging.info(f"[Swing] OPEN {coin} ({direction}) @ {price:.4f} target={target_p} stop={stop_p} | {reason[:80]}")
            dir_he = "שורט 📉" if direction == "short" else "לונג 📈"
            _send_trade_alert(
                f"🟢 נפתחה פוזיציה: {coin} ({dir_he})",
                f"מטבע: {coin}\nכיוון: {dir_he}\nכניסה: ${price:.4f}\nיעד: ${target_p:.4f}\nStop: ${stop_p:.4f}\nגודל: ${trade_usd:.0f}\nסיבה: {reason[:150]}"
            )
        except Exception as e:
            logging.error(f"[Swing] buy failed {coin}: {e}")
            debug.setdefault("order_errors", []).append(f"{coin}: {str(e)[:150]}")

    _write_debug(debug)
    save_swing_trades(trades)
    return trades
