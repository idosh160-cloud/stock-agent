# agent.py - שולח את הנתונים ל-Claude לניתוח

import json
import anthropic
import yfinance as yf
from datetime import datetime
import pytz
from config import PORTFOLIO_US, PORTFOLIO_IL, FUNDS_IL, RISK_PROFILE, HIDDEN_GEMS_COUNT

client = anthropic.Anthropic()

def is_market_open():
    ny_tz = pytz.timezone("America/New_York")
    now = datetime.now(ny_tz)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close

def get_us_prices(symbols):
    market_open = is_market_open()
    prices = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            if market_open:
                info = ticker.info
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                prices[sym] = {"price": round(float(price), 2), "type": "live"}
            else:
                hist = ticker.history(period="2d")
                if len(hist) >= 1:
                    prices[sym] = {"price": round(float(hist["Close"].iloc[-1]), 2), "type": "close"}
        except:
            prices[sym] = {"price": None, "type": "unknown"}
    return prices, market_open

def get_analyst_targets(symbols):
    targets = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info
            target = info.get("targetMeanPrice")
            targets[sym] = {
                "target": round(float(target), 2) if target else None,
                "num_analysts": info.get("numberOfAnalystOpinions", 0)
            }
        except:
            targets[sym] = {"target": None, "num_analysts": 0}
    return targets

def get_il_prices(portfolio_il):
    """Yahoo Finance מחזיר אגורות - מחלק ב-100 לשקלים"""
    prices = {}
    for sym in portfolio_il:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info
            price_agorot = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            prev_agorot = info.get("previousClose", price_agorot)
            price_ils = round(float(price_agorot) / 100, 2)
            prev_ils = round(float(prev_agorot) / 100, 2)
            change_pct = round(((price_ils - prev_ils) / prev_ils * 100), 2) if prev_ils else 0
            news = ticker.news or []
            prices[sym] = {
                "price": price_ils,
                "change_pct": change_pct,
                "news": [{"title": n.get("title", "")} for n in news[:3]]
            }
        except:
            prices[sym] = {"price": 0, "change_pct": 0, "news": []}
    return prices

