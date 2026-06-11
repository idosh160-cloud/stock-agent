"""
swing_trader.py — מסחר תנודתי חכם עם Claude
כל שעה: Claude בוחר מטבעות לסיבובים קצרים ($15 לכל עסקה)
כל 15 דק': בודק פוזיציות פתוחות — מוכר ב-+5% או עוצר ב-3%-
"""
import os
import json
import logging
import requests
from datetime import datetime

DIR        = os.path.dirname(os.path.abspath(__file__))
SWING_FILE = os.path.join(DIR, "swing_trades.json")

SWING_USD       = 15     # דולר לכל עסקה
TARGET_PCT      = 0.05   # +5% יעד רווח
STOP_PCT        = 0.03   # -3% עצור הפסד
MAX_OPEN        = 3      # פוזיציות פתוחות מקסימום
MAX_BUDGET      = 60     # תקציב מקסימלי לסינגים

# Pairs שאומתו ב-Kraken + מינימום נפח + דיוק מחיר
CANDIDATES = {
    "SOL":  {"pair": "SOLUSDC",  "min_vol": 0.06,  "price_dec": 2},
    "ADA":  {"pair": "ADAUSDC",  "min_vol": 20,    "price_dec": 6},
    "AVAX": {"pair": "AVAXUSDC", "min_vol": 0.5,   "price_dec": 3},
    "LINK": {"pair": "LINKUSDC", "min_vol": 0.55,  "price_dec": 5},
    "DOT":  {"pair": "DOTUSDC",  "min_vol": 3.9,   "price_dec": 4},
    "LTC":  {"pair": "LTCUSDC",  "min_vol": 0.1,   "price_dec": 3},
    "BCH":  {"pair": "BCHUSDC",  "min_vol": 0.01,  "price_dec": 2},
    "ALGO": {"pair": "ALGOUSDC", "min_vol": 41,    "price_dec": 5},
    "ATOM": {"pair": "ATOMUSDC", "min_vol": 2.5,   "price_dec": 4},
    "XTZ":  {"pair": "XTZUSDC",  "min_vol": 13,    "price_dec": 5},
}


# ── File helpers ──────────────────────────────────────────────────────────

