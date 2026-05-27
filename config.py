# config.py - תיק המניות שלך

PORTFOLIO_US = {
    "BW":   {"name": "Babcock & Wilcox",       "shares": 117, "avg_cost": 14.81},
    "FPS":  {"name": "Forgent Power Solutions", "shares": 60,  "avg_cost": 41.70},
    "IREN": {"name": "Iris Energy",             "shares": 28,  "avg_cost": 58.94},
    "CIFR": {"name": "Cipher Mining",           "shares": 138, "avg_cost": 16.03},
    "DRAM": {"name": "Roundhill Memory ETF",    "shares": 67,  "avg_cost": 51.97},
}

# מחירי קנייה בשקלים (לא אגורות!)
PORTFOLIO_IL = {
    "DSIT.TA":  {"name": "דיאסאייטי",          "shares": 330, "avg_cost": 21.20},
    "TASE.TA":  {"name": "הבורסה לניירות ערך", "shares": 192, "avg_cost": 119.07},
    "PHOE.TA":  {"name": "הפניקס",             "shares": 53,  "avg_cost": 188.60},
}

# מחירי קנייה בשקלים (לא אגורות!)
FUNDS_IL = {
    "SP500_HAREL":  {"name": "ממ SP500 הראל",    "shares": 18559, "avg_cost": 2.4469,  "tracks": "S&P 500",             "tracks_symbol": "^GSPC"},
    "NDX100_TKLIT": {"name": "ממ NDX100 תכלית",  "shares": 8280,  "avg_cost": 4.9749,  "tracks": "Nasdaq 100",          "tracks_symbol": "^NDX"},
    "TABIT_TKLIT":  {"name": "תכלית ת\"א ביטוח", "shares": 6043,  "avg_cost": 3.3354,  "tracks": "TA Insurance & Finance", "tracks_symbol": "^TA35.TA"},
    "TA125_MTF":    {"name": "MTF 125 כשתא",     "shares": 379,   "avg_cost": 52.626,  "tracks": "TA-125 Index",        "tracks_symbol": "^TA125.TA"},
}

RISK_PROFILE = "moderate"
HIDDEN_GEMS_COUNT = 3