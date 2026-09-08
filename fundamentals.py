"""
Fundamentals overlay.

Only runs on names that already passed the technical screen - typically 5 to
30 tickers, not the whole universe. yfinance's .info endpoint is one HTTP
request per ticker and is slow and rate-limit prone, so fetching it for 1,200
names would take forever and get throttled.

The grade is deliberately crude. It is a sanity check on the business behind
the chart, not a valuation model.
"""

import time


FIELDS = (
    "shortName", "sector", "industry", "marketCap",
    "trailingPE", "forwardPE", "profitMargins", "grossMargins",
    "revenueGrowth", "earningsGrowth", "returnOnEquity",
    "debtToEquity", "freeCashflow", "totalRevenue",
)


def fetch(tickers, pause=0.4):
    """Return {ticker: {field: value}}. Missing data is fine and common."""
    import yfinance as yf

    out = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info or {}
            out[t] = {k: info.get(k) for k in FIELDS}
        except Exception as e:
            print(f"    fundamentals unavailable for {t}: {e}")
            out[t] = {k: None for k in FIELDS}
        time.sleep(pause)
    return out


def _num(v):
    """Coerce to float, or None."""
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f else f  # reject NaN
    except (TypeError, ValueError):
        return None


def grade(f):
    """
    Score the business on four crude checks. Returns (label, notes, flags).

    Each check is pass / fail / unknown. Unknown is not counted against the
    company - plenty of legitimate names have gaps in free data.
    """
    notes, good, bad = [], 0, 0

    margin = _num(f.get("profitMargins"))
    if margin is not None:
        if margin > 0.10:
            good += 1
            notes.append(f"Net margin {margin:.0%} — solidly profitable")
        elif margin > 0:
            notes.append(f"Net margin {margin:.0%} — thin but positive")
        else:
            bad += 1
            notes.append(f"Net margin {margin:.0%} — currently lossmaking")

    growth = _num(f.get("revenueGrowth"))
    if growth is not None:
        if growth > 0.10:
            good += 1
            notes.append(f"Revenue growing {growth:.0%} year over year")
        elif growth > 0:
            notes.append(f"Revenue up {growth:.0%} — modest growth")
        else:
            bad += 1
            notes.append(f"Revenue {growth:.0%} — sales are shrinking")

    roe = _num(f.get("returnOnEquity"))
    if roe is not None:
        if roe > 0.15:
            good += 1
            notes.append(f"Return on equity {roe:.0%}")
        elif roe < 0:
            bad += 1
            notes.append(f"Return on equity {roe:.0%} — destroying capital")

    de = _num(f.get("debtToEquity"))
    if de is not None:
        de = de / 100 if de > 5 else de  # yfinance sometimes reports percent
        if de < 0.5:
            good += 1
            notes.append(f"Debt/equity {de:.2f} — conservative balance sheet")
        elif de > 2.0:
            bad += 1
            notes.append(f"Debt/equity {de:.2f} — heavily leveraged")
        else:
            notes.append(f"Debt/equity {de:.2f} — moderate leverage")

    sf = _num(f.get("shortPercentOfFloat"))
    if sf is not None:
        sf = sf if sf <= 1 else sf / 100      # sometimes percent, sometimes fraction
        dtc = _num(f.get("shortRatio"))
        dtc_txt = f", {dtc:.1f} days to cover" if dtc else ""
        if sf > 0.20:
            notes.append(f"Short interest {sf:.1%} of float{dtc_txt} — heavily "
                         "shorted, so squeezes and sharp reversals are both live risks")
        elif sf > 0.10:
            notes.append(f"Short interest {sf:.1%} of float{dtc_txt} — elevated")
        else:
            notes.append(f"Short interest {sf:.1%} of float{dtc_txt} — unremarkable")

        prior = _num(f.get("sharesShortPriorMonth"))
        cur = _num(f.get("sharesShort"))
        if prior and cur and prior > 0:
            chg = cur / prior - 1
            if abs(chg) > 0.15:
                direction = "rising" if chg > 0 else "falling"
                notes.append(f"Shares short {direction} {abs(chg):.0%} month over month")

    flt = _num(f.get("floatShares"))
    if flt is not None and flt > 0:
        if flt < 20e6:
            notes.append(f"Float only {flt / 1e6:.1f}M shares — thin, expect "
                         "violent moves in both directions")
        elif flt < 75e6:
            notes.append(f"Float {flt / 1e6:.0f}M shares — moderately tight")

    if not notes:
        return "No data", ["Fundamental data unavailable for this ticker"], 0

    if bad == 0 and good >= 3:
        label = "Strong"
    elif bad == 0 and good >= 1:
        label = "Sound"
    elif bad == 0:
        label = "Limited data"
    elif bad == 1 and good >= 1:
        label = "Mixed"
    elif bad == 1:
        label = "Mixed"
    else:
        label = "Weak"

    return label, notes, good - bad


def describe(f):
    """One-line business description for the report."""
    name = f.get("shortName") or ""
    sector = f.get("sector") or ""
    cap = _num(f.get("marketCap"))

    if cap:
        if cap >= 200e9:
            size = "mega cap"
        elif cap >= 10e9:
            size = "large cap"
        elif cap >= 2e9:
            size = "mid cap"
        else:
            size = "small cap"
        cap_txt = f"{size} at ${cap / 1e9:.1f}B"
    else:
        cap_txt = ""

    parts = [p for p in (name, sector, cap_txt) if p]
    return ", ".join(parts) if parts else "-"


def fetch_best(tickers):
    """
    Preferred source first, free fallback second.

    If FINVIZ_AUTH is set, one Elite export call covers every ticker at once
    and brings richer data (short interest, float, ownership, analyst recom).
    Otherwise fall back to Yahoo, one request per ticker.
    """
    import finviz

    if finviz.available():
        print("Using Finviz Elite for fundamentals...")
        df = finviz.fetch_screen()
        recs = finviz.to_records(df)
        if recs:
            wanted = set(tickers)
            hit = {t: r for t, r in recs.items() if t in wanted}
            missing = wanted - set(hit)
            print(f"  Finviz covered {len(hit)}/{len(wanted)} tickers")
            if missing:
                print(f"  Falling back to Yahoo for {len(missing)}: "
                      f"{', '.join(sorted(missing)[:8])}")
                hit.update(fetch(sorted(missing)))
            return hit
        print("  Finviz returned nothing usable - using Yahoo.")

    return fetch(tickers)
