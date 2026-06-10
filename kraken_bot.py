import os
import sys
import io
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

DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE  = os.path.join(DIR, "crypto_trades.json")
PARAMS_FILE  = os.path.join(DIR, "crypto_params.json")
CRYPTO_FILE  = os.path.join(DIR, "last_crypto.json")

# ── Default params (auto-tuned weekly) ───────────────────────────────────────
DEFAULT_PARAMS = {
    "RSI_BUY":       32,
    "RSI_SELL":      68,
    "MAX_TRADE_USD": 30,
    "MAX_DAILY_TRADES": 4,
}

PAIRS = {
    "BTC": "XXBTZUSD",
    "ETH": "XETHZUSD",
    "XRP": "XXRPZUSD",
}

MIN_VOLUMES = {"BTC": 0.0001, "ETH": 0.001, "XRP": 1.0}


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def get_ohlc(pair: str, interval: int = 60, count: int = 25) -> list:
    data = _request(f"/0/public/OHLC?pair={pair}&interval={interval}")
    key  = list(data.keys())[0]
    return [float(r[4]) for r in data[key][-count:]]


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


# ── RSI ───────────────────────────────────────────────────────────────────────

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


# ── Self-learning: tune params weekly ─────────────────────────────────────────

def tune_params():
    trades = load_trades()
    if len(trades) < 10:
        return
    params = load_params()

    wins   = [t for t in trades if t.get("pnl_pct", 0) > 0]
    losses = [t for t in trades if t.get("pnl_pct", 0) < 0]
    win_rate = len(wins) / len(trades) if trades else 0.5

    buy_rsis  = [t["rsi"] for t in wins if t["action"] == "BUY"]
    sell_rsis = [t["rsi"] for t in wins if t["action"] == "SELL"]

    if buy_rsis:
        best_buy = sum(buy_rsis) / len(buy_rsis)
        params["RSI_BUY"] = round(min(40, max(25, best_buy)), 1)
    if sell_rsis:
        best_sell = sum(sell_rsis) / len(sell_rsis)
        params["RSI_SELL"] = round(max(60, min(75, best_sell)), 1)

    if win_rate > 0.6:
        params["MAX_TRADE_USD"] = min(50, params["MAX_TRADE_USD"] + 5)
    elif win_rate < 0.4:
        params["MAX_TRADE_USD"] = max(15, params["MAX_TRADE_USD"] - 5)

    save_params(params)
    logging.info(f"[Crypto] Params tuned: win_rate={win_rate:.0%} → {params}")


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_cycle(auto_trade: bool = True) -> dict:
    params  = load_params()
    balance = get_balance()
    usdc    = balance.get("USDC", 0) + balance.get("USD", 0)
    daily   = trades_today()
    signals = []
    orders  = []

    prices = {}
    for coin, pair in PAIRS.items():
        try:
            closes  = get_ohlc(pair)
            rsi     = calc_rsi(closes)
            ticker  = get_ticker(pair)
            price   = ticker["last"]
            holding = balance.get(coin, 0)
            prices[coin] = price

            action = "HOLD"
            vol    = 0
            lp     = 0

            if (rsi < params["RSI_BUY"]
                    and usdc >= 10
                    and daily < params["MAX_DAILY_TRADES"]):
                spend = min(params["MAX_TRADE_USD"], usdc * 0.9)
                vol   = round(spend / price, 6)
                if vol >= MIN_VOLUMES.get(coin, 0.0001):
                    action = "BUY"
                    lp     = round(price * 0.998, 4)

            elif (rsi > params["RSI_SELL"]
                    and holding >= MIN_VOLUMES.get(coin, 0.0001)
                    and daily < params["MAX_DAILY_TRADES"]):
                vol    = round(holding * 0.5, 6)
                action = "SELL"
                lp     = round(price * 1.002, 4)

            sig = {
                "coin": coin, "pair": pair, "action": action,
                "rsi": rsi, "price": price,
                "volume": vol, "usd_value": round(vol * price, 2),
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
                        "txid":    txid,
                        "pnl_pct": None,
                    }
                    save_trade(trade)
                    orders.append(trade)
                    daily += 1
                    logging.info(f"[Crypto] {action} {vol} {coin} @ {lp} txid={txid}")
                except Exception as e:
                    logging.error(f"[Crypto] Order failed {coin}: {e}")

        except Exception as e:
            logging.error(f"[Crypto] Error {coin}: {e}")

    # portfolio value
    portfolio_usd = usdc
    for coin, amt in balance.items():
        if coin in prices:
            portfolio_usd += amt * prices[coin]

    state = {
        "timestamp":     datetime.now().isoformat(),
        "balance":       balance,
        "portfolio_usd": round(portfolio_usd, 2),
        "usdc":          round(usdc, 2),
        "signals":       signals,
        "orders_today":  daily,
        "params":        params,
        "recent_trades": load_trades()[-20:],
    }

    with open(CRYPTO_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    return state


if __name__ == "__main__":
    state = run_cycle(auto_trade=False)
    print(f"Portfolio: ${state['portfolio_usd']}")
    for s in state["signals"]:
        icon = "🟢" if s["action"] == "BUY" else "🔴" if s["action"] == "SELL" else "⚪"
        print(f"{icon} {s['coin']} RSI={s['rsi']} ${s['price']:,.2f} → {s['action']}")