def get_hidden_gems_data(symbols):
    results = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info
            hist = ticker.history(period="6mo")
            current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            gain_6mo = round(((current_price - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100), 1) if len(hist) > 0 else 0
            try:
                calendar = ticker.calendar
                earnings_date = None
                if calendar is not None and "Earnings Date" in calendar:
                    ed = calendar["Earnings Date"]
                    earnings_date = str(list(ed)[0])[:10] if hasattr(ed, '__iter__') else str(ed)[:10]
            except:
                earnings_date = None
            results[sym] = {
                "price": round(float(current_price), 2),
                "gain_6mo_pct": gain_6mo,
                "sector": info.get("sector", "Unknown"),
                "name": info.get("longName", sym),
                "earnings_date": earnings_date,
            }
        except Exception as e:
            results[sym] = {"error": str(e)}
    return results

def analyze_portfolio(market_data):
    us_prices, market_open = get_us_prices(list(PORTFOLIO_US.keys()))
    analyst_data = get_analyst_targets(list(PORTFOLIO_US.keys()))
    il_prices = get_il_prices(PORTFOLIO_IL)
    price_label = "Live price" if market_open else "Closing price"

    # מניות אמריקאיות
    us_summary = []
    total_us_current = 0
    total_us_original = 0
    for sym, config in PORTFOLIO_US.items():
        stock = market_data["stocks"].get(sym, {})
        price = us_prices.get(sym, {}).get("price") or stock.get("price", 0)
        avg_cost = config["avg_cost"]
        shares = config["shares"]
        current_value = round(price * shares, 2)
        original_value = round(avg_cost * shares, 2)
        total_us_current += current_value
        total_us_original += original_value
        pnl_dollars = round(current_value - original_value, 2)
        pnl_pct = round(((price - avg_cost) / avg_cost * 100), 1) if avg_cost else 0
        analyst_info = analyst_data.get(sym, {})
        analyst_target = analyst_info.get("target")
        num_analysts = analyst_info.get("num_analysts", 0)
        upside = round(((analyst_target - price) / price * 100), 1) if analyst_target and price else None
        us_summary.append({
            "symbol": sym,
            "name": config["name"],
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": price,
            "price_type": price_label,
            "current_value": current_value,
            "original_value": original_value,
            "pnl_dollars": pnl_dollars,
            "pnl_pct": pnl_pct,
            "daily_change_pct": stock.get("change_pct", 0),
            "analyst_target": analyst_target,
            "num_analysts": num_analysts,
            "upside_to_target_pct": upside,
            "52w_high": stock.get("52w_high"),
            "52w_low": stock.get("52w_low"),
            "earnings_date": stock.get("earnings_date"),
            "news": stock.get("news", [])[:3],
        })

    # מניות ישראליות - מחירים בשקלים
    il_summary = []
    total_il_current = 0
    total_il_original = 0
    for sym, config in PORTFOLIO_IL.items():
        price_data = il_prices.get(sym, {})
        price = price_data.get("price", 0)
        avg_cost = config["avg_cost"]  # כבר בשקלים
        shares = config["shares"]
        current_value = round(price * shares, 2)
        original_value = round(avg_cost * shares, 2)
        total_il_current += current_value
        total_il_original += original_value
        pnl_ils = round(current_value - original_value, 2)
        pnl_pct = round(((price - avg_cost) / avg_cost * 100), 1) if avg_cost else 0
        il_summary.append({
            "symbol": sym,
            "name": config["name"],
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": price,
            "current_value": current_value,
            "original_value": original_value,
            "pnl_ils": pnl_ils,
            "pnl_pct": pnl_pct,
            "daily_change_pct": price_data.get("change_pct", 0),
            "news": price_data.get("news", []),
        })

    # קרנות ישראליות
    funds_summary = []
    for fund_key, config in FUNDS_IL.items():
        index_data = market_data["indices"].get(fund_key, {})
        avg_cost = config["avg_cost"]  # בשקלים
        shares = config["shares"]
        original_value = round(avg_cost * shares, 2)
        funds_summary.append({
            "name": config["name"],
            "tracks": config["tracks"],
            "shares": shares,
            "avg_cost": avg_cost,
            "original_value": original_value,
            "index_change_pct": index_data.get("change_pct", 0),
        })

    portfolio_totals = {
        "total_us_current_usd": round(total_us_current, 2),
        "total_us_original_usd": round(total_us_original, 2),
        "total_us_pnl_usd": round(total_us_current - total_us_original, 2),
        "total_us_pnl_pct": round(((total_us_current - total_us_original) / total_us_original * 100), 1) if total_us_original else 0,
        "total_il_current_ils": round(total_il_current, 2),
        "total_il_original_ils": round(total_il_original, 2),
        "total_il_pnl_ils": round(total_il_current - total_il_original, 2),
        "total_il_pnl_pct": round(((total_il_current - total_il_original) / total_il_original * 100), 1) if total_il_original else 0,
    }

    prompt = f"""Today: {market_data['fetched_at'][:10]}
Price type: {price_label}
Risk profile: {RISK_PROFILE}

PORTFOLIO TOTALS:
{json.dumps(portfolio_totals, indent=2)}

US STOCKS:
{json.dumps(us_summary, indent=2)}

ISRAELI STOCKS (all prices in ILS - Israeli Shekels):
{json.dumps(il_summary, indent=2)}

ISRAELI FUNDS (analyze the INDEX they track, not the fund):
{json.dumps(funds_summary, indent=2)}

INSTRUCTIONS:
1. Market summary: S&P500, Nasdaq, macro trends. Max 4 sentences.
2. US stocks: MAX 2 sentences reasoning + support/resistance/entry/stop loss
3. Israeli stocks: MAX 2 sentences, prices in ILS
4. Funds: analyze the INDEX they track. MAX 2 sentences each.
5. Hidden gems: {HIDDEN_GEMS_COUNT} NASDAQ/NYSE stocks - AI infrastructure bottlenecks:
   - Power grid, transformers, cooling, fiber, specialty materials
   - NOT risen more than 100% in 6 months, small/mid cap
   - NOT NVDA/MSFT/GOOGL/META/AMZN

JSON only, no markdown:
{{
  "market_summary": "...",
  "yesterday_recap": "...",
  "rumors_and_contracts": "...",
  "portfolio_totals": {{
    "total_us_current_usd": 0,
    "total_us_pnl_usd": 0,
    "total_us_pnl_pct": 0,
    "total_il_current_ils": 0,
    "total_il_pnl_ils": 0,
    "total_il_pnl_pct": 0
  }},
  "us_recommendations": [
    {{
      "symbol": "BW",
      "name": "Babcock & Wilcox",
      "action": "HOLD",
      "confidence": "HIGH",
      "current_price": 19.50,
      "avg_cost": 14.81,
      "current_value": 2281.50,
      "original_value": 1732.77,
      "pnl_dollars": 548.73,
      "pnl_pct": 31.7,
      "daily_change_pct": -0.43,
      "analyst_target": 24.50,
      "analyst_target_explanation": "Consensus of 4 analysts",
      "upside_to_target_pct": 26.0,
      "earnings_date": "2026-08-01",
      "earnings_expectations": "EPS $0.12 expected",
      "support_levels": "$17.50, $16.80",
      "resistance_levels": "$21.00, $24.67",
      "entry_point": "Add at $17.50",
      "stop_loss": "$15.50",
      "reasoning": "Max 2 sentences."
    }}
  ],
  "il_recommendations": [
    {{
      "symbol": "PHOE.TA",
      "name": "הפניקס",
      "action": "HOLD",
      "confidence": "MEDIUM",
      "current_price": 186.50,
      "avg_cost": 188.60,
      "current_value": 9884.50,
      "original_value": 9995.80,
      "pnl_ils": -111.30,
      "pnl_pct": -1.1,
      "daily_change_pct": 0,
      "support_levels": "₪175, ₪165",
      "resistance_levels": "₪200, ₪215",
      "reasoning": "Max 2 sentences."
    }}
  ],
  "funds_analysis": [
    {{
      "name": "ממ SP500 הראל",
      "tracks": "S&P 500",
      "original_value": 45402,
      "index_change_pct": 0.97,
      "recommendation": "HOLD",
      "index_analysis": "Max 2 sentences about the S&P 500 index."
    }}
  ],
  "hidden_gems": [
    {{
      "symbol": "TICKER",
      "name": "Company",
      "sector": "Sector",
      "current_price": 0.0,
      "gain_6mo_pct": 0.0,
      "earnings_date": "",
      "why_interesting": "Max 2 sentences.",
      "ai_infrastructure_angle": "How this benefits from AI buildout.",
      "catalyst": "Specific catalyst.",
      "risk": "Main risk."
    }}
  ]
}}"""

    print("שולח ל-Claude לניתוח...")
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    print("✅ ניתוח הושלם")
    analysis = json.loads(raw.strip())
    analysis["portfolio_totals"] = portfolio_totals

    gem_symbols = [g["symbol"] for g in analysis.get("hidden_gems", [])]
    if gem_symbols:
        print("משיג מחירים לפנינות...")
        gems_data = get_hidden_gems_data(gem_symbols)
        for gem in analysis["hidden_gems"]:
            real = gems_data.get(gem["symbol"], {})
            if real and "error" not in real:
                gem["current_price"] = real["price"]
                gem["gain_6mo_pct"] = real["gain_6mo_pct"]
                gem["name"] = real["name"]
                gem["sector"] = real["sector"]
                if real.get("earnings_date"):
                    gem["earnings_date"] = real["earnings_date"]

    return analysis