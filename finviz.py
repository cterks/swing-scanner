"""
Finviz Elite export API.

This uses Finviz's OFFICIAL export endpoint, which is a paid Elite feature:
    https://elite.finviz.com/export.ashx?v=152&f=<filters>&auth=<token>

Documentation for your account's parameters is at:
    https://elite.finviz.com/api_explanation.ashx

Two things to be clear about:

  1. This requires a Finviz Elite subscription. Your auth token is on the
     API page linked above. Put it in the FINVIZ_AUTH GitHub Secret.

  2. This module does NOT scrape finviz.com. Scraping the free site is
     against Finviz's terms of service, and GitHub Actions runners share
     IP addresses that get blocked quickly. If you have no Elite token,
     this module does nothing and the scanner falls back to Yahoo.

Finviz asks for no more than one export call per 60 seconds. We make exactly
one call per run - a single screen returns every ticker with every column, so
there is no per-ticker looping to rate limit.
"""

import io
import os
import time

import pandas as pd

BASE = "https://elite.finviz.com/export.ashx"

# v=152 is the "Custom" screener view, which lets the column set be specified.
# c= is the ordered list of column ids. These cover description, valuation,
# financials, ownership and technicals including short interest.
DEFAULT_VIEW = "152"
DEFAULT_COLUMNS = (
    "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,"
    "26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,"
    "49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70"
)

# Default screen: liquid US common stock. Mirrors the universe filters so the
# Finviz path and the free path cover roughly the same names.
#   cap_smallover   - small cap and above
#   sh_avgvol_o500  - average volume over 500K
#   sh_price_o10    - price over $10
DEFAULT_FILTERS = "cap_smallover,sh_avgvol_o500,sh_price_o10"

_last_call = [0.0]
MIN_INTERVAL = 60.0   # seconds between calls, per Finviz guidance


def available():
    return bool(os.environ.get("FINVIZ_AUTH"))


def _throttle():
    elapsed = time.time() - _last_call[0]
    if _last_call[0] and elapsed < MIN_INTERVAL:
        wait = MIN_INTERVAL - elapsed
        print(f"  Finviz rate limit: waiting {wait:.0f}s")
        time.sleep(wait)
    _last_call[0] = time.time()


def fetch_screen(filters=DEFAULT_FILTERS, view=DEFAULT_VIEW,
                 columns=DEFAULT_COLUMNS, timeout=90):
    """
    Pull one screen as a DataFrame. Returns None if unavailable.

    One call returns the whole result set - all tickers, all columns.
    """
    import urllib.parse
    import urllib.request

    auth = os.environ.get("FINVIZ_AUTH")
    if not auth:
        print("No FINVIZ_AUTH set - skipping Finviz, using Yahoo instead.")
        return None

    params = {"v": view, "f": filters, "c": columns, "auth": auth}
    url = f"{BASE}?{urllib.parse.urlencode(params)}"

    _throttle()

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "swing-scanner/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Finviz export failed ({e}). Falling back to Yahoo.")
        return None

    if not raw.strip() or raw.lstrip().startswith("<"):
        print("Finviz returned no CSV - check the auth token is valid and "
              "your Elite subscription is active. Falling back to Yahoo.")
        return None

    try:
        df = pd.read_csv(io.StringIO(raw))
    except Exception as e:
        print(f"Could not parse Finviz CSV ({e}). Falling back to Yahoo.")
        return None

    if "Ticker" not in df.columns:
        print("Finviz CSV has no Ticker column. Falling back to Yahoo.")
        return None

    print(f"Finviz: {len(df)} rows, {len(df.columns)} columns")
    return df


# ---------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------
# Finviz column names -> our internal field names. Finviz occasionally
# renames columns, so anything missing is simply skipped rather than
# raising.

COLUMN_MAP = {
    "Company": "shortName",
    "Sector": "sector",
    "Industry": "industry",
    "Market Cap": "marketCap",
    "P/E": "trailingPE",
    "Forward P/E": "forwardPE",
    "Profit Margin": "profitMargins",
    "Gross Margin": "grossMargins",
    "Sales growth quarter over quarter": "revenueGrowth",
    "EPS growth quarter over quarter": "earningsGrowth",
    "Return on Equity": "returnOnEquity",
    "Total Debt/Equity": "debtToEquity",
    "Float Short": "shortPercentOfFloat",
    "Short Ratio": "shortRatio",
    "Shares Float": "floatShares",
    "Short Interest": "sharesShort",
    "Insider Ownership": "insiderOwn",
    "Institutional Ownership": "instOwn",
    "Average True Range": "atr",
    "Relative Strength Index (14)": "rsi",
    "Analyst Recom": "analystRecom",
    "Earnings Date": "earningsDate",
}

PERCENT_FIELDS = {
    "profitMargins", "grossMargins", "revenueGrowth", "earningsGrowth",
    "returnOnEquity", "shortPercentOfFloat", "insiderOwn", "instOwn",
}


def _to_number(v, is_percent=False):
    """Finviz writes '12.30%', '1.2B', '450M', '-' and blanks."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "nan", "NaN", "None"):
        return None

    s = s.replace(",", "").replace("%", "")
    mult = 1.0
    if s and s[-1] in "BMKT":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]

    try:
        n = float(s) * mult
    except ValueError:
        return None

    return n / 100 if is_percent else n


def to_records(df):
    """Turn the Finviz DataFrame into {ticker: {our_field: value}}."""
    if df is None:
        return {}

    out = {}
    for _, row in df.iterrows():
        t = str(row.get("Ticker", "")).strip().upper()
        if not t:
            continue

        rec = {}
        for fv_col, our_field in COLUMN_MAP.items():
            if fv_col not in df.columns:
                continue
            val = row[fv_col]
            if our_field in ("shortName", "sector", "industry",
                             "earningsDate", "analystRecom"):
                s = str(val).strip()
                rec[our_field] = None if s in ("", "-", "nan") else s
            else:
                rec[our_field] = _to_number(
                    val, is_percent=(our_field in PERCENT_FIELDS))
        out[t] = rec

    return out


def tickers(df):
    """Just the symbol list from a screen - useful as a universe source."""
    if df is None or "Ticker" not in df.columns:
        return []
    return [str(t).strip().upper() for t in df["Ticker"] if str(t).strip()]
