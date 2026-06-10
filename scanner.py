# scanner.py — סורק שוק שעתי
# מוצא הזדמנויות קשורות לאפיקי התיק, מדרג, ושולח ל-Claude להחלטה

import os
import json
import time
import math
from datetime import datetime

import yfinance as yf
from finviz.screener import Screener
import finviz

# ── אפיקי השקעה — קשורים לתיק ─────────────────────────────────────────
THEMES = {
    "Bitcoin Mining & Crypto": [
        "MARA", "RIOT", "CLSK", "HUT", "BITF", "CORZ", "WULF", "IREN", "CIFR"
    ],
    "AI Infrastructure & Chips": [
        "NVDA", "AMD", "SMCI", "ANET", "MRVL", "AVGO", "ARM", "FORM", "LSCC"
    ],
    "Memory & Semiconductors": [
        "MU", "LRCX", "AMAT", "KLAC", "ONTO", "WOLF", "ACLS"
    ],
    "Energy for AI (Power)": [
        "VST", "CEG", "NRG", "ETN", "POWL", "GTLS", "GEV"
    ],
    "AI Software & Data": [
        "PLTR", "AI", "BBAI", "SOUN", "GFAI", "KULR"
    ],
}

SCAN_FILE = os.path.join(os.path.dirname(__file__), "scan_results.json")
ENV_PATH  = r"C:\Users\User\Documents\stock_agent\.env"


