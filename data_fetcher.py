# data_fetcher.py - שולף נתונים מהאינטרנט

import requests
import yfinance as yf
from datetime import datetime, date


def _last_completed_rows(hist, n=2):
    """מחזיר את n השורות האחרונות של ימי מסחר שהסתיימו (לא היום)."""
    today = date.today()
    completed = hist[hist.index.date < today]
    if len(completed) < n:
        completed = hist  # fallback אם אין מספיק ימים
    return completed.iloc[-n:]


def get_stock_data(symbols):
    """מניות אמריקאיות"""
    results = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info
            news = ticker.news or []
            hist = ticker.history(period="5d")
            rows = _last_completed_rows(hist, 2)
            if len(rows) >= 2:
                price = round(rows["Close"].iloc[-1], 2)
                prev = round(rows["Close"].iloc[-2], 2)
            elif len(rows) == 1:
                price = round(rows["Close"].iloc[-1], 2)
                prev = price
            else:
                price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev = info.get("previousClose", price)
            change_pct = ((price - prev) / prev * 100) if prev else 0
            try:
                calendar = ticker.calendar
                earnings_date = None
                if calendar is not None and "Earnings Date" in calendar:
                    ed = calendar["Earnings Date"]
                    earnings_date = str(list(ed)[0])[:10] if hasattr(ed, '__iter__') else str(ed)[:10]
            except:
                earnings_date = None
            results[sym] = {
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "pe_ratio": info.get("trailingPE"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "analyst_target": info.get("targetMeanPrice"),
                "num_analysts": info.get("numberOfAnalystOpinions", 0),
                "sector": info.get("sector", "Unknown"),
                "earnings_date": earnings_date,
                "news": [{"title": n.get("title",""), "publisher": n.get("publisher","")} for n in news[:5]],
            }
        except Exception as e:
            results[sym] = {"error": str(e)}
    return results


def get_il_stock_data(portfolio_il):
    """מניות ישראליות - מחירים באגורות, מחלק ב-100 לשקלים"""
    results = {}
    for sym, config in portfolio_il.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            rows = _last_completed_rows(hist, 2)
            if len(rows) >= 2:
                price_agorot = rows["Close"].iloc[-1]
                prev_agorot = rows["Close"].iloc[-2]
            elif len(rows) == 1:
                price_agorot = rows["Close"].iloc[-1]
                prev_agorot = price_agorot
            else:
                info = ticker.info
                price_agorot = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev_agorot = info.get("previousClose", price_agorot)
            price_ils = round(price_agorot / 100, 2)
            prev_ils = round(prev_agorot / 100, 2)
            change_pct = ((price_ils - prev_ils) / prev_ils * 100) if prev_ils else 0
            news = ticker.news or []
            results[sym] = {
                "name": config["name"],
                "price": price_ils,
                "change_pct": round(change_pct, 2),
                "currency": "ILS",
                "news": [{"title": n.get("title",""), "publisher": n.get("publisher","")} for n in news[:3]],
            }
        except Exception as e:
            results[sym] = {"name": config["name"], "error": str(e)}
    return results


def get_index_data(funds_il):
    """נתוני מדדים עבור הקרנות"""
    results = {}
    for fund_key, config in funds_il.items():
        sym = config["tracks_symbol"]
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            rows = _last_completed_rows(hist, 2)
            if len(rows) >= 2:
                price = round(rows["Close"].iloc[-1], 2)
                prev = round(rows["Close"].iloc[-2], 2)
                change_pct = round(((price - prev) / prev) * 100, 2)
                ytd_start = hist["Close"].iloc[0]
                ytd_pct = round(((price - ytd_start) / ytd_start) * 100, 2)
                results[fund_key] = {
                    "name": config["name"],
                    "tracks": config["tracks"],
                    "index_price": price,
                    "change_pct": change_pct,
                    "period_pct": ytd_pct,
                }
        except Exception as e:
            results[fund_key] = {"name": config["name"], "error": str(e)}
    return results


def collect_all_data(us_symbols, portfolio_il, funds_il):
    print("משיג נתונים...")
    stock_data = get_stock_data(us_symbols)
    print("  ✅ מניות אמריקאיות")
    il_data = get_il_stock_data(portfolio_il)
    print("  ✅ מניות ישראליות")
    index_data = get_index_data(funds_il)
    print("  ✅ מדדים")

    # נתונים מועשרים מ-Finnhub
    finnhub_data = {}
    try:
        from finnhub_fetcher import enrich_us_stocks
        print("  [Finnhub] fetching...")
        finnhub_data = enrich_us_stocks(us_symbols)
        print("  OK Finnhub")
    except Exception as e:
        print(f"  WARN Finnhub failed: {e}")

    # נתונים מ-SEC Edgar
    sec_data = {}
    try:
        from sec_fetcher import fetch_sec_data_for_portfolio
        print("  [SEC] fetching...")
        sec_data = fetch_sec_data_for_portfolio(us_symbols)
        print("  OK SEC Edgar")
    except Exception as e:
        print(f"  WARN SEC failed: {e}")

    # נתונים מ-Finviz
    finviz_data = {}
    try:
        from finviz_fetcher import get_portfolio_finviz_data
        print("  [Finviz] fetching...")
        finviz_data = get_portfolio_finviz_data(us_symbols)
        print("  OK Finviz")
    except Exception as e:
        print(f"  WARN Finviz failed: {e}")

    return {
        "stocks": stock_data,
        "il_stocks": il_data,
        "indices": index_data,
        "finnhub": finnhub_data,
        "sec": sec_data,
        "finviz": finviz_data,
        "fetched_at": datetime.now().isoformat()
    }
