# finviz_fetcher.py - נתונים מ-Finviz (חינמי, ללא API key)

import time
import finviz
from finviz.screener import Screener


def get_stock_details(symbol):
    """נתונים מפורטים על מניה — short interest, insider, RSI וכו'"""
    try:
        data = finviz.get_stock(symbol)
        return {
            "short_float":    data.get("Short Float"),
            "short_ratio":    data.get("Short Ratio"),
            "insider_own":    data.get("Insider Own"),
            "insider_trans":  data.get("Insider Trans"),
            "inst_own":       data.get("Inst Own"),
            "inst_trans":     data.get("Inst Trans"),
            "pe_ratio":       data.get("P/E"),
            "forward_pe":     data.get("Forward P/E"),
            "peg":            data.get("PEG"),
            "eps_next_y":     data.get("EPS next Y"),
            "sales_past_5y":  data.get("Sales past 5Y"),
            "roe":            data.get("ROE"),
            "debt_eq":        data.get("Debt/Eq"),
            "gross_margin":   data.get("Gross Margin"),
            "rsi":            data.get("RSI (14)"),
            "perf_week":      data.get("Perf Week"),
            "perf_month":     data.get("Perf Month"),
            "perf_ytd":       data.get("Perf YTD"),
            "analyst_recom":  data.get("Recom"),
            "target_price":   data.get("Target Price"),
            "52w_high":       data.get("52W High"),
            "52w_low":        data.get("52W Low"),
            "avg_volume":     data.get("Avg Volume"),
            "rel_volume":     data.get("Rel Volume"),
            "market_cap":     data.get("Market Cap"),
            "sector":         data.get("Sector"),
            "industry":       data.get("Industry"),
        }
    except Exception as e:
        return {"error": str(e)}


def screen_hidden_gems(count=20):
    """
    מסנן מניות AI Infrastructure — תשתיות, אנרגיה, חומרים, קירור
    Small/Mid cap, גידול במכירות, forward P/E סביר
    """
    try:
        filters = [
            "cap_smallover",        # Small cap ומעלה (לא מיקרו)
            "cap_midunder",         # עד Mid cap
            "fa_fpe_u40",           # Forward P/E מתחת ל-40
            "fa_salesqoq_pos",      # גידול במכירות רבעוני
            "geo_usa",              # חברות אמריקאיות
            "sec_technology",       # סקטור טכנולוגיה
        ]
        screener = Screener(filters=filters, table="Overview", order="-volume")
        tech_results = _parse_screener(screener, count // 2)
    except Exception as e:
        print(f"  [Finviz] tech screener error: {e}")
        tech_results = []

    try:
        filters2 = [
            "cap_smallover",
            "cap_midunder",
            "fa_fpe_u40",
            "fa_salesqoq_pos",
            "geo_usa",
            "sec_utilities",        # חברות אנרגיה/חשמל לAI
        ]
        screener2 = Screener(filters=filters2, table="Overview", order="-volume")
        util_results = _parse_screener(screener2, count // 2)
    except Exception as e:
        print(f"  [Finviz] utilities screener error: {e}")
        util_results = []

    try:
        filters3 = [
            "cap_smallover",
            "cap_midunder",
            "fa_salesqoq_pos",
            "geo_usa",
            "sec_industrials",      # תעשייה — קירור, transformers
        ]
        screener3 = Screener(filters=filters3, table="Overview", order="-volume")
        ind_results = _parse_screener(screener3, count // 3)
    except Exception as e:
        print(f"  [Finviz] industrials screener error: {e}")
        ind_results = []

    # מיזוג וביטול כפילויות
    seen = set()
    combined = []
    for r in tech_results + util_results + ind_results:
        sym = r.get("symbol", "")
        if sym and sym not in seen:
            seen.add(sym)
            combined.append(r)

    return combined[:count]


def screen_wildcard(count=5):
    """
    מסנן מניות חלל וקוונטום — wildcard שבועי
    """
    space_quantum = [
        # חלל
        "RKLB", "ASTS", "LUNR", "RDW", "SPCE", "KTOS", "AJRD",
        "MNTS", "VORB", "IRDM", "MAXR", "BKSY", "GSAT",
        # קוונטום
        "IONQ", "RGTI", "QUBT", "QBTS", "QTUM", "ARQQ", "QMCO",
        "IBM",  "GOOGL", "MSFT",
    ]
    results = []
    for sym in space_quantum:
        try:
            d = finviz.get_stock(sym)
            results.append({
                "symbol":     sym,
                "name":       d.get("Company", sym),
                "sector":     d.get("Sector", ""),
                "industry":   d.get("Industry", ""),
                "price":      d.get("Price", ""),
                "change_pct": d.get("Perf Week", ""),
                "market_cap": d.get("Market Cap", ""),
                "pe":         d.get("P/E", ""),
                "forward_pe": d.get("Forward P/E", ""),
                "rsi":        d.get("RSI (14)", ""),
                "short_float":d.get("Short Float", ""),
                "perf_month": d.get("Perf Month", ""),
                "analyst_recom": d.get("Recom", ""),
            })
            time.sleep(0.5)
        except Exception:
            pass
        if len(results) >= count * 3:
            break
    return results


def _parse_screener(screener, count):
    results = []
    for row in screener:
        results.append({
            "symbol":     row.get("Ticker", ""),
            "name":       row.get("Company", ""),
            "sector":     row.get("Sector", ""),
            "price":      row.get("Price", ""),
            "change_pct": row.get("Change", ""),
            "market_cap": row.get("Market Cap", ""),
            "pe":         row.get("P/E", ""),
            "volume":     row.get("Volume", ""),
        })
        if len(results) >= count:
            break
    return results


def get_portfolio_finviz_data(symbols):
    """שולף נתוני Finviz לכל מניה בתיק"""
    results = {}
    for sym in symbols:
        print(f"  [Finviz] {sym}...")
        results[sym] = get_stock_details(sym)
        time.sleep(1)
    return results
