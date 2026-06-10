# finnhub_fetcher.py - נתונים מועשרים מ-Finnhub

import os
import requests
from datetime import datetime, timedelta

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
BASE_URL = "https://finnhub.io/api/v1"


def _get(endpoint, params={}):
    try:
        params["token"] = FINNHUB_API_KEY
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def get_analyst_consensus(symbol):
    """המלצות אנליסטים: כמה BUY / HOLD / SELL"""
    data = _get("stock/recommendation", {"symbol": symbol})
    if isinstance(data, list) and len(data) > 0:
        latest = data[0]
        return {
            "strong_buy": latest.get("strongBuy", 0),
            "buy": latest.get("buy", 0),
            "hold": latest.get("hold", 0),
            "sell": latest.get("sell", 0),
            "strong_sell": latest.get("strongSell", 0),
            "period": latest.get("period", ""),
        }
    return {}


def get_earnings_surprise(symbol):
    """האם החברה הפתיעה לטובה/לרעה בדוחות האחרונים"""
    data = _get("stock/earnings", {"symbol": symbol, "limit": 4})
    if not isinstance(data, list):
        return []
    results = []
    for e in data[:4]:
        actual = e.get("actual")
        estimate = e.get("estimate")
        if actual is not None and estimate is not None and estimate != 0:
            surprise_pct = round(((actual - estimate) / abs(estimate)) * 100, 1)
        else:
            surprise_pct = None
        results.append({
            "period": e.get("period", ""),
            "actual_eps": actual,
            "estimated_eps": estimate,
            "surprise_pct": surprise_pct,
        })
    return results


def get_insider_trades(symbol):
    """מסחר פנימי — האם מנהלים קנו או מכרו לאחרונה"""
    from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")
    data = _get("stock/insider-transactions", {
        "symbol": symbol, "from": from_date, "to": to_date
    })
    trades = data.get("data", []) if isinstance(data, dict) else []
    summary = {"buys": 0, "sells": 0, "buy_value": 0, "sell_value": 0}
    for t in trades[:20]:
        txn = t.get("transactionCode", "")
        shares = t.get("share", 0) or 0
        price = t.get("transactionPrice", 0) or 0
        value = shares * price
        if txn in ("P", "A"):  # Purchase / Award
            summary["buys"] += 1
            summary["buy_value"] += value
        elif txn in ("S", "D"):  # Sale / Disposition
            summary["sells"] += 1
            summary["sell_value"] += value
    return summary


def get_company_news_sentiment(symbol):
    """חדשות + sentiment בסיסי לפי כמות חיובי/שלילי"""
    from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")
    data = _get("company-news", {
        "symbol": symbol, "from": from_date, "to": to_date
    })
    if not isinstance(data, list):
        return []
    news = []
    for n in data[:5]:
        news.append({
            "headline": n.get("headline", ""),
            "source": n.get("source", ""),
            "datetime": datetime.fromtimestamp(n.get("datetime", 0)).strftime("%Y-%m-%d") if n.get("datetime") else "",
            "sentiment": n.get("sentiment", ""),
        })
    return news


def get_price_target(symbol):
    """יעד מחיר ממוצע מאנליסטים"""
    data = _get("stock/price-target", {"symbol": symbol})
    if isinstance(data, dict):
        return {
            "target_high": data.get("targetHigh"),
            "target_low": data.get("targetLow"),
            "target_mean": data.get("targetMean"),
            "last_updated": data.get("lastUpdated", ""),
        }
    return {}


def enrich_us_stocks(symbols):
    """שולף את כל הנתונים המועשרים לכל מניה אמריקאית"""
    enriched = {}
    for sym in symbols:
        print(f"  [Finnhub] {sym}...")
        enriched[sym] = {
            "analyst_consensus": get_analyst_consensus(sym),
            "earnings_surprises": get_earnings_surprise(sym),
            "insider_trades": get_insider_trades(sym),
            "recent_news": get_company_news_sentiment(sym),
            "price_target": get_price_target(sym),
        }
    return enriched
