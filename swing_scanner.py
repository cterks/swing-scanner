"""
Swing scanner - ranks the tradable universe by pullback quality.

Loads tickers from universe.txt (built automatically by universe.py),
pulls daily bars, computes three factors, and writes a ranked CSV.

Setup (one time):
    pip install yfinance pandas numpy

Run:
    python swing_scanner.py

Output:
    ranked_YYYY-MM-DD.csv
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

import bars

BENCHMARK = "SPY"
LOOKBACK_DAYS = 400
RS_WINDOW = 60
ATR_SHORT = 5
ATR_LONG = 20
TOP_N = 10

# Factor weights. Must sum to 1.0. Tune these once you have a trade log.
WEIGHTS = {
    "pullback": 0.40,
    "coil": 0.30,
    "rel_strength": 0.30,
}


# ---------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------

def true_range(df):
    """Wilder's true range: the largest of three candidate ranges."""
    prev_close = df["Close"].shift(1)
    a = df["High"] - df["Low"]
    b = (df["High"] - prev_close).abs()
    c = (df["Low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df, window):
    return true_range(df).rolling(window).mean()


def sma(series, window):
    return series.rolling(window).mean()


def rsi(series, window=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # No down days at all -> RSI is 100 by definition, not undefined.
    return out.mask(avg_loss.eq(0) & avg_gain.gt(0), 100.0)


# ---------------------------------------------------------------------
# Factors
# ---------------------------------------------------------------------

def compute_metrics(df, bench_return_60d):
    """Return a dict of raw metrics for one ticker, or None if unusable."""
    if df is None or len(df) < 210:
        return None

    close = df["Close"]
    last = bars.scalar(close.iloc[-1])

    sma20 = bars.scalar(sma(close, 20).iloc[-1])
    sma50 = bars.scalar(sma(close, 50).iloc[-1])
    sma200 = bars.scalar(sma(close, 200).iloc[-1])

    if any(np.isnan(x) for x in (sma20, sma50, sma200)):
        return None

    atr_s = bars.scalar(atr(df, ATR_SHORT).iloc[-1])
    atr_l = bars.scalar(atr(df, ATR_LONG).iloc[-1])
    if np.isnan(atr_s) or np.isnan(atr_l) or atr_l == 0:
        return None

    ret_60 = last / bars.scalar(close.iloc[-(RS_WINDOW + 1)]) - 1.0

    return {
        "price": last,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "rsi14": bars.scalar(rsi(close).iloc[-1]),
        "avg_vol_50d": bars.scalar(df["Volume"].rolling(50).mean().iloc[-1]),
        "pct_from_52w_high": last / bars.scalar(close.tail(252).max()) - 1.0,
        # Distance below the 50-day, as a fraction. Positive = below the MA.
        "pullback_depth": (sma50 - last) / sma50,
        "pct_above_sma200": (last / sma200 - 1) * 100,
        "atr14": bars.scalar(atr(df, 14).iloc[-1]),
        # Volume over the last 5 days vs the 50-day average. Below 1.0 = dry-up.
        "vol_dryup": bars.scalar(df["Volume"].tail(5).mean())
        / bars.scalar(df["Volume"].tail(50).mean()),
        # Volatility contraction. Below 1.0 means recent ranges are tightening.
        "coil_ratio": atr_s / atr_l,
        "rel_strength": ret_60 - bench_return_60d,
    }


def passes_filters(m):
    """Liquidity gates only. The individual setups decide everything else."""
    return m["price"] > 10 and m["avg_vol_50d"] > 500_000


def normalize(values):
    """Min-max to 0-1. Returns 0.5 for everything if there's no spread."""
    arr = np.asarray(values, dtype=float)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-12:
        return np.full_like(arr, 0.5)
    return (arr - lo) / (hi - lo)


def score(rows):
    """Rank candidates. Higher score = better setup."""
    if not rows:
        return []

    # Deeper pullback scores higher, but only within reason - the hard
    # filters already excluded anything that broke its 50-day badly.
    pullback = normalize([r["pullback_depth"] for r in rows])
    # Tighter coil scores higher, so invert.
    coil = 1.0 - normalize([r["coil_ratio"] for r in rows])
    rel = normalize([r["rel_strength"] for r in rows])

    for i, r in enumerate(rows):
        r["s_pullback"] = pullback[i]
        r["s_coil"] = coil[i]
        r["s_rel_strength"] = rel[i]
        r["score"] = (
            WEIGHTS["pullback"] * pullback[i]
            + WEIGHTS["coil"] * coil[i]
            + WEIGHTS["rel_strength"] * rel[i]
        )

    return sorted(rows, key=lambda r: r["score"], reverse=True)


# ---------------------------------------------------------------------
# Trade levels
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Data + main
# ---------------------------------------------------------------------

def fetch(tickers, chunk=150, pause=1.5):
    """Pull daily bars in chunks. Returns {ticker: DataFrame}."""
    import time
    import yfinance as yf

    out = {}
    total = (len(tickers) + chunk - 1) // chunk

    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        print(f"  chunk {i // chunk + 1}/{total}...", flush=True)

        try:
            data = yf.download(
                batch,
                period=f"{LOOKBACK_DAYS}d",
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as e:
            print(f"    chunk failed, skipping: {e}")
            time.sleep(pause * 3)
            continue

        for t in batch:
            df = bars.flatten(data, t)
            if df is None and len(batch) == 1:
                df = bars.flatten(data)
            if df is None:
                continue
            df = df.dropna()
            if bars.usable(df):
                out[t] = df

        time.sleep(pause)

    return out


def main():
    import universe
    tickers = universe.load()
    print(f"Fetching {len(tickers)} tickers plus benchmark...")

    price_bars = fetch(tickers + [BENCHMARK])

    if BENCHMARK not in price_bars:
        print("\n" + "=" * 68)
        print(f"SETUP PROBLEM: could not fetch {BENCHMARK} (the benchmark).")
        print("\nHOW TO FIX: this is nearly always Yahoo rate limiting, not")
        print("something you did. Wait ten minutes and re-run the workflow")
        print("from the Actions tab. If it fails for several days running,")
        print("bump the yfinance version in requirements.txt.")
        print("=" * 68 + "\n")
        sys.exit(1)

    bench = price_bars[BENCHMARK]["Close"]
    bench_ret = (bars.scalar(bench.iloc[-1])
                 / bars.scalar(bench.iloc[-(RS_WINDOW + 1)]) - 1.0)
    print(f"{BENCHMARK} {RS_WINDOW}d return: {bench_ret:+.1%}")

    import setups

    rows = []
    for t in tickers:
        m = compute_metrics(price_bars.get(t), bench_ret)
        if m is None or not passes_filters(m):
            continue

        primary, matched, reasons = setups.detect(m)
        if primary is None:
            continue

        lv = setups.trade_levels(price_bars[t], m)
        if lv is None:
            continue

        m["ticker"] = t
        m["setup"] = primary
        m["all_setups"] = matched
        m["reasons"] = reasons
        m.update(lv)
        rows.append(m)

    ranked = score(rows)
    print(f"{len(ranked)} of {len(tickers)} passed filters.\n")

    if not ranked:
        print("No candidates today. That is a normal and useful result.")
        import dashboard
        dashboard.write([], date.today().isoformat(), len(tickers), bench_ret)
        emit_report(None, date.today().isoformat(), len(tickers), bench_ret)
        return

    # Fundamentals: only for the names that made the cut, so this stays fast.
    top = ranked[:TOP_N]
    print(f"Fetching fundamentals for the top {len(top)}...")
    import fundamentals
    finfo = fundamentals.fetch_best([r["ticker"] for r in top])
    for r in top:
        f = finfo.get(r["ticker"], {})
        label, notes, _ = fundamentals.grade(f)
        r["fund_grade"] = label
        r["fund_notes"] = notes
        r["business"] = fundamentals.describe(f)

    # TradingView watchlist for the candidates
    import tradingview, universe as _u
    exchanges = _u.load_exchanges()
    tradingview.write_watchlist(top, exchanges)
    for r in top:
        r["tv_url"] = tradingview.chart_url(r["ticker"],
                                            exchanges.get(r["ticker"]))

    cols = [
        "ticker", "setup", "score", "price",
        "entry", "stop", "target_2r", "target_3r", "risk_pct",
        "rsi14", "pullback_depth", "coil_ratio", "rel_strength",
    ]
    out = pd.DataFrame(ranked)[cols]
    out["score"] = out["score"].round(3)
    out["pullback_depth"] = (out["pullback_depth"] * 100).round(2)
    out["rel_strength"] = (out["rel_strength"] * 100).round(2)
    out["coil_ratio"] = out["coil_ratio"].round(3)
    out["rsi14"] = out["rsi14"].round(1)
    out = out.rename(columns={
        "pullback_depth": "pullback_pct_below_sma50",
        "rel_strength": "rel_strength_pct_vs_spy",
    })

    run_date = date.today().isoformat()
    os.makedirs("results", exist_ok=True)
    fname = os.path.join("results", f"ranked_{run_date}.csv")
    out.to_csv(fname, index=False)

    print(out.head(TOP_N).to_string(index=False))
    print(f"\nWrote {fname}")

    import dashboard
    dashboard.write(top, run_date, len(tickers), bench_ret)

    emit_report(top, run_date, len(tickers), bench_ret)


def emit_report(rows, run_date, scanned, bench_ret):
    import report
    html = report.build_html(rows, run_date, scanned, bench_ret)
    n = 0 if rows is None else len(rows)
    subject = f"Swing scan {run_date} - {n} candidate{'' if n == 1 else 's'}"
    report.send(html, subject, attach="tradingview_watchlist.txt")


if __name__ == "__main__":
    main()
