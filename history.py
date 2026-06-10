# history.py — זיכרון קצר של המלצות קודמות (7 ימים אחרונים)

import json
import os
from datetime import datetime, timedelta

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "recommendations_history.json")
DAYS_TO_KEEP = 7


def _load():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(data):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_recommendations(gems: list, wildcard: dict):
    """שומר את המלצות היום"""
    history = _load()
    today = datetime.now().strftime("%Y-%m-%d")

    # מחק ערכים ישנים מעל 7 ימים
    cutoff = (datetime.now() - timedelta(days=DAYS_TO_KEEP)).strftime("%Y-%m-%d")
    history = [e for e in history if e.get("date", "") >= cutoff]

    # הסר ערך קיים של היום אם יש
    history = [e for e in history if e.get("date") != today]

    entry = {
        "date": today,
        "gems": [g.get("symbol", "") for g in gems if g.get("symbol")],
        "wildcard": wildcard.get("symbol", "") if wildcard else "",
    }
    history.append(entry)
    _save(history)


def get_recent_symbols(days=7):
    """מחזיר סמלים שהומלצו ב-N הימים האחרונים"""
    history = _load()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    symbols = set()
    for entry in history:
        if entry.get("date", "") >= cutoff:
            symbols.update(entry.get("gems", []))
            wc = entry.get("wildcard", "")
            if wc:
                symbols.add(wc)
    return symbols


def format_history_for_prompt():
    """טקסט לפרומפט — מה הומלץ לאחרונה"""
    history = _load()
    if not history:
        return "  (no previous recommendations)"

    lines = []
    for entry in sorted(history, key=lambda x: x.get("date", ""), reverse=True):
        gems_str = ", ".join(entry.get("gems", [])) or "none"
        wc = entry.get("wildcard", "") or "none"
        lines.append(f"  {entry['date']}: gems=[{gems_str}]  wildcard={wc}")
    return "\n".join(lines)
