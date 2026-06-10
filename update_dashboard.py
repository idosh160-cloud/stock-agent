# update_dashboard.py — מריץ ניתוח ודוחף last_analysis.json לגיטהאב
# בלי מייל, רק לדשבורד

import sys
import io
import os
import subprocess

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
    pass

from config import PORTFOLIO_US, PORTFOLIO_IL, FUNDS_IL
from data_fetcher import collect_all_data
from agent import analyze_portfolio

print("משיג נתונים...")
data = collect_all_data(
    us_symbols=list(PORTFOLIO_US.keys()),
    portfolio_il=PORTFOLIO_IL,
    funds_il=FUNDS_IL
)

print("מנתח...")
analysis = analyze_portfolio(data)

print("דוחף לגיטהאב...")
repo_dir = os.path.dirname(__file__)
subprocess.run(["git", "add", "last_analysis.json", "scan_results.json"], cwd=repo_dir)
subprocess.run(["git", "commit", "-m", "update: dashboard data"], cwd=repo_dir)
subprocess.run(["git", "push"], cwd=repo_dir)

print("הדשבורד עודכן!")
