import os
import sys
import io
import time
import socket
import logging
from datetime import datetime
from dotenv import load_dotenv

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import os as _os
_ENV_PATH = r"C:\Users\User\Documents\stock_agent\.env"
try:
    with open(_ENV_PATH, "r", encoding="utf-8-sig") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip()
                if _v:
                    _os.environ[_k] = _v
except Exception:
    load_dotenv()

from config import PORTFOLIO_US, PORTFOLIO_IL, FUNDS_IL
from data_fetcher import collect_all_data
from agent import analyze_portfolio
from email_sender import send_email

logging.basicConfig(
    filename="stock_agent.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def wait_for_network(timeout=90):
    start = time.time()
    while time.time() - start < timeout:
        try:
            socket.setdefaulttimeout(5)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("8.8.8.8", 53))
            s.close()
            return True
        except Exception:
            time.sleep(5)
    return False

def already_ran_today():
    flag_file = "last_run.txt"
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today:
                return True
    return False

def mark_ran_today():
    with open("last_run.txt", "w") as f:
        f.write(datetime.now().strftime("%Y-%m-%d"))

def main():
    logging.info("Stock Agent started")

    if already_ran_today():
        logging.info("Already ran today — skipping")
        print("כבר רץ היום — לא שולח שוב.")
        return

    print("ממתין לרשת...")
    if not wait_for_network(timeout=600):
        logging.error("Network unavailable after 90s — aborting without marking as ran")
        print("אין רשת — ננסה בפעם הבאה")
        return

    logging.info("Network ready, starting pipeline")
    print("\n" + "="*40)
    print("Stock Agent מתחיל...")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*40 + "\n")

    try:
        market_data = collect_all_data(
            us_symbols=list(PORTFOLIO_US.keys()),
            portfolio_il=PORTFOLIO_IL,
            funds_il=FUNDS_IL
        )

        analysis = analyze_portfolio(market_data)

        print("\nשולח מייל...")
        success = send_email(analysis)

        if success:
            mark_ran_today()
            logging.info("Email sent successfully — marked as ran")
            print("\nהסוכן סיים!")
        else:
            logging.error("send_email returned False — will retry next trigger")
            print("\nשליחת המייל נכשלה — ננסה בפעם הבאה")

    except Exception as e:
        logging.exception(f"Agent crashed: {e}")
        print(f"\nשגיאה: {e}")
        raise

if __name__ == "__main__":
    main()
