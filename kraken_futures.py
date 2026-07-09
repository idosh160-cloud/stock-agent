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


def _sign(endpoint_path: str, post_data: str, nonce: str, secret: str) -> str:
    # Kraken Futures: Authent = base64(HMAC-SHA512(base64decode(secret),
    #                 SHA256(postData + nonce + endpointPath)))
    # endpointPath חייב לכלול /api/v3 אבל לא /derivatives.
    sha = hashlib.sha256((post_data + nonce + endpoint_path).encode("utf-8")).digest()
    h = hmac.new(
        base64.b64decode(secret),
        sha,
        hashlib.sha512
    )
    return base64.b64encode(h.digest()).decode()


def _request(endpoint: str, params: dict = None, method: str = "GET") -> dict:
    api_key, api_secret = _load_futures_keys()
    if not api_key:
        raise Exception("Futures API key not configured")

    nonce = str(int(time.time() * 1000))
    params = params or {}
    # נתיב החתימה: /api/v3 + endpoint (ללא /derivatives שב-BASE_URL)
    sign_path = f"/api/v3{endpoint}"

    if method == "POST":
        post_data = urlencode(params)
        url = f"{BASE_URL}{endpoint}"
        sig = _sign(sign_path, post_data, nonce, api_secret)
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
        sig = _sign(sign_path, post_data, nonce, api_secret)
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
    """מחזיר margin זמין ב-Futures wallet.
    Kraken Pro Perps משתמש בחשבון flex (multiCollateralMarginAccount):
    הכסף יושב ב-flex.availableMargin (כל הקולטרל בשווי USD).
    fallback לחשבון cash הישן אם flex ריק."""
    try:
        data = _request("/accounts")
        accounts = data.get("accounts", {})

        # חשבון flex החדש — Kraken Pro Perps / multi-collateral
        flex = accounts.get("flex", {})
        if flex:
            avail = flex.get("availableMargin")
            if avail is not None:
                return float(avail)

        # fallback — חשבון cash הישן (legacy single-collateral)
        cash = accounts.get("cash", {})
        return float(cash.get("availableFunds", 0))
    except Exception as e:
        logging.error(f"[Futures] Balance failed: {e}")
        return 0.0


# ── העברות כספים בין ארנקים (עם תקרה קשיחה — הגנה מפני באג שמרוקן ארנק) ──
MAX_TRANSFER_USD = 200.0  # תקרה להעברה בודדת — מספיק למרג'ין של פוזיציית מניה מלאה ($450/x3)
MIN_TRANSFER_USD = 10.0   # מתחת לזה לא שווה (עמלות/מינימום)


def transfer_spot_to_futures(amount: float) -> bool:
    """מעביר USDC מארנק Spot ל-Futures. מוגבל ל-MAX_TRANSFER_USD."""
    amount = round(min(float(amount), MAX_TRANSFER_USD), 2)
    if amount < MIN_TRANSFER_USD:
        logging.info(f"[Transfer] סכום ${amount} קטן מהמינימום — מדלג")
        return False
    try:
        from kraken_bot import _request as spot_request
        res = spot_request("/0/private/WalletTransfer", {
            "asset":  "USDC",
            "from":   "Spot Wallet",
            "to":     "Futures Wallet",
            "amount": f"{amount:.2f}",
        }, private=True)
        refid = res.get("refid", "?")
        logging.warning(f"[Transfer] Spot→Futures ${amount:.2f} USDC | refid={refid}")
        return True
    except Exception as e:
        logging.error(f"[Transfer] Spot→Futures failed: {e}")
        return False


def transfer_futures_to_spot(amount: float) -> bool:
    """מחזיר USDC מארנק Futures (flex) ל-Spot. מוגבל ל-MAX_TRANSFER_USD."""
    amount = round(min(float(amount), MAX_TRANSFER_USD), 2)
    if amount < MIN_TRANSFER_USD:
        return False
    try:
        data = _request("/withdrawal", {
            "currency":     "usdc",
            "amount":       f"{amount:.2f}",
            "sourceWallet": "flex",
        }, method="POST")
        uid = data.get("uid", "?")
        logging.warning(f"[Transfer] Futures→Spot ${amount:.2f} USDC | uid={uid}")
        return True
    except Exception as e:
        logging.error(f"[Transfer] Futures→Spot failed: {e}")
        return False


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


_SIZE_PREC_CACHE = None


def get_size_precision(symbol: str) -> int:
    """דיוק הכמות המותר למכשיר (contractValueTradePrecision) — שליחת יותר
    ספרות מזה נדחית ע"י קרקן כ-invalidSize. 0 = חוזים שלמים בלבד.
    נשלף פעם אחת מ-/instruments (endpoint ציבורי) ונשמר בקאש לתהליך."""
    global _SIZE_PREC_CACHE
    if _SIZE_PREC_CACHE is None:
        try:
            r = requests.get(f"{BASE_URL}/instruments", timeout=15)
            _SIZE_PREC_CACHE = {
                i.get("symbol"): int(i.get("contractValueTradePrecision", 0))
                for i in r.json().get("instruments", [])
            }
        except Exception as e:
            logging.warning(f"[Futures] instruments fetch failed: {e}")
            _SIZE_PREC_CACHE = {}
    return _SIZE_PREC_CACHE.get(symbol, 0)


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
        # עיגול הכמות לדיוק האמיתי של המכשיר, כלפי מטה (לא לחרוג מהמרג'ין).
        # עיגול-ניחוש ל-4 ספרות נכשל ב-invalidSize על מכשירים של חוזים שלמים (AVA, SPCX).
        prec   = get_size_precision(symbol)
        factor = 10 ** prec
        size_q = int(float(size) * factor) / factor
        if size_q <= 0:
            raise Exception(f"size {size} rounds to 0 at precision {prec} (min tradeable = {1/factor})")
        size_str = f"{size_q:.{prec}f}" if prec > 0 else str(int(size_q))
        params = {
            "symbol": symbol,
            "side": side,
            "orderType": "lmt",
            "size": size_str,
            "limitPrice": str(round(limit_price, 2)),
        }
        data = _request("/sendorder", params, method="POST")
        status = data.get("sendStatus", {})
        order_status = status.get("status", "")
        order_id = status.get("order_id", "?")
        # ה-API מחזיר result="success" גם כשהפקודה נדחתה בפועל (למשל margin/price) —
        # הסטטוס האמיתי נמצא ב-sendStatus.status, ורק "placed" מציין שהפקודה אכן נכנסה לשוק.
        if order_status != "placed":
            raise Exception(f"Order rejected: status={order_status} | {status}")
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
