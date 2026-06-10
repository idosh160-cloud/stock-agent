import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
import json
import logging
from datetime import datetime, date

_env_vars = {}
try:
    with open(r"C:\Users\User\Documents\stock_agent\.env", "r", encoding="utf-8-sig") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                _env_vars[_k.strip()] = _v.strip()
except Exception:
    pass

API_KEY    = _env_vars.get("KRAKEN_API_KEY", "")
API_SECRET = _env_vars.get("KRAKEN_PRIVATE_KEY", "")
BASE_URL   = "https://api.kraken.com"

DIR          = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE  = os.path.join(DIR, "crypto_trades.json")
PARAMS_FILE  = os.path.join(DIR, "crypto_params.json")
CRYPTO_FILE  = os.path.join(DIR, "last_crypto.json")

DEFAULT_PARAMS = {
    "RSI_BUY":          38,
    "RSI_SELL":         62,
    "MAX_TRADE_USD":    30,
    "MAX_DAILY_TRADES": 4,
    "MIN_SIGNALS":      2,   # כמה אינדיקטורים חייבים להסכים לפני עסקה
}

PAIRS = {
    "BTC": "XXBTZUSD",
    "ETH": "XETHZUSD",
    "XRP": "XXRPZUSD",
}

MIN_VOLUMES = {"BTC": 0.0001, "ETH": 0.001, "XRP": 1.0}

# רמות תמיכה/התנגדות ידועות לכל מטבע (מתעדכנות אוטומטית)
SUPPORT_LEVELS = {
    "BTC": [55000, 58000, 60000, 62000, 65000],
    "ETH": [1400,  1500,  1600,  1700,  1800],
    "XRP": [0.85,  0.95,  1.05,  1.20,  1.40],
}


# ── File helpers ──────────────────────────────────────────────────────────────

