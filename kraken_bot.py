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

def _load_env():
    """טוען מפתחות מ-.env אם קיים, אחרת משתמש במשתני סביבה"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k and v and not os.environ.get(k):
                        os.environ[k] = v
    except Exception:
        pass

_load_env()
API_KEY    = os.environ.get("KRAKEN_API_KEY", "")
API_SECRET = os.environ.get("KRAKEN_PRIVATE_KEY", "")
BASE_URL   = "https://api.kraken.com"

DIR          = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE  = os.path.join(DIR, "crypto_trades.json")
PARAMS_FILE  = os.path.join(DIR, "crypto_params.json")
CRYPTO_FILE  = os.path.join(DIR, "last_crypto.json")

DEFAULT_PARAMS = {
    "RSI_BUY":          45,
    "RSI_SELL":         58,
    "MAX_TRADE_USD":    75,
    "MAX_DAILY_TRADES": 4,
    "MIN_SIGNALS":      2,
}

STOP_LOSS_PCT = 0.03  # -3% stop-loss על כל קנייה

PAIRS = {
    "BTC": "XBTUSDC",
    "ETH": "ETHUSDC",
    "XRP": "XRPUSDC",
}

MIN_VOLUMES = {"BTC": 0.0001, "ETH": 0.001, "XRP": 1.0}

# רמות תמיכה/התנגדות ידועות לכל מטבע (מתעדכנות אוטומטית)
SUPPORT_LEVELS = {
    "BTC": [88000, 90000, 92000, 95000, 98000],
    "ETH": [2200,  2400,  2600,  2800,  3000],
    "XRP": [2.00,  2.10,  2.20,  2.35,  2.50],
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
    # אם זו מכירה — חפש קנייה פתוחה ורשום P&L
    if trade.get("action") == "SELL":
        coin = trade["coin"]
        for t in reversed(trades):
            if t.get("coin") == coin and t.get("action") == "BUY" and t.get("pnl_pct") is None:
                buy_price = t.get("price", 0)
                sell_price = trade.get("price", 0)
                if buy_price > 0:
                    pnl_pct = round((sell_price - buy_price) / buy_price * 100, 2)
                    pnl_usd = round((sell_price - buy_price) * t.get("volume", 0), 2)
                    t["pnl_pct"] = pnl_pct
                    t["pnl_usd"] = pnl_usd
                    t["close_price"] = sell_price
                    trade["pnl_pct"] = pnl_pct
                    trade["pnl_usd"] = pnl_usd
                    logging.info(f"[Crypto] P&L {coin}: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
                break
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
    import re
    result = {}
    for k, v in raw.items():
        if float(v) <= 0:
            continue
        # נרמל staking variants: ETH2.S → ETH, SOL03.S → SOL וכו'
        normalized = re.sub(r'\d*\.S$', '', k)
        normalized = name_map.get(normalized, normalized)
        if normalized in result:
            result[normalized] = round(result[normalized] + float(v), 8)
        else:
            result[normalized] = round(float(v), 8)
    return result

# מיפוי pair קרקן → שם מטבע (כולל פורמטים ישנים)
_PAIR_TO_COIN = {
    "XETHZUSD": "ETH", "ETHUSDC": "ETH", "XETHUSDC": "ETH",
    "XXBTZUSD": "BTC", "XBTUSDC": "BTC",  "XXBTZUSD": "BTC",
    "XXRPZUSD": "XRP", "XRPUSDC": "XRP",
    "SOLUSDC": "SOL", "ADAUSDC": "ADA", "AVAXUSDC": "AVAX",
    "LINKUSDC": "LINK", "DOTUSDC": "DOT", "LTCUSDC": "LTC",
    "BCHUSDC": "BCH", "ALGOUSDC": "ALGO", "ATOMUSDC": "ATOM",
    "XTZUSDC": "XTZ", "XADAZUSD": "ADA",
}

def _pair_to_coin(pair: str) -> str:
    if pair in _PAIR_TO_COIN:
        return _PAIR_TO_COIN[pair]
    for suffix in ("USDC", "ZUSD", "USD", "EUR"):
        if pair.endswith(suffix):
            base = pair[:-len(suffix)].lstrip("X")
            return {"XBT": "BTC", "ETH": "ETH", "XRP": "XRP"}.get(base, base)
    return pair

def get_avg_costs() -> dict:
    """מחשב avg cost אמיתי מהיסטוריית עסקאות קרקן (כולל עסקאות לפני הבוט)"""
    try:
        data   = _request("/0/private/TradesHistory", {"trades": True}, private=True)
        trades = data.get("trades", {})
    except Exception as e:
        logging.warning(f"[Kraken] TradesHistory failed: {e}")
        return {}

    holdings: dict = {}
    for t in sorted(trades.values(), key=lambda x: float(x.get("time", 0))):
        coin  = _pair_to_coin(t.get("pair", ""))
        side  = t.get("type", "")
        vol   = float(t.get("vol", 0))
        price = float(t.get("price", 0))
        if not coin or vol == 0:
            continue
        h = holdings.setdefault(coin, {"vol": 0.0, "cost": 0.0})
        if side == "buy":
            h["vol"]  += vol
            h["cost"] += vol * price
        elif side == "sell" and h["vol"] > 0:
            ratio     = min(vol / h["vol"], 1.0)
            h["cost"] -= h["cost"] * ratio
            h["vol"]  -= vol
            h["vol"]   = max(0.0, h["vol"])

    result = {
        coin: round(h["cost"] / h["vol"], 6)
        for coin, h in holdings.items()
        if h["vol"] > 0.0001 and h["cost"] > 0
    }
    # מיזוג עם עלויות ידניות (לפוזיציות שנרכשו מחוץ לבוט)
    manual_path = os.path.join(DIR, "crypto_manual_costs.json")
    if os.path.exists(manual_path):
        try:
            with open(manual_path, encoding="utf-8") as f:
                manual = json.load(f)
            for coin, data in manual.items():
                if coin.startswith("_"):
                    continue
                avg = float(data.get("avg_cost", 0))
                if avg > 0 and coin not in result:
                    result[coin] = avg
        except Exception:
            pass
    return result

def get_live_prices_public(coins: list) -> dict:
    """מחירים חיים מ-Kraken public API לכל מטבע"""
    import requests as _req
    coin_pairs = {
        "BTC": "XBTUSDC", "ETH": "ETHUSDC", "XRP": "XRPUSDC",
        "SOL": "SOLUSDC", "ADA": "ADAUSDC", "AVAX": "AVAXUSDC",
        "LINK": "LINKUSDC", "DOT": "DOTUSDC", "LTC": "LTCUSDC",
        "BCH": "BCHUSDC", "ALGO": "ALGOUSDC", "ATOM": "ATOMUSDC",
        "XTZ": "XTZUSDC", "DOGE": "XDGUSDC", "XMR": "XMRUSDC",
        "BNB": "BNBUSDC", "TON": "TONUSDC", "SHIB": "SHIBUSDC",
        "MANA": "MANAUSDC", "VET": "VETUSDC",
    }
    needed = {c: coin_pairs[c] for c in coins if c in coin_pairs}
    if not needed:
        return {}
    try:
        pair_str = ",".join(needed.values())
        r   = _req.get(f"https://api.kraken.com/0/public/Ticker?pair={pair_str}", timeout=8)
        res = r.json().get("result", {})
        out = {}
        for coin, kpair in needed.items():
            t = res.get(kpair, {})
            if t:
                price  = float(t["c"][0])
                open_p = float(t["o"])
                out[coin] = {
                    "price":      price,
                    "change_pct": round((price - open_p) / open_p * 100, 2) if open_p else 0,
                    "high_24h":   float(t["h"][1]),
                    "low_24h":    float(t["l"][1]),
                }
        return out
    except Exception as e:
        logging.warning(f"[Kraken] public prices failed: {e}")
        return {}

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
                    # קרקן: BTC=1 ספרה, ETH=2, XRP=4
                    decimals = {"BTC": 1, "ETH": 2, "XRP": 4}.get(coin, 2)
                    lp = round(support * 1.002, decimals)
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

            decimals = {"BTC": 1, "ETH": 2, "XRP": 4}.get(coin, 2)

            # stop-loss — בדוק אם יש קנייה פתוחה שירדה מעל 3%
            if holding >= MIN_VOLUMES.get(coin, 0.0001):
                open_buy = next(
                    (t for t in reversed(load_trades())
                     if t.get("coin") == coin and t.get("action") == "BUY" and t.get("pnl_pct") is None),
                    None
                )
                if open_buy and open_buy.get("price", 0) > 0:
                    drop = (price - open_buy["price"]) / open_buy["price"]
                    if drop <= -STOP_LOSS_PCT:
                        sl_vol = round(holding * 0.99, 6)
                        sl_lp  = round(price * 0.999, decimals)
                        if sl_vol >= MIN_VOLUMES.get(coin, 0.0001):
                            try:
                                res   = place_order(pair, "sell", sl_vol, sl_lp)
                                txid  = list(res.get("txid", ["?"]))[0]
                                logging.warning(f"[StopLoss] {coin} drop={drop:.1%} → SELL @ {sl_lp} txid={txid}")
                                save_trade({
                                    "date": datetime.now().isoformat(), "coin": coin,
                                    "action": "SELL", "price": price, "volume": sl_vol,
                                    "usd": round(sl_vol * price, 2), "rsi": rsi,
                                    "buy_score": 0, "sell_score": 0,
                                    "reasons": [f"Stop-loss triggered ({drop:.1%})"],
                                    "txid": txid, "pnl_pct": None,
                                })
                                daily += 1
                            except Exception as e:
                                logging.error(f"[StopLoss] failed {coin}: {e}")
                        action = "STOP-LOSS"
                        vol, lp = 0, 0
                        signals.append({**{k: 0 for k in ["volume","usd_value","limit_price","buy_score","sell_score","support","resistance","ma50","ma200","macd"]},
                                        "coin": coin, "pair": pair, "action": action, "rsi": rsi,
                                        "near_support": False, "near_resistance": False, "reasons": [f"Stop-loss {drop:.1%}"], "price": price})
                        continue

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
                    lp = round(price * 0.998, decimals)
            elif action == "SELL" and holding >= MIN_VOLUMES.get(coin, 0.0001) and daily < params["MAX_DAILY_TRADES"]:
                vol = round(holding * 0.5, 6)
                lp  = round(price * 1.002, decimals)
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
    pair_to_coin = {v: k for k, v in PAIRS.items()}
    try:
        for txid, o in get_open_orders().items():
            descr    = o.get("descr", {})
            raw_pair = descr.get("pair", "")
            coin_name = pair_to_coin.get(raw_pair, raw_pair.replace("USDC","").replace("XBT","BTC"))
            open_orders_display.append({
                "txid":   txid,
                "coin":   coin_name,
                "side":   descr.get("type", ""),
                "price":  float(descr.get("price", 0)),
                "volume": float(o.get("vol", 0)),
                "usd":    round(float(o.get("vol", 0)) * float(descr.get("price", 0) or 0), 2),
            })
    except Exception:
        pass

    # ── מחירים חיים + avg costs לכל מטבע בבאלנס ─────────────────────────
    non_stable = [c for c in balance if c not in ("USDC", "USD")]
    live_px    = get_live_prices_public(non_stable)
    avg_costs  = get_avg_costs()

    # עדכן portfolio_usd עם מחירים חיים — fallback למחיר מה-OHLC, לא 0
    portfolio_usd = usdc
    for coin, amt in balance.items():
        p = live_px.get(coin, {}).get("price") or prices.get(coin)
        if not p:
            continue  # מחיר לא ידוע — לא מוסיפים 0 לתיק
        portfolio_usd += amt * p

    # בנה positions מלא
    positions_out = []
    for coin in non_stable:
        qty    = balance.get(coin, 0)
        px_data = live_px.get(coin, {})
        price_now = px_data.get("price", prices.get(coin, 0))
        avg   = avg_costs.get(coin)
        val   = round(qty * price_now, 2)
        pnl_usd = round((price_now - avg) * qty, 2) if avg else None
        pnl_pct = round((price_now - avg) / avg * 100, 2) if avg else None
        positions_out.append({
            "coin":       coin,
            "qty":        qty,
            "price":      price_now,
            "value_usd":  val,
            "avg_cost":   avg,
            "pnl_usd":    pnl_usd,
            "pnl_pct":    pnl_pct,
            "change_24h": px_data.get("change_pct", 0),
            "high_24h":   px_data.get("high_24h", 0),
            "low_24h":    px_data.get("low_24h", 0),
        })
    positions_out.sort(key=lambda x: x["value_usd"], reverse=True)

    state = {
        "timestamp":     datetime.now().isoformat(),
        "balance":       balance,
        "positions":     positions_out,
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
