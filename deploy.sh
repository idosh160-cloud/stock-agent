#!/bin/bash
# deploy.sh - הגדרת הבוט על שרת לינוקס (Hetzner CX23)
# הרץ פעם אחת בלבד עם: bash deploy.sh

set -e

echo "=== Stock/Crypto Bot Deploy Script ==="

# 1. עדכון חבילות
sudo apt update && sudo apt upgrade -y

# 2. התקנת Python ו-pip
sudo apt install -y python3 python3-pip python3-venv git

# 3. שיבוט הקוד מ-GitHub
REPO_URL="https://github.com/idosh160-cloud/stock-agent.git"
APP_DIR="$HOME/stock_agent"

if [ -d "$APP_DIR" ]; then
    echo "תיקייה קיימת - מעדכן..."
    cd "$APP_DIR" && git pull
else
    echo "מוריד קוד מ-GitHub..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 4. יצירת virtual environment
python3 -m venv venv
source venv/bin/activate

# 5. התקנת תלויות
pip install --upgrade pip
pip install -r requirements.txt

# 6. יצירת קובץ .env (יש להשלים מפתחות!)
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << 'ENVFILE'
KRAKEN_API_KEY=YOUR_KRAKEN_API_KEY_HERE
KRAKEN_PRIVATE_KEY=YOUR_KRAKEN_PRIVATE_KEY_HERE
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY_HERE
FINNHUB_API_KEY=YOUR_FINNHUB_API_KEY_HERE
EMAIL_ADDRESS=idosh160@gmail.com
EMAIL_PASSWORD=YOUR_EMAIL_PASSWORD_HERE
ENVFILE
    echo ""
    echo "!!! חשוב: ערוך את $APP_DIR/.env והכנס את המפתחות האמיתיים !!!"
    echo "    nano $APP_DIR/.env"
    echo ""
fi

# 7. הגדרת cron jobs
CRON_USER=$(whoami)
PYTHON_BIN="$APP_DIR/venv/bin/python3"
LOG_DIR="$APP_DIR/logs"
mkdir -p "$LOG_DIR"

# הסרת crons ישנים של הבוט
crontab -l 2>/dev/null | grep -v "stock_agent\|kraken_bot\|swing_trader\|crypto_agent" | crontab - 2>/dev/null || true

# הוספת crons חדשים
(crontab -l 2>/dev/null; cat << CRONEOF
# Crypto agent - כל שעה
0 * * * * cd $APP_DIR && $PYTHON_BIN crypto_agent.py >> $LOG_DIR/crypto.log 2>&1

# Swing trader - כל 4 שעות
0 */4 * * * cd $APP_DIR && $PYTHON_BIN swing_trader.py >> $LOG_DIR/swing.log 2>&1

# Kraken bot (daily analysis) - כל יום ב-8 בבוקר
0 8 * * * cd $APP_DIR && $PYTHON_BIN kraken_bot.py >> $LOG_DIR/kraken.log 2>&1

# Git push אוטומטי - כל לילה ב-3
0 3 * * * cd $APP_DIR && git add -A && git commit -m "auto: daily update \$(date +%Y-%m-%d)" && git push >> $LOG_DIR/git.log 2>&1
CRONEOF
) | crontab -

echo ""
echo "=== Cron jobs הוגדרו ==="
crontab -l

echo ""
echo "=== Deploy הסתיים! ==="
echo ""
echo "צעדים הבאים:"
echo "1. ערוך .env:  nano $APP_DIR/.env"
echo "2. הגדר git push:  git config credential.helper store"
echo "3. בדוק crons:  crontab -l"
echo "4. הרץ בדיקה:  cd $APP_DIR && source venv/bin/activate && python3 crypto_agent.py"