def _load_env():
    try:
        with open(ENV_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if v:
                        os.environ[k] = v
    except Exception:
        pass


def safe_float(v, default=0.0):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def get_finviz_data(symbol):
    """שולף נתוני Finviz למניה"""
    try:
        d = finviz.get_stock(symbol)
        return {
            "price":       safe_float(d.get("Price")),
            "rsi":         safe_float(d.get("RSI (14)")),
            "forward_pe":  safe_float(d.get("Forward P/E")),
            "perf_week":   safe_float(str(d.get("Perf Week","0")).replace("%","")),
            "perf_month":  safe_float(str(d.get("Perf Month","0")).replace("%","")),
            "w52_high":    safe_float(str(d.get("52W High","0")).replace("%","")),
            "w52_low":     safe_float(str(d.get("52W Low","0")).replace("%","")),
            "short_float": safe_float(str(d.get("Short Float","0")).replace("%","")),
            "market_cap":  d.get("Market Cap", ""),
            "analyst_recom": safe_float(d.get("Recom", "3")),
            "volume_rel":  safe_float(d.get("Rel Volume")),
            "sector":      d.get("Sector", ""),
            "industry":    d.get("Industry", ""),
            "name":        d.get("Company", symbol),
            "eps_next_y":  safe_float(str(d.get("EPS next Y","0")).replace("%","")),
        }
    except Exception:
        return None


def score_opportunity(d, portfolio_symbols):
    """
    מחשב ציון הזדמנות 0-100.
    גבוה = זול + מומנטום חיובי + אנליסטים בעד
    """
    score = 50  # ניטרלי

    # RSI — oversold = הזדמנות
    rsi = d.get("rsi", 50)
    if rsi < 35:
        score += 20
    elif rsi < 45:
        score += 10
    elif rsi > 70:
        score -= 15

    # מרחק מ-52w high — ככל שרחוק יותר = זול יותר
    w52h = d.get("w52_high", 0)
    if w52h < -30:
        score += 15
    elif w52h < -20:
        score += 10
    elif w52h < -10:
        score += 5
    elif w52h > -5:
        score -= 10  # קרוב לשיא = יקר

    # המלצת אנליסטים (1=Strong Buy, 5=Strong Sell)
    recom = d.get("analyst_recom", 3)
    if recom <= 1.5:
        score += 15
    elif recom <= 2.0:
        score += 10
    elif recom >= 4.0:
        score -= 15

    # Forward P/E
    fpe = d.get("forward_pe", 0)
    if 0 < fpe < 15:
        score += 10
    elif 15 <= fpe < 25:
        score += 5
    elif fpe > 50:
        score -= 10

    # מניה שכבר בתיק — מוריד עדיפות (כבר יש לנו חשיפה)
    if d.get("symbol") in portfolio_symbols:
        score -= 20

    # נפח חריג — עניין של שוק
    if d.get("volume_rel", 1) > 2:
        score += 5

    return max(0, min(100, score))


def scan_market():
    """סורק את כל האפיקים ומחזיר Top candidates"""
    from config import PORTFOLIO_US
    portfolio_symbols = set(PORTFOLIO_US.keys())

    print(f"[Scanner] {datetime.now().strftime('%H:%M')} — סורק שוק...")
    all_candidates = []
    seen = set()

    for theme, symbols in THEMES.items():
        for sym in symbols:
            if sym in seen:
                continue
            seen.add(sym)
            try:
                d = get_finviz_data(sym)
                if d is None or d["price"] == 0:
                    continue
                d["symbol"] = sym
                d["theme"]  = theme
                d["score"]  = score_opportunity(d, portfolio_symbols)
                all_candidates.append(d)
                time.sleep(0.3)
            except Exception as e:
                print(f"  [Scanner] {sym}: {e}")

    # מיין לפי ציון — Top 10
    all_candidates.sort(key=lambda x: x["score"], reverse=True)
    top = all_candidates[:10]

    print(f"[Scanner] נמצאו {len(all_candidates)} מניות, Top 10 לניתוח Claude")
    return top


def analyze_with_claude(candidates):
    """Claude מחליט מהן ההזדמנויות האמיתיות וכמה לקנות"""
    _load_env()
    import anthropic
    from config import PORTFOLIO_US

    # חשב שווי תיק נוכחי לצורך sizing
    total_value = 0
    for sym, cfg in PORTFOLIO_US.items():
        try:
            t = yf.Ticker(sym)
            p = safe_float(t.info.get("currentPrice") or t.info.get("regularMarketPrice", 0))
            total_value += p * cfg["shares"]
        except Exception:
            total_value += cfg["avg_cost"] * cfg["shares"]

    # בנה context מקוצר
    candidates_text = "\n".join([
        f"  {c['symbol']} | {c['name']} | {c['theme']} | "
        f"Price:${c['price']:.2f} | RSI:{c['rsi']:.0f} | "
        f"52wHigh:{c['w52_high']:+.0f}% | FwdPE:{c['forward_pe']:.1f} | "
        f"Recom:{c['analyst_recom']:.1f} | Score:{c['score']}"
        for c in candidates
    ])

    portfolio_text = "\n".join([
        f"  {sym}: {cfg['shares']} shares @ ${cfg['avg_cost']:.2f}"
        for sym, cfg in PORTFOLIO_US.items()
    ])

    prompt = f"""You are a concise stock analyst. Today: {datetime.now().strftime('%Y-%m-%d %H:%M')}.

CURRENT PORTFOLIO (US):
{portfolio_text}
Total portfolio value: ~${total_value:,.0f}

SCAN RESULTS — Top candidates by opportunity score:
Symbol | Name | Theme | Price | RSI | 52wHigh% | FwdPE | Recom(1=buy,5=sell) | Score
{candidates_text}

TASK: From the candidates above, identify 2-3 genuine opportunities RIGHT NOW.
For each opportunity:
- Is it actually cheap or just falling for a reason?
- How much to buy? (suggest $ amount, max 10% of portfolio per position)
- What order type and price?
- One-line reason

Also flag 1-2 TRIM candidates from the portfolio if any look overextended.

Return ONLY valid JSON:
{{
  "scanned_at": "{datetime.now().isoformat()}",
  "portfolio_value": {round(total_value)},
  "opportunities": [
    {{
      "symbol": "TICKER",
      "name": "Name",
      "theme": "Theme",
      "action": "BUY",
      "current_price": 0.0,
      "suggested_amount_usd": 0,
      "order_type": "LIMIT",
      "limit_price": 0.0,
      "reason": "One sentence why NOW",
      "score": 0,
      "rsi": 0,
      "w52_high_pct": 0
    }}
  ],
  "trim_suggestions": [
    {{
      "symbol": "TICKER",
      "reason": "One sentence why to trim",
      "suggested_sell_pct": 25
    }}
  ],
  "scan_summary": "2 sentences on what the scan found"
}}"""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = msg.content[0].text
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    return json.loads(raw.strip())


def run_scan():
    """הרצה מלאה — סריקה + Claude + שמירה"""
    _load_env()
    try:
        candidates = scan_market()
        if not candidates:
            print("[Scanner] אין מועמדים")
            return

        print("[Scanner] שולח ל-Claude...")
        results = analyze_with_claude(candidates)
        results["all_candidates"] = candidates  # שמור גם את כל המועמדים לדשבורד

        with open(SCAN_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        n_opp  = len(results.get("opportunities", []))
        n_trim = len(results.get("trim_suggestions", []))
        print(f"[Scanner] ✅ {n_opp} הזדמנויות, {n_trim} המלצות קיצוץ — נשמר")
        return results

    except Exception as e:
        print(f"[Scanner] שגיאה: {e}")
        raise


if __name__ == "__main__":
    run_scan()
