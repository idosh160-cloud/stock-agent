# test_email.py — הרצת בדיקה מלאה ללא נעילת היום
# מריץ את כל הפייפליין ושולח מייל, בלי לגעת ב-last_run.txt

import sys
import io
import os

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# טעינת .env ידנית
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
    print("✅ .env נטען")
except Exception as e:
    print(f"⚠️ לא נטען .env: {e}")

from datetime import datetime
from config import PORTFOLIO_US, PORTFOLIO_IL, FUNDS_IL
from data_fetcher import collect_all_data
from agent import analyze_portfolio
from email_sender import send_email

print("\n" + "="*40)
print("TEST RUN — Stock Agent")
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("="*40 + "\n")

print("משיג נתונים...")
data = collect_all_data(
    us_symbols=list(PORTFOLIO_US.keys()),
    portfolio_il=PORTFOLIO_IL,
    funds_il=FUNDS_IL
)

print("\nשולח לקלוד לניתוח...")
analysis = analyze_portfolio(data)

print("\nשולח מייל בדיקה...")
ok = send_email(analysis)

if ok:
    print("\n✅ מייל בדיקה נשלח בהצלחה!")
else:
    print("\n❌ שליחת המייל נכשלה — בדוק GMAIL_USER / GMAIL_APP_PASSWORD ב-.env")
