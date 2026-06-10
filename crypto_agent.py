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


def push_to_github():
    try:
        subprocess.run(["git", "add", "last_crypto.json", "crypto_trades.json", "crypto_params.json"],
                       cwd=DIR, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=DIR, capture_output=True
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", f"crypto: update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                cwd=DIR, capture_output=True
            )
            subprocess.run(["git", "push"], cwd=DIR, capture_output=True)
            logging.info("GitHub updated")
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
    logging.info("Crypto Agent cycle started")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Crypto Agent מתחיל...")

    try:
        from kraken_bot import run_cycle, tune_params, refresh_limit_orders, get_balance

        if should_tune_params():
            tune_params()
            logging.info("Params tuned")

        # רענן פקודות limit ברמות תמיכה — פעם בשעה
        limit_flag = os.path.join(DIR, "last_limit_refresh.txt")
        now_hour   = datetime.now().strftime("%Y-%m-%d %H")
        last_hour  = open(limit_flag).read().strip() if os.path.exists(limit_flag) else ""
        if last_hour != now_hour:
            try:
                refresh_limit_orders(get_balance())
                with open(limit_flag, "w") as f:
                    f.write(now_hour)
                logging.info("Limit orders refreshed")
            except Exception as e:
                logging.warning(f"Limit refresh failed: {e}")

        state = run_cycle(auto_trade=True)

        orders = state.get("recent_trades", [])
        new_orders = [t for t in orders if t.get("date", "").startswith(date.today().isoformat())]

        print(f"Portfolio: ${state['portfolio_usd']} | USDC: ${state['usdc']}")
        for s in state["signals"]:
            icon = "BUY" if s["action"] == "BUY" else "SELL" if s["action"] == "SELL" else "hold"
            print(f"  {s['coin']} RSI={s['rsi']} ${s['price']:,.2f} → {icon}")

        if new_orders:
            print(f"  ** {len(new_orders)} עסקאות בוצעו היום **")
            push_to_github()
        else:
            push_to_github()

        logging.info(f"Cycle complete. Portfolio=${state['portfolio_usd']} orders_today={state['orders_today']}")

    except Exception as e:
        logging.exception(f"Crypto Agent crashed: {e}")
        print(f"שגיאה: {e}")


if __name__ == "__main__":
    main()
