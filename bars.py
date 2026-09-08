"""
Normalizes yfinance output.

yfinance changed its column layout between major versions. Depending on the
version and the arguments, download() can return any of:

  1. Flat columns:            Open, High, Low, Close, Volume
  2. (Price, Ticker):         ('Close','SPY'), ('Open','SPY'), ...
  3. (Ticker, Price):         ('SPY','Close'), ('SPY','Open'), ...

Code written against one layout breaks on the others - typically as
"float() argument must be a string or a real number, not 'Series'", because
frame['Close'] returns a one-column DataFrame instead of a Series.

Everything in this project goes through here so the rest of the code can
assume a plain OHLCV frame with a single level of columns.
"""

import pandas as pd

OHLCV = ("Open", "High", "Low", "Close", "Volume")


def flatten(df, ticker=None):
    """Return a single-ticker OHLCV frame with flat columns, or None."""
    if df is None or len(df) == 0:
        return None

    if not isinstance(df.columns, pd.MultiIndex):
        return df

    lv0 = df.columns.get_level_values(0)
    lv1 = df.columns.get_level_values(1)

    # Prefer an explicit ticker match on whichever level holds tickers.
    if ticker:
        if ticker in set(lv0):
            out = df.xs(ticker, axis=1, level=0)
            return out if len(out.columns) else None
        if ticker in set(lv1):
            out = df.xs(ticker, axis=1, level=1)
            return out if len(out.columns) else None
        return None

    # No ticker given: identify the price level by its known field names.
    if set(lv1) & set(OHLCV):
        df = df.droplevel(0, axis=1)
    elif set(lv0) & set(OHLCV):
        df = df.droplevel(1, axis=1)
    else:
        df = df.droplevel(1, axis=1)

    # A duplicated ticker level can leave repeated column names.
    return df.loc[:, ~df.columns.duplicated()]


def scalar(v):
    """Coerce a value that might be a 1-element Series into a float."""
    if hasattr(v, "iloc"):
        if len(v) == 0:
            return float("nan")
        v = v.iloc[0]
    if hasattr(v, "item"):
        try:
            return float(v.item())
        except (ValueError, AttributeError):
            pass
    return float(v)


def usable(df, min_rows=1):
    """True if this frame has the columns and depth we need."""
    if df is None or len(df) < min_rows:
        return False
    return all(c in df.columns for c in ("High", "Low", "Close", "Volume"))
