"""
swing_trader.py — מסחר תנודתי חכם עם Claude
כל שעה: Claude בוחר מטבעות לסיבובים קצרים ($45 לכל עסקה, מינוף 2x)
כל 15 דק': בודק פוזיציות פתוחות — מוכר ב-+5% או עוצר ב-2%-
"""
import os
import json
import logging
import requests
from datetime import datetime

DIR        = os.path.dirname(os.path.abspath(__file__))
SWING_FILE = os.path.join(DIR, "swing_trades.json")

SWING_USD       = 100    # דולר לכל עסקה (collateral — שולטים ב-$200 עם מינוף 2x)
TARGET_PCT      = 0.05   # +5% יעד רווח
STOP_PCT        = 0.02   # -2% עצור הפסד (= ~4% על הון אמיתי עם מינוף)
MAX_OPEN        = 6      # פוזיציות פתוחות מקסימום
MAX_BUDGET      = 600    # תקציב מקסימלי לסווינגים
LEVERAGE        = 2      # מינוף x2 על כל קנייה (Kraken margin)

# מטבעות שקרקן מאפשר עליהם margin trading
MARGIN_ELIGIBLE = {"ETH", "SOL", "XRP", "LTC", "BCH", "LINK", "DOT", "ADA", "AVAX", "BNB", "DOGE", "XMR", "TON"}

