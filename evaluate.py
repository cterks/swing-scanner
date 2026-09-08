"""
Forward-tests the screen against its own history.

Every run commits results/ranked_YYYY-MM-DD.csv. This walks those files, finds
candidates old enough to have an outcome, looks up what the price actually did
at +5 and +20 trading days, and reports hit rates per setup.

This is the honest measurement. It is unbiased in a way a manual trade log is
not, because it scores every candidate the screen ever produced - including
the ones you would have talked yourself out of taking.

It answers one question: does a setup do better than a coin flip?
"""

import glob
import json
import os
from datetime import datetime

import pandas as pd

import bars

RESULTS_DIR = "results"
OUT = "docs/record.json"

HORIZONS = (5, 20)
MIN_SAMPLE = 30      # below this, results are noise and are labelled as such

# A run needs at least this many calendar days before any outcome exists.
# Scoring today's candidates is meaningless - nothing has happened to them.
# It also avoids asking Yahoo for a start date that is still in the future,
# which happens whenever the scan runs late enough that UTC has rolled over.
MIN_AGE_DAYS = 3

# Fetch from a few days before the earliest run so the base price is available
# even if that run landed on a Monday after a long weekend.
LOOKBACK_PAD_DAYS = 7


def _load_history():
    """Past runs old enough to have an outcome, oldest first."""
    from datetime import date as _date, timedelta

    cutoff = _date.today() - timedelta(days=MIN_AGE_DAYS)
    rows, skipped = [], 0

    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, "ranked_*.csv"))):
        date = os.path.basename(path)[7:-4]
        try:
            if _date.fromisoformat(date) > cutoff:
                skipped += 1
                continue
        except ValueError:
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        for _, r in df.iterrows():
            rows.append({
                "date": date,
                "ticker": str(r.get("ticker", "")).upper(),
                "setup": r.get("setup", "Unknown"),
                "entry": r.get("entry"),
                "price": r.get("price"),
            })

    if skipped:
        print(f"Skipped {skipped} run(s) newer than {MIN_AGE_DAYS} days - "
              "too recent to have an outcome yet.")
    return rows


def _price_lookup(tickers, start):
    """Daily closes for every ticker we need to score."""
    import yfinance as yf

    out = {}
    tickers = sorted(set(tickers))
    for i in range(0, len(tickers), 150):
        batch = tickers[i:i + 150]
        try:
            data = yf.download(batch, start=start, interval="1d",
                               auto_adjust=True, group_by="ticker",
                               progress=False, threads=True)
        except Exception as e:
            print(f"  price fetch failed for a batch: {e}")
            continue
        for t in batch:
            df = bars.flatten(data, t)
            if df is None and len(batch) == 1:
                df = bars.flatten(data)
            if df is None or "Close" not in df.columns:
                continue
            s = df["Close"].dropna()
            if len(s):
                out[t] = s
    return out


def evaluate():
    rows = _load_history()
    if not rows:
        print("Nothing old enough to score yet. This is expected for roughly "
              "the first week - come back once a few runs have aged.")
        return None

    earliest = min(r["date"] for r in rows)

    # Pad backwards so the base price exists, and never ask for a start date
    # at or after today.
    from datetime import date as _date, timedelta
    start = _date.fromisoformat(earliest) - timedelta(days=LOOKBACK_PAD_DAYS)
    today = _date.today()
    if start >= today:
        print("Start date would be in the future - nothing to score.")
        return None

    print(f"Evaluating {len(rows)} past candidates since {earliest} "
          f"(fetching from {start})...")

    prices = _price_lookup([r["ticker"] for r in rows], start.isoformat())

    scored = []
    for r in rows:
        s = prices.get(r["ticker"])
        if s is None or s.empty:
            continue
        try:
            run_day = pd.Timestamp(r["date"]).tz_localize(None)
        except Exception:
            continue

        idx = s.index.tz_localize(None) if s.index.tz is not None else s.index
        after = s[idx > run_day]
        if after.empty:
            continue

        prior = s[idx <= run_day]
        base = bars.scalar(prior.iloc[-1]) if len(prior) else None
        if not base:
            continue

        rec = {"date": r["date"], "ticker": r["ticker"],
               "setup": r["setup"] or "Unknown"}
        for h in HORIZONS:
            rec[f"r{h}"] = (bars.scalar(after.iloc[h - 1]) / base - 1
                            if len(after) >= h else None)
        scored.append(rec)

    if not scored:
        print("No candidates are old enough to score yet.")
        return None

    df = pd.DataFrame(scored)

    def stats(sub):
        out = {"n": int(len(sub))}
        for h in HORIZONS:
            col = sub[f"r{h}"].dropna()
            out[f"n{h}"] = int(len(col))
            out[f"avg{h}"] = round(float(col.mean()) * 100, 2) if len(col) else None
            out[f"win{h}"] = (round(float((col > 0).mean()) * 100, 1)
                              if len(col) else None)
            out[f"med{h}"] = round(float(col.median()) * 100, 2) if len(col) else None
        return out

    record = {
        "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "first_run": earliest,
        "min_sample": MIN_SAMPLE,
        "overall": stats(df),
        "by_setup": {name: stats(sub) for name, sub in df.groupby("setup")},
    }

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(record, f, indent=1)

    o = record["overall"]
    print(f"\nScored {o['n']} candidates.")
    for h in HORIZONS:
        if o[f"win{h}"] is not None:
            print(f"  +{h}d: {o[f'win{h}']}% finished up, "
                  f"average {o[f'avg{h}']:+.2f}% (n={o[f'n{h}']})")
    if o["n20"] < MIN_SAMPLE:
        print(f"\n  Sample is {o['n20']}, below {MIN_SAMPLE}. Treat as noise.")

    return record


if __name__ == "__main__":
    evaluate()
