"""
Preflight check. Runs before the scan and says, in plain language, exactly
what is missing or broken.

The point is that a failed GitHub Actions run should never be a bare
"exit code 1" with the reason buried three hundred lines up the log.
"""

import os
import sys

REQUIRED_FILES = [
    ("swing_scanner.py", "the scanner itself"),
    ("universe.py", "builds the ticker list"),
    ("setups.py", "setup detection and trade levels"),
    ("fundamentals.py", "business quality grades"),
    ("tradingview.py", "chart links and watchlist export"),
    ("report.py", "the email report"),
    ("dashboard.py", "the web app's data feed"),
    ("bars.py", "normalizes price data"),
    ("requirements.txt", "the Python dependency list"),
]

BANNER = "=" * 68


def fail(problem, fix):
    print(f"\n{BANNER}\nSETUP PROBLEM: {problem}\n\nHOW TO FIX: {fix}\n{BANNER}\n")
    return False


def check_files():
    ok = True
    for name, why in REQUIRED_FILES:
        if not os.path.exists(name):
            ok = fail(
                f"{name} is missing ({why}).",
                f"Upload {name} to the top level of your repository. Use "
                "Add file -> Upload files on the repo's main page. Make sure "
                "it lands at the top level, not inside a subfolder.")
    return ok


def check_universe():
    if os.path.exists("universe.txt"):
        with open("universe.txt") as f:
            n = sum(1 for line in f
                    if line.strip() and not line.startswith("#"))
        if n:
            print(f"  universe.txt: {n} tickers")
            return True
        return fail(
            "universe.txt exists but has no tickers in it.",
            "Go to the Actions tab, choose 'Weekly universe refresh', and "
            "click Run workflow. That rebuilds the list.")
    return fail(
        "universe.txt is missing.",
        "Either upload universe.txt from the zip, or go to Actions -> "
        "'Weekly universe refresh' -> Run workflow to generate it.")


def check_imports():
    missing = []
    for mod in ("pandas", "numpy", "yfinance"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return fail(
            f"Python packages not installed: {', '.join(missing)}.",
            "This normally means requirements.txt did not upload. Check it "
            "is at the top level of your repository.")
    import pandas
    print(f"  pandas {pandas.__version__}")
    try:
        import yfinance
        print(f"  yfinance {getattr(yfinance, '__version__', 'unknown')}")
    except Exception:
        pass
    return True


def check_network():
    """One tiny download. If this fails, nothing downstream can work."""
    try:
        import yfinance as yf
        import bars
        raw = yf.download("SPY", period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        df = bars.flatten(raw, "SPY")
        if df is None:
            df = bars.flatten(raw)
        if df is None or df.empty:
            return fail(
                "Yahoo Finance returned no data for SPY.",
                "This is almost always temporary rate limiting rather than "
                "anything you did. Wait ten minutes and re-run the workflow. "
                "If it keeps happening for days, yfinance may need updating - "
                "edit requirements.txt and bump the yfinance version.")
        import bars as _b
        print(f"  Yahoo reachable, SPY last close "
              f"{_b.scalar(df['Close'].iloc[-1]):.2f}")
        return True
    except Exception as e:
        return fail(
            f"Could not reach Yahoo Finance ({type(e).__name__}: {e}).",
            "Usually temporary. Wait ten minutes and re-run. If it persists, "
            "bump the yfinance version in requirements.txt.")


def main():
    print("Preflight check\n" + "-" * 30)
    ok = True

    if not check_files():
        ok = False

    # Later checks depend on earlier ones, so stop rather than emit
    # a cascade of misleading follow-on errors.
    if not check_imports():
        print("Preflight failed. Fix the problem above and re-run.")
        return 1

    for step in (check_universe, check_network):
        if not step():
            ok = False

    if ok:
        print("-" * 30 + "\nAll checks passed.\n")
        return 0
    print("Preflight failed. Fix the problem above and re-run the workflow.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
