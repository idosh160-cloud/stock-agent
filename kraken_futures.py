"""
kraken_futures.py — מסחר xStocks דרך Kraken Futures API
"""
import os
import hmac
import hashlib
import base64
import time
import logging
import requests
from urllib.parse import urlencode
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://futures.kraken.com/derivatives/api/v3"


def _load_futures_keys():
    """טוען מפתחות Futures מ-.env או משתני סביבה"""
    api_key = os.environ.get("KRAKEN_FUTURES_API_KEY", "")
    api_secret = os.environ.get("KRAKEN_FUTURES_API_SECRET", "")
    if api_key and api_secret:
        return api_key, api_secret
    try:
        env_path = os.path.join(DIR, ".env")
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "KRAKEN_FUTURES_API_KEY":
                    api_key = v
                elif k == "KRAKEN_FUTURES_API_SECRET":
                    api_secret = v
    except Exception:
        pass
    return api_key, api_secret


def _sign(endpoint: str, post_data: str, nonce: str, secret: str) -> str:
    message = post_data + nonce + endpoint
    h = hmac.new(
        base64.b64decode(secret),
        message.encode("utf-8"),
        hashlib.sha512
    )
    return base64.b64encode(h.digest()).decode()


def _request(endpoint: str, params: dict = None, method: str = "GET") -> dict:
    api_key, api_secret = _load_futures_keys()
    if not api_key:
        raise Exception("Futures API key not configured")

    nonce = str(int(time.time() * 1000))
    params = params or {}

    if method == "POST":
        post_data = urlencode(params)
        url = f"{BASE_URL}{endpoint}"
        sig = _sign(endpoint, post_data, nonce, api_secret)
        headers = {
            "APIKey": api_key,
            "Authent": sig,
            "Nonce": nonce,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        r = requests.post(url, data=post_data, headers=headers, timeout=15)
    else:
        post_data = ""
        url = f"{BASE_URL}{endpoint}"
        sig = _sign(endpoint, post_data, nonce, api_secret)
        headers = {
            "APIKey": api_key,
            "Authent": sig,
            "Nonce": nonce,
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)

    data = r.json()
    if data.get("result") != "success":
        raise Exception(f"Futures API error: {data}")
    return data


def get_futures_balance() -> float:
    """מחזיר יתרת USD זמינה ב-Futures wallet"""
    try:
        data = _request("/accounts")
        accounts = data.get("accounts", {})
        cash = accounts.get("cash", {})
        return float(cash.get("availableFunds", 0))
    except Exception as e:
        logging.error(f"[Futures] Balance failed: {e}")
        return 0.0


def get_futures_positions() -> list:
    """מחזיר פוזיציות פתוחות ב-Futures"""
    try:
        data = _request("/openpositions")
        return data.get("openPositions", [])
    except Exception as e:
        logging.error(f"[Futures] Positions failed: {e}")
        return []


def get_futures_price(symbol: str) -> float:
    """מחיר נוכחי של xStock"""
    try:
        r = requests.get(
            f"{BASE_URL}/tickers",
            timeout=10
        )
        tickers = r.json().get("tickers", [])
        for t in tickers:
            if t.get("symbol") == symbol:
                return float(t.get("last", 0) or 0)
    except Exception as e:
        logging.error(f"[Futures] Price failed {symbol}: {e}")
    return 0.0


def place_futures_order(symbol: str, side: str, size: float, limit_price: float) -> str:
    """
    מבצע פקודת קנייה/מכירה ב-Futures
    symbol: PF_TSLAXUSD
    side: buy / sell
    size: כמות חוזים
    limit_price: מחיר limit
    מחזיר order_id
    """
    try:
        params = {
            "symbol": symbol,
            "side": side,
            "orderType": "lmt",
            "size": str(size),
            "limitPrice": str(round(limit_price, 2)),
        }
        data = _request("/sendorder", params, method="POST")
        status = data.get("sendStatus", {})
        order_id = status.get("order_id", "?")
        logging.info(f"[Futures] {side.upper()} {symbol} x{size} @ {limit_price} → {order_id}")
        return order_id
    except Exception as e:
        logging.error(f"[Futures] Order failed {symbol}: {e}")
        raise


def cancel_futures_order(order_id: str) -> bool:
    """מבטל פקודה פתוחה"""
    try:
        _request("/cancelorder", {"order_id": order_id}, method="POST")
        logging.info(f"[Futures] Cancelled {order_id}")
        return True
    except Exception as e:
        logging.error(f"[Futures] Cancel failed {order_id}: {e}")
        return False


def test_connection() -> bool:
    """בדיקת חיבור ואימות"""
    try:
        bal = get_futures_balance()
        logging.info(f"[Futures] Connected. Balance: ${bal:.2f}")
        return True
    except Exception as e:
        logging.error(f"[Futures] Connection test failed: {e}")
        return False