def load_params() -> dict:
    if os.path.exists(PARAMS_FILE):
        try:
            with open(PARAMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PARAMS.copy()

def save_params(p: dict):
    with open(PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

def load_trades() -> list:
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_trade(trade: dict):
    trades = load_trades()
    trades.append(trade)
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)

def trades_today() -> int:
    today = date.today().isoformat()
    return sum(1 for t in load_trades() if t.get("date", "").startswith(today))


# ── Kraken API ────────────────────────────────────────────────────────────────

def _sign(urlpath: str, data: dict) -> dict:
    postdata = urllib.parse.urlencode(data)
    encoded  = (str(data["nonce"]) + postdata).encode()
    message  = urlpath.encode() + hashlib.sha256(encoded).digest()
    secret   = API_SECRET + "=" * (-len(API_SECRET) % 4)
    mac      = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return {"API-Key": API_KEY, "API-Sign": base64.b64encode(mac.digest()).decode()}

def _request(endpoint: str, data: dict = None, private: bool = False) -> dict:
    url = BASE_URL + endpoint
    if private:
        data = data or {}
        data["nonce"] = str(int(time.time() * 1000))
        headers = _sign(endpoint, data)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(data).encode()
        req  = urllib.request.Request(url, data=body, headers=headers)
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.loads(r.read().decode())
    if result.get("error"):
        raise RuntimeError(f"Kraken: {result['error']}")
    return result["result"]

def get_balance() -> dict:
    raw = _request("/0/private/Balance", private=True)
    name_map = {"ZUSD": "USD", "XXBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "USDC": "USDC", "ADA": "ADA"}
    return {name_map.get(k, k): round(float(v), 8) for k, v in raw.items() if float(v) > 0}

def get_ohlc(pair: str, interval: int = 60, count: int = 210) -> list:
    data = _request(f"/0/public/OHLC?pair={pair}&interval={interval}")
    key  = list(data.keys())[0]
    rows = data[key][-count:]
    return {
        "close":  [float(r[4]) for r in rows],
        "high":   [float(r[2]) for r in rows],
        "low":    [float(r[3]) for r in rows],
        "volume": [float(r[6]) for r in rows],
    }

def get_ticker(pair: str) -> dict:
    data = _request(f"/0/public/Ticker?pair={pair}")
    key  = list(data.keys())[0]
    t    = data[key]
    return {"bid": float(t["b"][0]), "ask": float(t["a"][0]), "last": float(t["c"][0])}

def place_order(pair: str, side: str, volume: float, price: float) -> dict:
    return _request("/0/private/AddOrder", {
        "pair": pair, "type": side, "ordertype": "limit",
        "volume": f"{volume:.8f}", "price": f"{price:.4f}",
    }, private=True)

def get_open_orders() -> dict:
    return _request("/0/private/OpenOrders", private=True).get("open", {})

def cancel_order(txid: str):
    return _request("/0/private/CancelOrder", {"txid": txid}, private=True)


# ── Indicators ────────────────────────────────────────────────────────────────

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        (gains if d > 0 else losses).append(abs(d))
    avg_g = sum(gains) / period if gains else 0
    avg_l = sum(losses) / period if losses else 1e-9
    return round(100 - 100 / (1 + avg_g / avg_l), 2)

def calc_ma(closes: list, period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    return round(sum(closes[-period:]) / period, 6)

def calc_ema(closes: list, period: int) -> list:
    if len(closes) < period:
        return [closes[-1]] * len(closes)
    k = 2 / (period + 1)
    ema = [sum(closes[:period]) / period]
    for p in closes[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema

def calc_macd(closes: list) -> dict:
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[-min_len + i] - ema26[-min_len + i] for i in range(min_len)]
    signal    = calc_ema(macd_line, 9)
    histogram = macd_line[-1] - signal[-1]
    return {
        "macd":      round(macd_line[-1], 6),
        "signal":    round(signal[-1], 6),
        "histogram": round(histogram, 6),
        "bullish":   histogram > 0 and macd_line[-1] > signal[-1],
        "bearish":   histogram < 0 and macd_line[-1] < signal[-1],
    }

def find_support_resistance(highs: list, lows: list, price: float) -> dict:
    """
    מזהה רמות תמיכה והתנגדות מה-OHLC האחרון (50 נרות).
    מחזיר את הרמה הקרובה ביותר מעל ומתחת למחיר.
    """
    levels = []
    window = 5
    for i in range(window, len(highs) - window):
        # שיא מקומי = התנגדות
        if highs[i] == max(highs[i-window:i+window+1]):
            levels.append(highs[i])
        # שפל מקומי = תמיכה
        if lows[i] == min(lows[i-window:i+window+1]):
            levels.append(lows[i])

    levels = sorted(set(round(l, 4) for l in levels))

    support    = max((l for l in levels if l < price * 0.999), default=None)
    resistance = min((l for l in levels if l > price * 1.001), default=None)

    near_support    = support    and abs(price - support)    / price < 0.015  # תוך 1.5%
    near_resistance = resistance and abs(resistance - price) / price < 0.015

    return {
        "support":        support,
        "resistance":     resistance,
        "near_support":   near_support,
        "near_resistance": near_resistance,
        "all_levels":     levels[-10:],
    }

def score_signals(rsi: float, macd: dict, sr: dict, price: float,
                  ma50: float, ma200: float, params: dict) -> dict:
    """
    מחזיר ציון קנייה/מכירה לפי כמה אינדיקטורים מסכימים.
    כל אינדיקטור = נקודה. צריך MIN_SIGNALS נקודות לפעולה.
    """
    buy_score  = 0
    sell_score = 0
    reasons    = []

    # RSI
    if rsi < params["RSI_BUY"]:
        buy_score += 2
        reasons.append(f"RSI {rsi} (oversold)")
    elif rsi > params["RSI_SELL"]:
        sell_score += 2
        reasons.append(f"RSI {rsi} (overbought)")

    # MACD
    if macd["bullish"]:
        buy_score += 1
        reasons.append("MACD bullish crossover")
    elif macd["bearish"]:
        sell_score += 1
        reasons.append("MACD bearish crossover")

    # MA50 — מחיר מתחת/מעל הממוצע
    if ma50 > 0:
        if price < ma50 * 0.98:
            buy_score += 1
            reasons.append(f"Below MA50 (${ma50:,.2f})")
        elif price > ma50 * 1.02:
            sell_score += 1
            reasons.append(f"Above MA50 (${ma50:,.2f})")

    # MA200 — מגמה ארוכת טווח
    if ma200 > 0:
        if price > ma200:
            buy_score += 1
            reasons.append("Above MA200 (uptrend)")
        else:
            sell_score += 1
            reasons.append("Below MA200 (downtrend)")

    # Support/Resistance
    if sr["near_support"]:
        buy_score += 2
        reasons.append(f"Near support ${sr['support']:,.4f}")
    if sr["near_resistance"]:
        sell_score += 2
        reasons.append(f"Near resistance ${sr['resistance']:,.4f}")

    action = "HOLD"
    if buy_score >= params["MIN_SIGNALS"] and buy_score > sell_score:
        action = "BUY"
    elif sell_score >= params["MIN_SIGNALS"] and sell_score > buy_score:
        action = "SELL"

    return {
        "action":     action,
        "buy_score":  buy_score,
        "sell_score": sell_score,
        "reasons":    reasons,
    }


# ── Self-learning ─────────────────────────────────────────────────────────────

def tune_params():
    trades = load_trades()
    if len(trades) < 10:
        return
    params   = load_params()
    wins     = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
    win_rate = len(wins) / len(trades)

    buy_rsis  = [t["rsi"] for t in wins if t["action"] == "BUY"]
    sell_rsis = [t["rsi"] for t in wins if t["action"] == "SELL"]

    if buy_rsis:
        params["RSI_BUY"]  = round(min(42, max(28, sum(buy_rsis)  / len(buy_rsis))), 1)
    if sell_rsis:
        params["RSI_SELL"] = round(max(58, min(75, sum(sell_rsis) / len(sell_rsis))), 1)

    if win_rate > 0.6:
        params["MAX_TRADE_USD"] = min(60, params["MAX_TRADE_USD"] + 5)
    elif win_rate < 0.4:
        params["MAX_TRADE_USD"] = max(15, params["MAX_TRADE_USD"] - 5)

    save_params(params)
    logging.info(f"[Crypto] Tuned params win_rate={win_rate:.0%} → {params}")


# ── Order management ─────────────────────────────────────────────────────────

def get_open_coins() -> set:
    """מחזיר סט של מטבעות שכבר יש עליהם פקודה פתוחה."""
    try:
        orders = get_open_orders()
        coins = set()
        for o in orders.values():
            pair = o.get("descr", {}).get("pair", "")
            for coin, kpair in PAIRS.items():
                if coin in pair or kpair[:4] in pair:
                    coins.add(coin)
        return coins
    except Exception:
        return set()

def cancel_bot_orders():
    """מבטל את כל פקודות ה-limit של הבוט."""
    try:
        for txid, o in get_open_orders().items():
            cancel_order(txid)
            logging.info(f"[Crypto] Cancelled {txid}")
    except Exception as e:
        logging.warning(f"[Crypto] Cancel failed: {e}")

def refresh_limit_orders(balance: dict):
    """
    שם פקודות limit ממתינות ברמות תמיכה — רק למטבעות שאין עליהם פקודה פתוחה.
    מחשב כמה USDC פנוי לאחר הפרשת כסף לפקודות קיימות.
    """
    params      = load_params()
    open_orders = {}
    try:
        open_orders = get_open_orders()
    except Exception as e:
        logging.warning(f"[Crypto] Cannot fetch open orders: {e}")
        return

    # חשב כמה USDC כבר "שמור" בפקודות פתוחות
    reserved_usdc = 0.0
    open_coins    = set()
    for o in open_orders.values():
        descr   = o.get("descr", {})
        side    = descr.get("type", "")
        pair    = descr.get("pair", "")
        vol     = float(o.get("vol", 0))
        price   = float(descr.get("price", 0))
        if side == "buy" and price > 0:
            reserved_usdc += vol * price
        for coin, kpair in PAIRS.items():
            if coin in pair or kpair[:4] in pair:
                open_coins.add(coin)

    usdc_free = (balance.get("USDC", 0) + balance.get("USD", 0)) - reserved_usdc

    if usdc_free < 15:
        logging.info(f"[Crypto] Skipping limit orders — free USDC={usdc_free:.2f}")
        return

    for coin, pair in PAIRS.items():
        if coin in open_coins:
            logging.info(f"[Crypto] Skipping {coin} — already has open order")
            continue
        try:
            ohlc    = get_ohlc(pair, interval=240, count=100)
            price   = get_ticker(pair)["last"]
            sr      = find_support_resistance(ohlc["high"], ohlc["low"], price)
            support = sr.get("support")

            # שים limit רק אם הרמה לפחות 2% מתחת למחיר הנוכחי
            if support and support < price * 0.98:
                spend = min(params["MAX_TRADE_USD"], usdc_free * 0.3)
                vol   = round(spend / support, 6)
                if vol >= MIN_VOLUMES.get(coin, 0.0001):
                    lp = round(support * 1.002, 4)
                    place_order(pair, "buy", vol, lp)
                    reserved_usdc += vol * lp
                    usdc_free     -= vol * lp
                    logging.info(f"[Crypto] Pre-placed BUY {coin} @ {lp} (support={support})")
        except Exception as e:
            logging.warning(f"[Crypto] Pre-place failed {coin}: {e}")


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_cycle(auto_trade: bool = True) -> dict:
    params     = load_params()
    balance    = get_balance()
    usdc       = balance.get("USDC", 0) + balance.get("USD", 0)
    daily      = trades_today()
    signals    = []
    orders     = []
    prices     = {}
    open_coins = get_open_coins()  # מטבעות שכבר יש עליהם פקודה פתוחה

    for coin, pair in PAIRS.items():
        try:
            ohlc    = get_ohlc(pair, interval=60, count=210)
            closes  = ohlc["close"]
            highs   = ohlc["high"]
            lows    = ohlc["low"]
            ticker  = get_ticker(pair)
            price   = ticker["last"]
            holding = balance.get(coin, 0)
            prices[coin] = price

            rsi   = calc_rsi(closes)
            macd  = calc_macd(closes)
            ma50  = calc_ma(closes, 50)
            ma200 = calc_ma(closes, 200)
            sr    = find_support_resistance(highs, lows, price)

            scored = score_signals(rsi, macd, sr, price, ma50, ma200, params)
            action = scored["action"]
            vol    = 0
            lp     = 0

            # אם יש פקודה פתוחה על המטבע — לא מוסיפים עוד
            if coin in open_coins:
                action = "HOLD (pending order)"
                vol, lp = 0, 0
            elif action == "BUY" and usdc >= 10 and daily < params["MAX_DAILY_TRADES"]:
                spend = min(params["MAX_TRADE_USD"], usdc * 0.9)
                vol   = round(spend / price, 6)
                if vol < MIN_VOLUMES.get(coin, 0.0001):
                    action = "HOLD"
                else:
                    lp = round(price * 0.998, 4)
            elif action == "SELL" and holding >= MIN_VOLUMES.get(coin, 0.0001) and daily < params["MAX_DAILY_TRADES"]:
                vol = round(holding * 0.5, 6)
                lp  = round(price * 1.002, 4)
            else:
                action = "HOLD"

            sig = {
                "coin":        coin,
                "pair":        pair,
                "action":      action,
                "rsi":         rsi,
                "macd":        macd["histogram"],
                "ma50":        round(ma50, 2),
                "ma200":       round(ma200, 2),
                "support":     sr["support"],
                "resistance":  sr["resistance"],
                "near_support": sr["near_support"],
                "buy_score":   scored["buy_score"],
                "sell_score":  scored["sell_score"],
                "reasons":     scored["reasons"],
                "price":       price,
                "volume":      vol,
                "usd_value":   round(vol * price, 2),
                "limit_price": lp,
            }
            signals.append(sig)

            if auto_trade and action in ("BUY", "SELL") and vol > 0:
                try:
                    result = place_order(pair, action.lower(), vol, lp)
                    txid   = list(result.get("txid", ["?"]))[0]
                    trade  = {
                        "date":    datetime.now().isoformat(),
                        "coin":    coin,
                        "action":  action,
                        "price":   price,
                        "volume":  vol,
                        "usd":     round(vol * price, 2),
                        "rsi":     rsi,
                        "buy_score":  scored["buy_score"],
                        "sell_score": scored["sell_score"],
                        "reasons": scored["reasons"],
                        "txid":    txid,
                        "pnl_pct": None,
                    }
                    save_trade(trade)
                    orders.append(trade)
                    daily += 1
                    logging.info(f"[Crypto] {action} {vol} {coin} @ {lp} score={scored['buy_score']} txid={txid}")
                except Exception as e:
                    logging.error(f"[Crypto] Order failed {coin}: {e}")

        except Exception as e:
            logging.error(f"[Crypto] Error {coin}: {e}")

    portfolio_usd = usdc
    for coin, amt in balance.items():
        if coin in prices:
            portfolio_usd += amt * prices[coin]

    # פקודות limit פתוחות לתצוגה בדשבורד
    open_orders_display = []
    try:
        for txid, o in get_open_orders().items():
            descr = o.get("descr", {})
            open_orders_display.append({
                "txid":   txid,
                "coin":   descr.get("pair", ""),
                "side":   descr.get("type", ""),
                "price":  float(descr.get("price", 0)),
                "volume": float(o.get("vol", 0)),
                "usd":    round(float(o.get("vol", 0)) * float(descr.get("price", 0) or 0), 2),
            })
    except Exception:
        pass

    state = {
        "timestamp":     datetime.now().isoformat(),
        "balance":       balance,
        "portfolio_usd": round(portfolio_usd, 2),
        "usdc":          round(usdc, 2),
        "signals":       signals,
        "orders_today":  daily,
        "params":        params,
        "open_orders":   open_orders_display,
        "recent_trades": load_trades()[-20:],
    }

    with open(CRYPTO_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    return state


if __name__ == "__main__":
    state = run_cycle(auto_trade=False)
    print(f"Portfolio: ${state['portfolio_usd']}")
    for s in state["signals"]:
        icon = "BUY" if s["action"] == "BUY" else "SELL" if s["action"] == "SELL" else "hold"
        print(f"[{icon}] {s['coin']} | RSI={s['rsi']} MA50=${s['ma50']:,.2f} | "
              f"buy={s['buy_score']} sell={s['sell_score']} | {', '.join(s['reasons'][:2])}")
