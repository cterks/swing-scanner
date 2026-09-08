"""
Builds the scan universe automatically. No hand-picked watchlist.

Two stages:
  1. Pull every US listed symbol from NASDAQ Trader's public symbol directory
     (free, no key, updated nightly), then strip out everything that isn't
     ordinary common stock - ETFs, warrants, units, rights, preferreds,
     test issues, and so on.
  2. Download 3 months of bars for what's left and keep the most liquid
     names by average dollar volume. That becomes universe.txt.

Stage 2 is slow, so it's cached. Refresh weekly, not daily.

Run directly to rebuild:
    python universe.py
"""

import io
import os
import sys
import time

import pandas as pd

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

UNIVERSE_FILE = "universe.txt"

# How many names survive to the daily scan. Higher = broader coverage but
# slower runs and more chance of hitting Yahoo's rate limits.
UNIVERSE_SIZE = 1200

# Liquidity floor applied before ranking.
MIN_PRICE = 10.0
MIN_DOLLAR_VOL = 5_000_000  # average daily dollar volume

CHUNK = 150      # tickers per download call
PAUSE = 1.5      # seconds between chunks, to stay under rate limits

# Security-name substrings that indicate something other than common stock.
NAME_EXCLUDE = (
    "warrant", "right", " unit", "units", "preferred", "depositary",
    "debenture", "notes due", "convertible", "trust", "acquisition corp",
    "%", "etf", "index fund", "ishares", "spdr", "proshares", "invesco",
    "vanguard", "direxion", "when issued",
)


def _read_pipe_file(text):
    """NASDAQ Trader files are pipe-delimited with a footer line to drop."""
    df = pd.read_csv(io.StringIO(text), sep="|", dtype=str)
    # Last row is 'File Creation Time: ...' in the first column.
    if len(df) and str(df.iloc[-1, 0]).startswith("File Creation Time"):
        df = df.iloc[:-1]
    return df.fillna("")


def _clean(df, sym_col, name_col, etf_col, test_col):
    """Filter one directory file down to plausible common stock."""
    out = df.copy()
    out.columns = [c.strip() for c in out.columns]

    if test_col in out.columns:
        out = out[out[test_col].str.strip().str.upper() != "Y"]
    if etf_col in out.columns:
        out = out[out[etf_col].str.strip().str.upper() != "Y"]

    sym = out[sym_col].str.strip().str.upper()
    name = out[name_col].str.strip().str.lower()

    keep = (
        sym.str.fullmatch(r"[A-Z]{1,5}")          # no dots, dollars, suffixes
        & ~name.apply(lambda n: any(x in n for x in NAME_EXCLUDE))
    )
    kept = out[keep]
    ex_col = "Exchange" if "Exchange" in out.columns else "Market Category"
    if ex_col in kept.columns:
        codes = kept[ex_col].str.strip().str.upper()
    else:
        codes = pd.Series(["Q"] * len(kept), index=kept.index)
    return dict(zip(sym[keep], codes))


def fetch_symbols():
    """Return every US listed common stock symbol. Requires network."""
    import urllib.request

    symbols = {}

    for url, cols in (
        (NASDAQ_URL, ("Symbol", "Security Name", "ETF", "Test Issue")),
        (OTHER_URL, ("ACT Symbol", "Security Name", "ETF", "Test Issue")),
    ):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                text = r.read().decode("utf-8", errors="replace")
            df = _read_pipe_file(text)
            symbols.update(_clean(df, *cols))
            print(f"  {url.rsplit('/', 1)[-1]}: {len(df)} rows")
        except Exception as e:
            print(f"  WARNING: could not fetch {url} - {e}")

    return symbols


def rank_by_liquidity(symbols):
    """Download recent bars in chunks and keep the most liquid names."""
    import yfinance as yf

    rows = []
    total = (len(symbols) + CHUNK - 1) // CHUNK

    for i in range(0, len(symbols), CHUNK):
        batch = symbols[i:i + CHUNK]
        n = i // CHUNK + 1
        print(f"  chunk {n}/{total} ({len(batch)} tickers)...", flush=True)

        try:
            data = yf.download(
                batch, period="3mo", interval="1d", auto_adjust=True,
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            print(f"    chunk failed, skipping: {e}")
            time.sleep(PAUSE * 3)
            continue

        for t in batch:
            try:
                df = data[t].dropna() if len(batch) > 1 else data.dropna()
            except (KeyError, TypeError):
                continue
            if len(df) < 40:
                continue

            price = float(df["Close"].iloc[-1])
            dollar_vol = float((df["Close"] * df["Volume"]).tail(40).mean())

            if price >= MIN_PRICE and dollar_vol >= MIN_DOLLAR_VOL:
                rows.append({"ticker": t, "price": price,
                             "dollar_vol": dollar_vol})

        time.sleep(PAUSE)

    ranked = sorted(rows, key=lambda r: r["dollar_vol"], reverse=True)
    return [r["ticker"] for r in ranked[:UNIVERSE_SIZE]]


def build():
    print("Fetching the full symbol directory...")
    sym_map = fetch_symbols()
    if not sym_map:
        sys.exit("Could not fetch any symbols. Check the network and retry.")
    print(f"{len(sym_map)} common stocks after filtering.\n")

    print("Ranking by liquidity (this takes a few minutes)...")
    universe = rank_by_liquidity(sorted(sym_map))

    if not universe:
        sys.exit("Liquidity ranking returned nothing. Not overwriting the "
                 "existing universe file.")

    with open(UNIVERSE_FILE, "w") as f:
        f.write("# Auto-generated by universe.py. Do not edit by hand.\n")
        f.write(f"# {len(universe)} most liquid US common stocks.\n")
        f.write("# ticker,exchange_code\n")
        for t in universe:
            f.write(f"{t},{sym_map.get(t, 'Q')}\n")

    print(f"\nWrote {UNIVERSE_FILE} with {len(universe)} tickers.")
    print(f"Sample: {', '.join(universe[:12])}")
    return universe


def load(path=UNIVERSE_FILE):
    """Read the cached universe. Falls back to watchlist.txt if absent."""
    for p in (path, "watchlist.txt"):
        if os.path.exists(p):
            with open(p) as f:
                tickers = [
                    line.strip().upper().split(",")[0] for line in f
                    if line.strip() and not line.startswith("#")
                ]
            if tickers:
                print(f"Loaded {len(tickers)} tickers from {p}")
                return tickers
    sys.exit("No universe.txt or watchlist.txt found. Run: python universe.py")


if __name__ == "__main__":
    build()


def load_exchanges(path=UNIVERSE_FILE):
    """Return {ticker: exchange_code}. Empty dict if the file has no codes."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.upper().split(",")
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    return out