# Pairs שאומתו ב-Kraken + מינימום נפח + דיוק מחיר
CANDIDATES = {
    "ETH":  {"pair": "ETHUSDC",  "min_vol": 0.004, "price_dec": 2},
    "SOL":  {"pair": "SOLUSDC",  "min_vol": 0.06,  "price_dec": 2},
    "XRP":  {"pair": "XRPUSDC",  "min_vol": 10,    "price_dec": 4},
    "ADA":  {"pair": "ADAUSDC",  "min_vol": 20,    "price_dec": 6},
    "AVAX": {"pair": "AVAXUSDC", "min_vol": 0.5,   "price_dec": 3},
    "LINK": {"pair": "LINKUSDC", "min_vol": 0.55,  "price_dec": 5},
    "DOT":  {"pair": "DOTUSDC",  "min_vol": 3.9,   "price_dec": 4},
    "LTC":  {"pair": "LTCUSDC",  "min_vol": 0.1,   "price_dec": 3},
    "BCH":  {"pair": "BCHUSDC",  "min_vol": 0.01,  "price_dec": 2},
    "ALGO": {"pair": "ALGOUSDC", "min_vol": 41,    "price_dec": 5},
    "ATOM": {"pair": "ATOMUSDC", "min_vol": 2.5,   "price_dec": 4},
    "XTZ":  {"pair": "XTZUSDC",  "min_vol": 13,    "price_dec": 5},
    "BNB":  {"pair": "BNBUSDC",  "min_vol": 0.07,  "price_dec": 2},
    "TON":  {"pair": "TONUSDC",  "min_vol": 3,     "price_dec": 4},
    "SHIB": {"pair": "SHIBUSDC", "min_vol": 500000,"price_dec": 8},
    "MANA": {"pair": "MANAUSDC", "min_vol": 20,    "price_dec": 5},
    "VET":  {"pair": "VETUSDC",  "min_vol": 100,   "price_dec": 6},
    "XMR":  {"pair": "XMRUSDC",  "min_vol": 0.05,  "price_dec": 2},
    "DOGE": {"pair": "XDGUSDC",  "min_vol": 50,    "price_dec": 5},
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
Available USDC: ${usdc:.2f} | Trade size: ${SWING_USD} each (2x leverage = controls ${SWING_USD*2})
Take-profit: +5% | Stop-loss: -2% (protects ~4% real capital with leverage)
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
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    raw = part
                    break
        # חתוך כל מה שאחרי ה-} האחרון
        last_brace = raw.rfind("}")
        if last_brace != -1:
            raw = raw[:last_brace+1]
        # נסה לתקן trailing commas נפוצות
        import re
        raw = re.sub(r",\s*}", "}", raw)
        raw = re.sub(r",\s*]", "]", raw)
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
            cfg       = CANDIDATES.get(coin, {})
            price_dec = cfg.get("price_dec", 4)

            if reason == "profit" and t.get("sell_txid"):
                # כבר יש limit sell פתוח — פשוט סמן כסגור
                t["status"]      = "closed_profit"
                t["date_close"]  = datetime.now().isoformat()
                t["close_price"] = current
                t["close_txid"]  = t["sell_txid"]
                logging.info(f"[Swing] CLOSE PROFIT {coin} @ {current:.4f} (limit already placed)")
            else:
                # stop-loss — בטל את ה-TP הפתוח ושים market sell
                if t.get("sell_txid"):
                    try:
                        request_fn("/0/private/CancelOrder", {"txid": t["sell_txid"]}, private=True)
                        logging.info(f"[Swing] Cancelled TP order {t['sell_txid']} for {coin}")
                    except Exception as ce:
                        logging.warning(f"[Swing] cancel TP failed: {ce}")

                holding  = float(balance.get(coin, 0))
                sell_vol = min(vol, holding)
                if sell_vol < cfg.get("min_vol", 0.01):
                    logging.warning(f"[Swing] {coin} holding {holding} below min — cannot sell")
                    continue
                lp = round(current * 0.999, price_dec)
                use_lev = coin in MARGIN_ELIGIBLE
                try:
                    stop_params = {
                        "pair": pair, "type": "sell", "ordertype": "limit",
                        "volume": f"{sell_vol:.8f}", "price": f"{lp:.{price_dec}f}",
                    }
                    if use_lev:
                        stop_params["leverage"] = str(LEVERAGE)
                    res  = request_fn("/0/private/AddOrder", stop_params, private=True)
                    txid = list(res.get("txid", ["?"]))[0]
                    t["status"]      = "closed_loss"
                    t["date_close"]  = datetime.now().isoformat()
                    t["close_price"] = current
                    t["close_txid"]  = txid
                    logging.info(f"[Swing] CLOSE STOP {coin} @ {current:.4f} | P&L {pnl_pct:+.1f}% | txid={txid}")
                except Exception as e:
                    logging.error(f"[Swing] stop sell failed {coin}: {e}")

    if changed:
        save_swing_trades(trades)
    return trades


def get_margin_used(request_fn) -> float:
    """מחזיר סה"כ margin בשימוש מ-Kraken (בדולרים)"""
    try:
        pos = request_fn("/0/private/OpenPositions", private=True)
        return sum(float(p.get("margin", 0)) for p in pos.values())
    except Exception:
        return 0.0

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
    if usdc < 10:
        logging.info(f"[Swing] USDC critically low ${usdc:.2f} — skipping scan")
        return trades

    # בדוק margin usage — אם מעל 80% מהתקרה, אל תנסה leverage
    margin_used = get_margin_used(request_fn)
    margin_headroom = max(0, 150 - margin_used)  # ~$150 תקרה לחשבון ~$600
    logging.info(f"[Swing] Margin used: ${margin_used:.0f} | headroom: ${margin_headroom:.0f}")

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

        buy_lp      = round(price * 0.999, price_dec)
        target_p    = round(price * (1 + TARGET_PCT), price_dec)
        stop_p      = round(price * (1 - STOP_PCT),   price_dec)
        try:
            # פקודת קנייה (מינוף רק למטבעות מאושרים)
            use_leverage = coin in MARGIN_ELIGIBLE
            buy_params = {
                "pair": pair, "type": "buy", "ordertype": "limit",
                "volume": f"{vol:.8f}", "price": f"{buy_lp:.{price_dec}f}",
            }
            if use_leverage:
                buy_params["leverage"] = str(LEVERAGE)
            try:
                res = request_fn("/0/private/AddOrder", buy_params, private=True)
            except Exception as margin_e:
                if "margin" in str(margin_e).lower() and use_leverage:
                    # מרג'ין מלא — נסה ללא מינוף
                    logging.warning(f"[Swing] Margin full for {coin}, retrying without leverage")
                    buy_params.pop("leverage", None)
                    use_leverage = False
                    res = request_fn("/0/private/AddOrder", buy_params, private=True)
                else:
                    raise
            txid = list(res.get("txid", ["?"]))[0]

            # פקודת מכירה ב-take-profit (מיד אחרי הקנייה)
            sell_txid = None
            try:
                sell_params = {
                    "pair": pair, "type": "sell", "ordertype": "limit",
                    "volume": f"{vol:.8f}", "price": f"{target_p:.{price_dec}f}",
                }
                if use_leverage:
                    sell_params["leverage"] = str(LEVERAGE)
                try:
                    sell_res = request_fn("/0/private/AddOrder", sell_params, private=True)
                except Exception as se2:
                    if "margin" in str(se2).lower():
                        sell_params.pop("leverage", None)
                        sell_res = request_fn("/0/private/AddOrder", sell_params, private=True)
                    else:
                        raise
                sell_txid = list(sell_res.get("txid", ["?"]))[0]
                logging.info(f"[Swing] SELL-TP placed {coin} @ {target_p} txid={sell_txid}")
            except Exception as se:
                logging.warning(f"[Swing] sell-tp failed {coin}: {se}")

            trade = {
                "coin":          coin,
                "pair":          pair,
                "entry_price":   price,
                "limit_price":   buy_lp,
                "volume":        vol,
                "usd":           round(vol * price, 2),
                "target_price":  target_p,
                "stop_price":    stop_p,
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
                "sell_txid":     sell_txid,
                "close_price":   None,
                "close_txid":    None,
            }
            trades.append(trade)
            open_coins.add(coin)
            logging.info(f"[Swing] OPEN {coin} @ {price:.4f} target={target_p} stop={stop_p} | {reason[:80]}")
        except Exception as e:
            logging.error(f"[Swing] buy failed {coin}: {e}")

    save_swing_trades(trades)
    return trades
