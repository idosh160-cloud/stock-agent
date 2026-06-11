# agent.py - שולח את הנתונים ל-Claude לניתוח

import json
import os
import time
import math
import anthropic
import yfinance as yf
from datetime import datetime
import pytz
from dotenv import load_dotenv


def _safe_price(val):
    """מחזיר 0 אם הערך הוא None, NaN, או אינסוף"""
    try:
        v = float(val)
        return v if math.isfinite(v) else 0
    except (TypeError, ValueError):
        return 0

ENV_PATH = r"C:\Users\User\Documents\stock_agent\.env"

def _load_env():
    try:
        with open(ENV_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if v:  # תמיד מחליף אם יש ערך
                        os.environ[k] = v
    except Exception:
        pass

_load_env()

from config import PORTFOLIO_US, PORTFOLIO_IL, FUNDS_IL, RISK_PROFILE, HIDDEN_GEMS_COUNT

def _get_client():
    _load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=key)

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
        price = _safe_price(us_prices.get(sym, {}).get("price") or stock.get("price", 0))
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
        # נתוני Finnhub
        fh = market_data.get("finnhub", {}).get(sym, {})
        consensus = fh.get("analyst_consensus", {})
        surprises = fh.get("earnings_surprises", [])
        insider = fh.get("insider_trades", {})
        fh_news = fh.get("recent_news", [])
        fh_target = fh.get("price_target", {})

        # יעד מחיר — Finnhub עדיף על yfinance
        if fh_target.get("target_mean"):
            analyst_target = fh_target["target_mean"]
            upside = round(((analyst_target - price) / price * 100), 1) if analyst_target and price else None

        # מיזוג חדשות — Finnhub + yfinance
        combined_news = fh_news if fh_news else stock.get("news", [])[:3]

        # נתוני Finviz
        fv = market_data.get("finviz", {}).get(sym, {})
        finviz_summary = {
            "short_float":   fv.get("short_float"),
            "insider_trans": fv.get("insider_trans"),
            "rsi":           fv.get("rsi"),
            "perf_week":     fv.get("perf_week"),
            "perf_month":    fv.get("perf_month"),
            "debt_eq":       fv.get("debt_eq"),
            "gross_margin":  fv.get("gross_margin"),
            "analyst_recom": fv.get("analyst_recom"),
        }

        # נתוני SEC Edgar
        sec = market_data.get("sec", {}).get(sym, {})
        sec_summary = {
            "latest_filing_type": sec.get("latest_filing_type", ""),
            "latest_filing_date": sec.get("latest_filing_date", ""),
            "recent_form4_count": sec.get("recent_form4_count", 0),
            "filing_excerpt": sec.get("filing_text_excerpt", "")[:3000],
        }

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
            "analyst_target_high": fh_target.get("target_high"),
            "analyst_target_low": fh_target.get("target_low"),
            "num_analysts": num_analysts,
            "upside_to_target_pct": upside,
            "analyst_consensus": consensus,
            "earnings_surprises_last_4q": surprises,
            "insider_trades_90d": insider,
            "finviz": finviz_summary,
            "sec_filing": sec_summary,
            "52w_high": stock.get("52w_high"),
            "52w_low": stock.get("52w_low"),
            "earnings_date": stock.get("earnings_date"),
            "news": combined_news,
        })

    # מניות ישראליות - מחירים בשקלים
    il_summary = []
    total_il_current = 0
    total_il_original = 0
    for sym, config in PORTFOLIO_IL.items():
        price_data = il_prices.get(sym, {})
        price = _safe_price(price_data.get("price", 0))
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

    # עיבוד אותות לפני שליחה ל-Claude
    def build_signals(stock_data):
        signals = []
        warnings = []

        # אנליסטים
        consensus = stock_data.get("analyst_consensus", {})
        total_analysts = sum([
            consensus.get("strong_buy", 0), consensus.get("buy", 0),
            consensus.get("hold", 0), consensus.get("sell", 0), consensus.get("strong_sell", 0)
        ])
        if total_analysts > 0:
            buys = consensus.get("strong_buy", 0) + consensus.get("buy", 0)
            sells = consensus.get("sell", 0) + consensus.get("strong_sell", 0)
            buy_pct = round(buys / total_analysts * 100)
            if buy_pct >= 70:
                signals.append(f"ANALYST CONSENSUS BULLISH: {buys}/{total_analysts} analysts say BUY ({buy_pct}%)")
            elif sells / total_analysts > 0.3:
                warnings.append(f"ANALYST WARNING: {sells}/{total_analysts} analysts say SELL")

        # EPS Surprises
        surprises = stock_data.get("earnings_surprises_last_4q", [])
        if surprises:
            beats = [s for s in surprises if (s.get("surprise_pct") or 0) > 0]
            misses = [s for s in surprises if (s.get("surprise_pct") or 0) < -10]
            if len(beats) >= 3:
                pcts = [f"{s['surprise_pct']}%" for s in beats[:3]]
                signals.append(f"EARNINGS MOMENTUM: Beat estimates {len(beats)} of last {len(surprises)} quarters ({', '.join(pcts)})")
            elif len(misses) >= 2:
                warnings.append(f"EARNINGS CONCERN: Missed estimates {len(misses)} of last {len(surprises)} quarters")

        # מסחר פנימי — Finnhub
        insider = stock_data.get("insider_trades_90d", {})
        buy_val = insider.get("buy_value", 0) or 0
        sell_val = insider.get("sell_value", 0) or 0
        if buy_val > 100000:
            signals.append(f"INSIDER BUYING: Executives bought ${buy_val:,.0f} worth in last 90 days — bullish signal")
        if sell_val > 500000:
            warnings.append(f"INSIDER SELLING: Executives sold ${sell_val:,.0f} worth in last 90 days — watch closely")

        # Finviz
        fv = stock_data.get("finviz", {})
        short_float = fv.get("short_float", "")
        try:
            sf_num = float(str(short_float).replace("%", ""))
            if sf_num > 20:
                warnings.append(f"HIGH SHORT INTEREST: {short_float} of float is shorted — high risk/reward")
            elif sf_num > 15:
                warnings.append(f"ELEVATED SHORT INTEREST: {short_float} — possible short squeeze or real concern")
        except:
            pass

        rsi = fv.get("rsi", "")
        try:
            rsi_num = float(str(rsi))
            if rsi_num > 70:
                warnings.append(f"RSI OVERBOUGHT: {rsi} — consider waiting for pullback before adding")
            elif rsi_num < 35:
                signals.append(f"RSI OVERSOLD: {rsi} — potential entry opportunity")
        except:
            pass

        insider_trans = fv.get("insider_trans", "")
        try:
            it_num = float(str(insider_trans).replace("%", ""))
            if it_num < -15:
                warnings.append(f"INSIDER NET SELLING: {insider_trans} net change — management reducing exposure")
        except:
            pass

        debt_eq = fv.get("debt_eq", "")
        try:
            de_num = float(str(debt_eq))
            if de_num > 2.0:
                warnings.append(f"HIGH DEBT: Debt/Equity ratio {debt_eq} — monitor cash flow carefully")
        except:
            pass

        return signals, warnings

    # בניית בלוק ניתוח לכל מניה
    us_analysis_blocks = []
    for stock in us_summary:
        sym = stock["symbol"]
        signals, warnings = build_signals(stock)
        sec = stock.get("sec_filing", {})
        sec_text = sec.get("filing_excerpt", "")[:2000]

        block = f"""
=== {sym} — {stock['name']} ===
PRICE: ${stock['current_price']} | AVG COST: ${stock['avg_cost']} | P&L: ${stock['pnl_dollars']:+.0f} ({stock['pnl_pct']:+.1f}%)
VALUE: ${stock['current_value']:,.0f} | DAILY: {stock['daily_change_pct']:+.2f}%
ANALYST TARGET: ${stock.get('analyst_target') or 'N/A'} | UPSIDE: {stock.get('upside_to_target_pct') or 'N/A'}%
52W RANGE: ${stock.get('52w_low')} — ${stock.get('52w_high')}
NEXT EARNINGS: {stock.get('earnings_date') or 'Unknown'}
RSI: {stock.get('finviz',{}).get('rsi','N/A')} | SHORT FLOAT: {stock.get('finviz',{}).get('short_float','N/A')}
GROSS MARGIN: {stock.get('finviz',{}).get('gross_margin','N/A')} | DEBT/EQ: {stock.get('finviz',{}).get('debt_eq','N/A')}

BULLISH SIGNALS ({len(signals)}):
{chr(10).join(f'  ✅ {s}' for s in signals) if signals else '  (none)'}

WARNING SIGNALS ({len(warnings)}):
{chr(10).join(f'  ⚠️ {w}' for w in warnings) if warnings else '  (none)'}

LATEST SEC FILING ({sec.get('latest_filing_type','')} — {sec.get('latest_filing_date','')}):
{sec_text if sec_text else '(not available)'}

RECENT NEWS:
{chr(10).join(f"  - {n.get('headline') or n.get('title','')}" for n in stock.get('news',[])[:3]) if stock.get('news') else '  (none)'}
"""
        us_analysis_blocks.append(block)

    # היסטוריית המלצות קודמות
    from history import format_history_for_prompt, get_recent_symbols
    history_text    = format_history_for_prompt()
    recent_symbols  = get_recent_symbols(days=7)

    # פנינות — סינון + העמקת מידע
    gems_context   = "  (screener unavailable — use your knowledge)"
    wildcard_context = "  (unavailable)"
    try:
        from finviz_fetcher import screen_hidden_gems, screen_wildcard
        from finnhub_fetcher import get_analyst_consensus, get_earnings_surprise, get_insider_trades

        # AI Infrastructure gems
        print("  [Gems] scanning AI infrastructure candidates...")
        screened = screen_hidden_gems(count=20)

        # העמקת מידע — Finnhub על כל מועמד
        enriched_gems = []
        for g in screened[:15]:
            sym = g.get("symbol", "")
            if not sym:
                continue
            try:
                consensus = get_analyst_consensus(sym)
                surprises = get_earnings_surprise(sym)
                insider   = get_insider_trades(sym)
                last_surprise = surprises[0].get("surprise_pct") if surprises else None
                buys = consensus.get("strong_buy", 0) + consensus.get("buy", 0)
                total = sum([consensus.get(k, 0) for k in ["strong_buy","buy","hold","sell","strong_sell"]])
                enriched_gems.append({
                    **g,
                    "analyst_buys": buys,
                    "analyst_total": total,
                    "last_eps_surprise_pct": last_surprise,
                    "insider_buys": insider.get("buys", 0),
                    "insider_sells": insider.get("sells", 0),
                    "insider_buy_value": insider.get("buy_value", 0),
                })
                time.sleep(0.3)
            except Exception:
                enriched_gems.append(g)

        gems_context = "\n".join([
            f"  {g['symbol']} | {g['name']} | {g['sector']} | "
            f"Price:{g.get('price','')} | MCap:{g.get('market_cap','')} | P/E:{g.get('pe','')} | "
            f"Analysts:{g.get('analyst_buys',0)}B/{g.get('analyst_total',0)}total | "
            f"LastEPS:{g.get('last_eps_surprise_pct','N/A')}% | "
            f"InsiderBuys:{g.get('insider_buys',0)}(${g.get('insider_buy_value',0):,.0f}) | "
            f"InsiderSells:{g.get('insider_sells',0)}"
            for g in enriched_gems
        ]) if enriched_gems else "  (screener unavailable — use your knowledge)"

        # Wildcard — חלל וקוונטום
        print("  [Gems] scanning space/quantum wildcard...")
        wildcards = screen_wildcard(count=5)
        wildcard_context = "\n".join([
            f"  {g['symbol']} | {g['name']} | {g.get('industry','')} | "
            f"Price:{g.get('price','')} | MCap:{g.get('market_cap','')} | "
            f"RSI:{g.get('rsi','')} | PerfMonth:{g.get('perf_month','')} | "
            f"Recom:{g.get('analyst_recom','')}"
            for g in wildcards
        ]) if wildcards else "  (unavailable)"

        print(f"  [Gems] {len(enriched_gems)} AI candidates, {len(wildcards)} wildcard candidates")

    except Exception as e:
        print(f"  [Gems] error: {e}")
        gems_context = "  (screener unavailable — use your knowledge)"
        wildcard_context = "  (unavailable)"

    prompt = f"""You are an expert stock analyst. Today is {market_data['fetched_at'][:10]}.
Price type: {price_label} | Risk profile: {RISK_PROFILE}

IMPORTANT: Write text fields (reasoning, position_advice, sec_insight, market_summary, yesterday_recap, rumors_and_contracts, why_interesting, catalyst, risk) in Hebrew. Keep all JSON keys, symbols, numbers, and action values in English. Use only standard ASCII quotes in the JSON structure.

Your job: Analyze each stock using the pre-processed signals below and produce a structured JSON recommendation.
The signals were extracted from Finnhub (analyst consensus, earnings surprises, insider trades),
Finviz (short interest, RSI, debt), and SEC Edgar (actual 10-Q filings).

============================
PORTFOLIO TOTALS
============================
{json.dumps(portfolio_totals, indent=2)}

============================
US STOCKS — FULL SIGNAL ANALYSIS
============================
{''.join(us_analysis_blocks)}

============================
ISRAELI STOCKS (prices in ILS)
============================
{json.dumps(il_summary, indent=2)}

============================
ISRAELI FUNDS
============================
{json.dumps(funds_summary, indent=2)}

============================
HIDDEN GEMS CANDIDATES — AI Infrastructure (from Finviz + Finnhub)
============================
Each row: Symbol | Name | Sector | Price | MCap | P/E | Analysts(B/Total) | LastEPS Surprise | Insider Buys | Insider Sells
{gems_context}

============================
RECENT RECOMMENDATIONS HISTORY (do NOT repeat these)
============================
{history_text}
IMPORTANT: Do not recommend the same gem or wildcard that appeared in the last 7 days above.
Pick different stocks to provide variety.

============================
WILDCARD CANDIDATES — Space & Quantum Computing
============================
One wildcard pick per report. Choose the most compelling from:
{wildcard_context}

============================
YOUR TASK
============================
For each US stock:
1. Read the bullish signals and warning signals carefully
2. Read the SEC filing excerpt — find revenue trends, profitability, debt changes, guidance
3. Combine everything into ONE clear verdict
4. Set confidence: HIGH (3+ signals agree), MEDIUM (mixed), LOW (conflicting)
5. Give specific entry, stop loss, support, resistance based on price range

For Israeli stocks: analyze based on price action and news. Note these are ILS prices.
For funds: analyze the index they track, not the fund itself.
For hidden gems: pick {HIDDEN_GEMS_COUNT} from the AI Infrastructure candidates above.
- Prefer stocks with: analyst buys > 50% of total, positive EPS surprise, insider buying
- Avoid stocks with heavy insider selling or zero analyst coverage
- Explain WHY each one specifically based on the data

For wildcard: pick exactly 1 from the Space & Quantum candidates.
- Pick the one with best momentum + analyst support
- Explain the specific thesis: why space/quantum NOW

Return ONLY valid JSON, no markdown:
{{
  "market_summary": "4 sentences on S&P500, Nasdaq, macro, rates today",
  "yesterday_recap": "What moved yesterday and why",
  "rumors_and_contracts": "Key rumors, contracts, sector news",
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
      "analyst_target_explanation": "10 of 11 analysts rate BUY",
      "upside_to_target_pct": 26.0,
      "earnings_date": "2026-08-01",
      "earnings_expectations": "Expected EPS $0.44, beat 3 of last 4 quarters",
      "key_signals": ["Beat EPS 3 of 4 quarters", "10/11 analysts BUY", "Insider selling $16M — watch"],
      "sec_insight": "One sentence from reading the actual 10-Q filing",
      "support_levels": "$17.50, $16.80",
      "resistance_levels": "$21.00, $24.67",
      "entry_point": "Add at $17.50",
      "stop_loss": "$15.50",
      "position_advice": "Hold current. Add only on pullback to support.",
      "reasoning": "2 sentences synthesizing all signals into final verdict."
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
      "position_advice": "Hold. Wait for break above ₪200 before adding.",
      "reasoning": "2 sentences."
    }}
  ],
  "funds_analysis": [
    {{
      "name": "ממ SP500 הראל",
      "tracks": "S&P 500",
      "original_value": 45402,
      "index_change_pct": 0.97,
      "recommendation": "HOLD",
      "index_analysis": "2 sentences about S&P 500 index specifically."
    }}
  ],
  "hidden_gems": [
    {{
      "symbol": "TICKER",
      "name": "Company Name",
      "sector": "Sector",
      "current_price": 0.0,
      "gain_6mo_pct": 0.0,
      "earnings_date": "",
      "why_interesting": "2 sentences — specific reason based on screener + Finnhub data",
      "ai_infrastructure_angle": "Specific connection to AI buildout",
      "catalyst": "Concrete upcoming catalyst",
      "risk": "Main risk factor"
    }}
  ],
  "wildcard": {{
    "symbol": "TICKER",
    "name": "Company Name",
    "sector": "Space / Quantum Computing",
    "current_price": 0.0,
    "why_interesting": "2 sentences — why this space or quantum stock NOW",
    "thesis": "The specific investment thesis",
    "catalyst": "Upcoming catalyst",
    "risk": "Main risk"
  }}
}}"""

    print("שולח ל-Claude לניתוח...")
    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text
    # נקה markdown אם יש
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    # חלץ JSON גולמי אם עדיין לא תקין
    if not raw.strip().startswith("{"):
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]

    print("✅ ניתוח הושלם")
    try:
        analysis = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        print(f"  [Agent] JSON parse error: {e}")
        print(f"  [Agent] raw (first 500): {raw[:500]}")
        # fallback — תחזיר מבנה ריק עם הנתונים שיש
        analysis = {
            "market_summary": "Data unavailable — JSON parse error",
            "yesterday_recap": "",
            "rumors_and_contracts": "",
            "us_recommendations": [],
            "il_recommendations": [],
            "funds_analysis": [],
            "hidden_gems": [],
            "wildcard": None,
        }
    analysis["portfolio_totals"] = portfolio_totals

    # מזג נתוני תיק מ-us_summary לתוך us_recommendations
    us_summary_map = {s["symbol"]: s for s in us_summary}
    for r in analysis.get("us_recommendations", []):
        sym = r.get("symbol", "")
        if sym in us_summary_map:
            s = us_summary_map[sym]
            # תמיד עדכן מהנתונים האמיתיים — אל תסמוך על Claude לשדות מספריים
            for field in ("shares", "current_price", "current_value",
                          "original_value", "pnl_dollars", "pnl_pct", "daily_change_pct"):
                if not r.get(field) and s.get(field):
                    r[field] = s[field]

    # fallback — אם Claude לא החזיר מניות, בנה כרטיסיות בסיסיות מהנתונים
    if not analysis.get("us_recommendations"):
        print("  [Agent] us_recommendations empty — building fallback cards")
        analysis["us_recommendations"] = [
            {
                "symbol": s["symbol"],
                "name": s["name"],
                "action": "HOLD",
                "confidence": "LOW",
                "current_price": s["current_price"],
                "avg_cost": s["avg_cost"],
                "current_value": s["current_value"],
                "original_value": s["original_value"],
                "pnl_dollars": s["pnl_dollars"],
                "pnl_pct": s["pnl_pct"],
                "daily_change_pct": s.get("daily_change_pct", 0),
                "analyst_target": s.get("analyst_target"),
                "upside_to_target_pct": s.get("upside_to_target_pct"),
                "key_signals": [],
                "reasoning": "Analysis unavailable — data fetched successfully",
                "position_advice": "",
                "support_levels": "", "resistance_levels": "",
                "entry_point": "", "stop_loss": "",
                "earnings_date": s.get("earnings_date", ""),
                "earnings_expectations": "",
                "sec_insight": "",
            }
            for s in us_summary
        ]

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

    # שמור היסטוריה למחר
    try:
        from history import save_recommendations
        save_recommendations(
            gems=analysis.get("hidden_gems", []),
            wildcard=analysis.get("wildcard")
        )
    except Exception as e:
        print(f"  [History] could not save: {e}")

    # מעבר אחרון — וודא שכל מחירי US הם אמיתיים (לא 0 מ-Claude)
    us_summary_map2 = {s["symbol"]: s for s in us_summary}
    for r in analysis.get("us_recommendations", []):
        sym = r.get("symbol", "")
        if sym in us_summary_map2:
            s = us_summary_map2[sym]
            for field in ("shares", "current_price", "current_value",
                          "original_value", "pnl_dollars", "pnl_pct",
                          "avg_cost", "daily_change_pct"):
                real_val = s.get(field)
                if real_val and not r.get(field):
                    r[field] = real_val
            # תמיד עדכן מחיר אם Claude שם 0
            if not r.get("current_price") and s.get("current_price"):
                r["current_price"] = s["current_price"]

    # שמור ניתוח לדשבורד
    try:
        analysis_path = os.path.join(os.path.dirname(__file__), "last_analysis.json")
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        print("  [Dashboard] last_analysis.json נשמר")
    except Exception as e:
        print(f"  [Dashboard] שגיאה בשמירה: {e}")

    return analysis