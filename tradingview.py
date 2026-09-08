"""
TradingView integration.

Two things:
  1. A .txt watchlist file in TradingView's import format - comma-separated
     symbols with exchange prefixes, e.g. NASDAQ:AAPL,NYSE:CAT
  2. Per-ticker chart deep links for the email report.

Import it in TradingView: open the watchlist panel on the right, click the
watchlist name, choose "Import list...", pick the file.

The exchange prefix matters. Without it TradingView guesses the data feed,
which usually works for large caps and fails on smaller names - you get a
blank chart or a stale foreign listing. We have real exchange data from the
NASDAQ symbol directory, so we use it.
"""

# NASDAQ Trader exchange codes -> TradingView prefixes
EXCHANGE_MAP = {
    "Q": "NASDAQ",   # NASDAQ (from nasdaqlisted.txt market categories)
    "G": "NASDAQ",
    "S": "NASDAQ",
    "N": "NYSE",
    "A": "AMEX",     # NYSE American
    "P": "NYSE",     # NYSE Arca - common stock there is rare
    "Z": "BATS",
    "V": "NASDAQ",   # IEX; TradingView coverage is patchy, NASDAQ is safer
}

DEFAULT_EXCHANGE = "NASDAQ"


def qualify(ticker, exchange_code=None):
    """Turn 'AAPL' into 'NASDAQ:AAPL'."""
    prefix = EXCHANGE_MAP.get((exchange_code or "").strip().upper(),
                              DEFAULT_EXCHANGE)
    return f"{prefix}:{ticker}"


def chart_url(ticker, exchange_code=None):
    """Deep link that opens this symbol on a TradingView chart."""
    return f"https://www.tradingview.com/chart/?symbol={qualify(ticker, exchange_code)}"


def write_watchlist(rows, exchanges, path="tradingview_watchlist.txt"):
    """
    Write the day's candidates as a TradingView-importable list.

    Sections are supported with ###Name headers, so candidates get grouped
    by setup. Symbols within a section are comma-separated.
    """
    by_setup = {}
    for r in rows:
        by_setup.setdefault(r.get("setup") or "Other", []).append(r)

    lines = []
    for setup, items in by_setup.items():
        lines.append(f"###{setup}")
        syms = [qualify(r["ticker"], exchanges.get(r["ticker"]))
                for r in items]
        lines.append(",".join(syms))

    text = "\n".join(lines) + "\n"
    with open(path, "w") as f:
        f.write(text)

    total = sum(len(v) for v in by_setup.values())
    print(f"Wrote {path} — {total} symbols in {len(by_setup)} section(s)")
    return text
