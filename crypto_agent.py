import os
import sys
import io
import logging

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
import subprocess
from datetime import datetime, date


DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=os.path.join(DIR, "crypto_agent.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def pull_from_github():
    try:
        subprocess.run(["git", "pull", "--ff-only"], cwd=DIR, capture_output=True, timeout=30)
        logging.info("Git pull done")
    except Exception as e:
        logging.error(f"Git pull failed: {e}")


def push_to_github():
    try:
        for f in ["last_crypto.json", "crypto_trades.json", "crypto_params.json", "swing_trades.json", "swing_history.json"]:
            subprocess.run(["git", "add", f], cwd=DIR, capture_output=True)
        subprocess.run(["git", "add", "-f", "last_crypto.json"], cwd=DIR, capture_output=True)
        has_changes = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=DIR, capture_output=True
        ).returncode != 0
        if has_changes:
            subprocess.run(
                ["git", "commit", "-m", f"crypto: update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                cwd=DIR, capture_output=True
            )
            subprocess.run(["git", "push"], cwd=DIR, capture_output=True, timeout=30)
            logging.info("GitHub updated")
        else:
            logging.info("No changes to push")
    except Exception as e:
        logging.error(f"Git push failed: {e}")


def should_tune_params() -> bool:
    from kraken_bot import load_trades
    trades = load_trades()
    if len(trades) < 10:
        return False
    last_tune_file = os.path.join(DIR, "last_tune.txt")
    today = date.today().isoformat()
    if os.path.exists(last_tune_file):
        with open(last_tune_file) as f:
            if f.read().strip() == today:
                return False
    with open(last_tune_file, "w") as f:
        f.write(today)
    return True


def main():
    pull_from_github()
    logging.info("Crypto Agent cycle started")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Crypto Agent מתחיל...")

    try:
        from kraken_bot import run_cycle, tune_params, refresh_limit_orders, get_balance, _request
        from swing_trader import check_open_swings, run_swing_scan

        if should_tune_params():
            tune_params()
            logging.info("Params tuned")

        balance  = get_balance()
        now_hour = datetime.now().strftime("%Y-%m-%d %H")

        # רענן פקודות limit ברמות תמיכה — פעם בשעה
        limit_flag = os.path.join(DIR, "last_limit_refresh.txt")
        last_hour  = open(limit_flag).read().strip() if os.path.exists(limit_flag) else ""
        if last_hour != now_hour:
            try:
                refresh_limit_orders(balance)
                with open(limit_flag, "w") as f:
                    f.write(now_hour)
                logging.info("Limit orders refreshed")
            except Exception as e:
                logging.warning(f"Limit refresh failed: {e}")

        # ── ציקל מניות עיקרי (BTC/ETH/XRP) ─────────────────────────────
        state = run_cycle(auto_trade=True)
        usdc  = state["usdc"]
        btc_price = next((s["price"] for s in state["signals"] if s["coin"] == "BTC"), 0)

        # ── בדיקת swing פתוחות — כל 15 דק' ──────────────────────────────
        try:
            swing_trades = check_open_swings(balance, _request)
            open_swings  = [t for t in swing_trades if t.get("status") == "open"]
            logging.info(f"Swing check: {len(open_swings)} open positions")
        except Exception as e:
            logging.warning(f"Swing check failed: {e}")
            swing_trades = []

        # ── סריקת swing + רוטציה — תמיד רץ (קלוד מחליט אם לפתוח/לסגור) ──
        if usdc > 5:
            try:
                swing_trades = run_swing_scan(balance, usdc, _request, btc_price)
                logging.info("Swing scan completed")
            except Exception as e:
                logging.warning(f"Swing scan failed: {e}")

        # ── הדפס סיכום ──────────────────────────────────────────────────
        print(f"Portfolio: ${state['portfolio_usd']} | USDC: ${usdc:.2f}")
        for s in state["signals"]:
            icon = "BUY" if s["action"] == "BUY" else "SELL" if s["action"] == "SELL" else "hold"
            print(f"  {s['coin']} RSI={s['rsi']:.1f} ${s['price']:,.2f} → {icon}")

        open_sw = [t for t in swing_trades if t.get("status") == "open"]
        if open_sw:
            print(f"  Swings פתוחים: {len(open_sw)} — {', '.join(t['coin'] for t in open_sw)}")

        push_to_github()
        logging.info(f"Cycle complete. Portfolio=${state['portfolio_usd']} orders_today={state['orders_today']} swings={len(open_sw)}")

    except Exception as e:
        logging.exception(f"Crypto Agent crashed: {e}")
        print(f"שגיאה: {e}")


if __name__ == "__main__":
    main()
