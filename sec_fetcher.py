# sec_fetcher.py - נתונים מ-SEC Edgar (ממשלתי, חינמי, ללא הרשמה)

import requests
import time
from datetime import datetime

HEADERS = {"User-Agent": "StockAgent idosh160@gmail.com"}


def get_cik(symbol):
    """מחפש את מספר CIK של חברה לפי הסימבול שלה"""
    try:
        url = "https://efts.sec.gov/LATEST/search-index?q=%22{}%22&dateRange=custom&startdt=2024-01-01&enddt=2026-12-31".format(symbol)
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={symbol}&type=10-K&dateb=&owner=include&count=5&search_text=&action=getcompany&output=atom"
        r = requests.get(url, headers=HEADERS, timeout=10)
        # שיטה יותר אמינה — קובץ JSON ממוין של כל החברות
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        r2 = requests.get(tickers_url, headers=HEADERS, timeout=15)
        if r2.status_code == 200:
            data = r2.json()
            for key, val in data.items():
                if val.get("ticker", "").upper() == symbol.upper():
                    cik = str(val["cik_str"]).zfill(10)
                    return cik
    except Exception:
        pass
    return None


def get_latest_filings(cik, form_type="10-Q", count=2):
    """שולף את הדוחות האחרונים של חברה"""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        results = []
        for i, form in enumerate(forms):
            if form == form_type and len(results) < count:
                results.append({
                    "form": form,
                    "date": dates[i] if i < len(dates) else "",
                    "accession": accessions[i] if i < len(accessions) else "",
                    "cik": cik,
                })
        return results
    except Exception:
        return []


def get_filing_text(cik, accession_number):
    """מוריד את תוכן הדוח — ראשי בלבד, מוגבל ל-8000 תווים לClaude"""
    try:
        acc_clean = accession_number.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{accession_number}-index.htm"
        r = requests.get(index_url, headers=HEADERS, timeout=15)
        # מחפש קובץ htm/html ראשי
        import re
        matches = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', r.text, re.IGNORECASE)
        if not matches:
            return ""
        doc_url = "https://www.sec.gov" + matches[0]
        r2 = requests.get(doc_url, headers=HEADERS, timeout=20)
        # מוציא טקסט נקי מה-HTML
        text = re.sub(r'<[^>]+>', ' ', r2.text)
        text = re.sub(r'\s+', ' ', text).strip()
        # מחזיר רק 8000 תווים ראשונים
        return text[:8000]
    except Exception:
        return ""


def get_insider_form4(cik, symbol):
    """שולף Form 4 — מסחר פנימי רשמי מה-SEC"""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        results = []
        for i, form in enumerate(forms):
            if form == "4" and len(results) < 5:
                results.append({
                    "date": dates[i] if i < len(dates) else "",
                    "form": "4",
                })
        return results
    except Exception:
        return []


def fetch_sec_data_for_symbol(symbol):
    """פונקציה ראשית — מביאה הכל ל-symbol אחד"""
    print(f"  [SEC] {symbol}...")
    time.sleep(0.2)  # כבוד ל-SEC rate limit

    cik = get_cik(symbol)
    if not cik:
        return {"error": f"CIK not found for {symbol}"}

    # דוח 10-Q (רבעוני) אחרון
    filings_10q = get_latest_filings(cik, form_type="10-Q", count=1)
    # דוח 10-K (שנתי) אחרון
    filings_10k = get_latest_filings(cik, form_type="10-K", count=1)
    # Form 4 — מסחר פנימי
    form4_list = get_insider_form4(cik, symbol)

    latest_filing = filings_10q[0] if filings_10q else (filings_10k[0] if filings_10k else None)
    filing_text = ""
    filing_date = ""
    filing_type = ""

    if latest_filing:
        filing_date = latest_filing["date"]
        filing_type = latest_filing["form"]
        filing_text = get_filing_text(cik, latest_filing["accession"])

    return {
        "cik": cik,
        "symbol": symbol,
        "latest_filing_type": filing_type,
        "latest_filing_date": filing_date,
        "filing_text_excerpt": filing_text,
        "recent_form4_count": len(form4_list),
        "recent_form4_dates": [f["date"] for f in form4_list],
    }


def fetch_sec_data_for_portfolio(symbols):
    """שולף SEC data לכל המניות בתיק"""
    results = {}
    for sym in symbols:
        try:
            results[sym] = fetch_sec_data_for_symbol(sym)
        except Exception as e:
            results[sym] = {"error": str(e)}
    return results