def load_swing_trades() -> list:
    if os.path.exists(SWING_FILE):
        try:
            with open(SWING_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_swing_trades(trades: list):
    with open(SWING_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)


# ── Market data ───────────────────────────────────────────────────────────

def get_candidate_data() -> list:
    """מחזיר רשימת מטבעות עם נתוני שוק, ממוין לפי תנודתיות"""
    pair_str = ",".join(c["pair"] for c in CANDIDATES.values())
    try:
        r = requests.get(
            f"https://api.kraken.com/0/public/Ticker?pair={pair_str}",
            timeout=10
        )
        result = r.json().get("result", {})
    except Exception as e:
        logging.error(f"[Swing] ticker fetch failed: {e}")
        return []

    out = []
    for coin, cfg in CANDIDATES.items():
        t = result.get(cfg["pair"])
        if not t:
            continue
        price  = float(t["c"][0])
        open_p = float(t["o"])
        high   = float(t["h"][1])
        low    = float(t["l"][1])
        vol    = float(t["v"][1])
        if open_p == 0 or price == 0:
            continue
        chg   = round((price - open_p) / open_p * 100, 2)
        rng   = round((high - low) / low * 100, 2) if low else 0
        out.append({
            "coin": coin, "pair": cfg["pair"],
            "price": price, "price_dec": cfg["price_dec"],
            "min_vol": cfg["min_vol"],
            "change_24h": chg, "range_24h": rng,
            "high_24h": high, "low_24h": low,
            "volume_usdc": round(vol * price, 0),
        })

    out.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    return out


def get_current_price(pair: str) -> float:
    try:
        r = requests.get(
            f"https://api.kraken.com/0/public/Ticker?pair={pair}",
            timeout=5
        )
        t = r.json().get("result", {}).get(pair, {})
        return float(t["c"][0]) if t else 0
    except Exception:
        return 0


# ── Claude analysis ───────────────────────────────────────────────────────

def _load_api_key():
    env_path = os.path.join(DIR, ".env")
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == "ANTHROPIC_API_KEY" and v.strip():
                        os.environ["ANTHROPIC_API_KEY"] = v.strip()
    except Exception:
        pass

def analyze_with_claude(candidates: list, open_coins: set, usdc: float, btc_price: float) -> dict:
    _load_api_key()
    import anthropic

    rows = "\n".join([
        f"  {c['coin']}: ${c['price']:.4f} | {c['change_24h']:+.1f}% | "
        f"range {c['range_24h']:.1f}% | vol ${c['volume_usdc']:,.0f} | "
        f"H=${c['high_24h']:.4f} L=${c['low_24h']:.4f}"
        for c in candidates[:15]
    ])
    skip = ", ".join(open_coins) if open_coins else "none"

    prompt = f"""You are an expert crypto swing trader. {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC.

BTC context price: ${btc_price:,.0f}
Available USDC: ${usdc:.2f} | Trade size: $15 each
Take-profit: +5% | Stop-loss: -3%
Already open positions (skip): {skip}

Altcoin candidates ranked by 24h movement:
{rows}

Your job: Think carefully and pick 0, 1, or 2 coins for a swing trade RIGHT NOW.
Criteria to look for:
- Strong momentum with room to continue (not exhausted)
- Coins near intraday low that may bounce (dip buy)
- Volume confirming the move
- Clear entry with defined risk

Criteria to avoid:
- Coins that already ran 10%+ and look extended
- Very low volume (under $50k/day)
- Choppy sideways movement

Return ONLY valid JSON:
{{
  "picks": [
    {{
      "coin": "SOL",
      "confidence": "HIGH",
      "reasoning": "שתי משפטים בעברית — מה בדיוק אתה רואה ולמה עכשיו"
    }}
  ],
  "market_read": "משפט אחד בעברית על מצב השוק הכללי כרגע",
  "skip_reason": "למה דחית את השאר (משפט אחד בעברית)"
}}

If nothing looks good — return picks as empty array. Better to miss a trade than to lose money."""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    raw = part
                    break
        return json.loads(raw)
    except Exception as e:
        logging.error(f"[Swing] Claude error: {e}")
        return {"picks": [], "market_read": "", "skip_reason": str(e)}


# ── Main cycles ───────────────────────────────────────────────────────────

def check_open_swings(balance: dict, request_fn) -> list:
    """נקרא כל 15 דקות — בודק אם פוזיציות פתוחות הגיעו ליעד/stop"""
    trades  = load_swing_trades()
    changed = False

    for t in trades:
        if t.get("status") != "open":
            continue

        coin  = t["coin"]
        pair  = t["pair"]
        entry = t["entry_price"]
        vol   = t["volume"]

        current = get_current_price(pair)
        if current == 0:
            continue

        pnl_pct = (current - entry) / entry * 100
        t["current_price"] = round(current, 6)
        t["pnl_pct"]       = round(pnl_pct, 2)
        t["pnl_usd"]       = round((current - entry) * vol, 2)
        changed = True

        reason = None
        if current >= t["target_price"]:
            reason = "profit"
        elif current <= t["stop_price"]:
            reason = "loss"

        if reason:
            holding = float(balance.get(coin, 0))
            sell_vol = min(vol, holding)
            cfg = CANDIDATES.get(coin, {})
            if sell_vol < cfg.get("min_vol", 0.01):
                logging.warning(f"[Swing] {coin} holding {holding} below min — cannot sell")
                continue
            price_dec = cfg.get("price_dec", 4)
            lp = round(current * (1.001 if reason == "profit" else 0.999), price_dec)
            try:
                res  = request_fn("/0/private/AddOrder", {
                    "pair": pair, "type": "sell", "ordertype": "limit",
                    "volume": f"{sell_vol:.8f}", "price": f"{lp:.{price_dec}f}",
                }, private=True)
                txid = list(res.get("txid", ["?"]))[0]
                t["status"]     = f"closed_{reason}"
                t["date_close"] = datetime.now().isoformat()
                t["close_price"]= current
                t["close_txid"] = txid
                logging.info(f"[Swing] CLOSE {reason.upper()} {coin} @ {current:.4f} | P&L {pnl_pct:+.1f}% | txid={txid}")
            except Exception as e:
                logging.error(f"[Swing] sell failed {coin}: {e}")

    if changed:
        save_swing_trades(trades)
    return trades


def run_swing_scan(balance: dict, usdc: float, request_fn, btc_price: float = 0) -> list:
    """נקרא כל שעה — Claude סורק ובוחר מועמדים"""
    trades      = load_swing_trades()
    open_swings = [t for t in trades if t.get("status") == "open"]
    open_coins  = {t["coin"] for t in open_swings}
    open_budget = sum(t.get("usd", 0) for t in open_swings)

    if len(open_swings) >= MAX_OPEN:
        logging.info(f"[Swing] {MAX_OPEN} positions open — skipping scan")
        return trades
    if open_budget >= MAX_BUDGET:
        logging.info(f"[Swing] Budget ${MAX_BUDGET} reached — skipping scan")
        return trades
    if usdc < SWING_USD + 5:
        logging.info(f"[Swing] Low USDC ${usdc:.2f} — skipping scan")
        return trades

    candidates = get_candidate_data()
    if not candidates:
        logging.warning("[Swing] No candidate data available")
        return trades

    analysis   = analyze_with_claude(candidates, open_coins, usdc, btc_price)
    market_read = analysis.get("market_read", "")
    skip_reason = analysis.get("skip_reason", "")
    logging.info(f"[Swing] Claude: {market_read} | skipped: {skip_reason}")

    slots = MAX_OPEN - len(open_swings)
    for pick in analysis.get("picks", [])[:slots]:
        coin   = pick.get("coin", "")
        reason = pick.get("reasoning", "")
        conf   = pick.get("confidence", "MEDIUM")

        if coin in open_coins or coin not in CANDIDATES:
            continue

        cfg       = CANDIDATES[coin]
        pair      = cfg["pair"]
        price_dec = cfg["price_dec"]
        min_v     = cfg["min_vol"]

        coin_data = next((c for c in candidates if c["coin"] == coin), None)
        if not coin_data:
            continue

        price = coin_data["price"]
        vol   = round(SWING_USD / price, 8)

        if vol < min_v:
            logging.warning(f"[Swing] {coin} vol={vol:.6f} < min={min_v} — skip")
            continue

        lp = round(price * 0.999, price_dec)
        try:
            res  = request_fn("/0/private/AddOrder", {
                "pair": pair, "type": "buy", "ordertype": "limit",
                "volume": f"{vol:.8f}", "price": f"{lp:.{price_dec}f}",
            }, private=True)
            txid = list(res.get("txid", ["?"]))[0]

            trade = {
                "coin":          coin,
                "pair":          pair,
                "entry_price":   price,
                "limit_price":   lp,
                "volume":        vol,
                "usd":           round(vol * price, 2),
                "target_price":  round(price * (1 + TARGET_PCT), price_dec),
                "stop_price":    round(price * (1 - STOP_PCT),   price_dec),
                "date_open":     datetime.now().isoformat(),
                "date_close":    None,
                "status":        "open",
                "confidence":    conf,
                "reasoning":     reason,
                "market_read":   market_read,
                "current_price": price,
                "pnl_pct":       0.0,
                "pnl_usd":       0.0,
                "txid":          txid,
                "close_price":   None,
                "close_txid":    None,
            }
            trades.append(trade)
            open_coins.add(coin)
            logging.info(f"[Swing] OPEN {coin} @ {price:.4f} target={trade['target_price']} stop={trade['stop_price']} | {reason[:80]}")
        except Exception as e:
            logging.error(f"[Swing] buy failed {coin}: {e}")

    save_swing_trades(trades)
    return trades
