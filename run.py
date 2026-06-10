import os
import sys
import io
import time
import socket
import logging
import subprocess
from datetime import datetime
from dotenv import load_dotenv

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

_ENV_PATH = r"C:\Users\User\Documents\stock_agent\.env"
try:
    with open(_ENV_PATH, "r", encoding="utf-8-sig") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip()
                if _v:
                    os.environ[_k] = _v
except Exception:
    load_dotenv()

from config import PORTFOLIO_US, PORTFOLIO_IL, FUNDS_IL
from data_fetcher import collect_all_data
from agent import analyze_portfolio

logging.basicConfig(
    filename="stock_agent.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def wait_for_network(timeout=600):
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
    flag_file = os.path.join(os.path.dirname(__file__), "last_run.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today:
                return True
    return False

def mark_ran_today():
    flag_file = os.path.join(os.path.dirname(__file__), "last_run.txt")
    with open(flag_file, "w") as f:
        f.write(datetime.now().strftime("%Y-%m-%d"))

def push_to_github():
    repo_dir = os.path.dirname(__file__)
    try:
        subprocess.run(["git", "add", "last_analysis.json"], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", f"update: daily analysis {datetime.now().strftime('%Y-%m-%d')}"], cwd=repo_dir)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        logging.info("Dashboard updated on GitHub")
        print("דשבורד עודכן בגיטהאב")
    except Exception as e:
        logging.error(f"Git push failed: {e}")
        print(f"שגיאה בדחיפה לגיטהאב: {e}")

def main():
    logging.info("Stock Agent started")

    if already_ran_today():
        logging.info("Already ran today — skipping")
        print("כבר רץ היום.")
        return

    print("ממתין לרשת...")
    if not wait_for_network():
        logging.error("Network unavailable — aborting")
        print("אין רשת — ננסה בפעם הבאה")
        return

    logging.info("Network ready, starting pipeline")
    print("\n" + "="*40)
    print("Stock Agent מתחיל...")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*40 + "\n")

    try:
        print("משיג נתונים...")
        market_data = collect_all_data(
            us_symbols=list(PORTFOLIO_US.keys()),
            portfolio_il=PORTFOLIO_IL,
            funds_il=FUNDS_IL
        )

        print("מנתח...")
        analysis = analyze_portfolio(market_data)

        print("מעדכן דשבורד...")
        push_to_github()

        mark_ran_today()
        logging.info("Daily analysis complete — dashboard updated")
        print("\nהסוכן סיים!")

    except Exception as e:
        logging.exception(f"Agent crashed: {e}")
        print(f"\nשגיאה: {e}")
        raise

if __name__ == "__main__":
    main()
