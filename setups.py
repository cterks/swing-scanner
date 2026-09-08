"""
Setup detection and trade levels.

Each setup is a named pattern with its own entry logic. A stock can match
more than one; the highest-priority match becomes its primary setup.

Every setup produces a plain-English reason list so the report explains
WHY a name appeared, not just that it scored well.
"""

import numpy as np


# ---------------------------------------------------------------------
# Setup definitions
# ---------------------------------------------------------------------
# Each returns (matched, reasons) given a metrics dict.

def setup_pullback(m):
    """Uptrend, price has pulled back to or below the 20-day. Buy the dip."""
    ok = (
        m["price"] > m["sma200"]
        and m["price"] > m["sma50"]
        and m["price"] < m["sma20"]
        and 35 <= m["rsi14"] <= 55
        and m["pct_from_52w_high"] > -0.20
    )
    if not ok:
        return False, []

    depth = m["pullback_depth"] * 100
    where = (f"{depth:.1f}% below" if depth > 0
             else f"{abs(depth):.1f}% above")
    reasons = [
        f"Trading {abs(m['pct_above_sma200']):.0f}% above its 200-day average, "
        "so the long-term trend is up",
        f"Now {where} its 50-day average — closer to support than to a chase",
        f"RSI at {m['rsi14']:.0f} — cooled off without breaking down",
    ]
    if m["rel_strength"] > 0:
        reasons.append(
            f"Outperforming SPY by {m['rel_strength'] * 100:.1f}% over 60 days"
        )
    return True, reasons


def setup_coil(m):
    """Volatility contraction near the highs. Tightening before a move."""
    ok = (
        m["price"] > m["sma50"]
        and m["price"] > m["sma200"]
        and m["coil_ratio"] < 0.80
        and m["pct_from_52w_high"] > -0.12
    )
    if not ok:
        return False, []

    reasons = [
        f"Daily ranges have contracted to {m['coil_ratio']:.0%} of their "
        "20-day norm — volatility is compressing",
        f"Holding within {abs(m['pct_from_52w_high']) * 100:.0f}% of its "
        "52-week high while quieting down",
        "Tight action near highs often precedes an expansion, though the "
        "direction is not predetermined",
    ]
    if m["vol_dryup"] < 0.85:
        reasons.append(
            f"Volume has dried up to {m['vol_dryup']:.0%} of its 50-day "
            "average, typical of a supply pause"
        )
    return True, reasons


def setup_breakout_ready(m):
    """Coiled right underneath a 52-week high."""
    ok = (
        m["pct_from_52w_high"] > -0.04
        and m["price"] > m["sma50"]
        and m["coil_ratio"] < 0.95
        and m["rsi14"] < 72
    )
    if not ok:
        return False, []

    return True, [
        f"Sitting {abs(m['pct_from_52w_high']) * 100:.1f}% below its 52-week "
        "high — a breakout is within reach",
        f"RSI at {m['rsi14']:.0f}, so it is not yet stretched",
        "Ranges are narrowing into the level rather than spiking through it",
    ]


def setup_trend_reset(m):
    """Deeper pullback all the way to the 50-day, still above the 200."""
    ok = (
        m["price"] > m["sma200"]
        and abs(m["price"] / m["sma50"] - 1) < 0.03
        and m["rsi14"] < 50
        and m["pct_above_sma200"] > 3
    )
    if not ok:
        return False, []

    return True, [
        "Price has come right back to its 50-day average, a level buyers "
        "often defend in an uptrend",
        f"Still {m['pct_above_sma200']:.0f}% above the 200-day, so the "
        "larger trend is intact",
        f"RSI at {m['rsi14']:.0f} — the pullback has done real work",
    ]


# Priority order. First match becomes the primary setup.
SETUPS = [
    ("Breakout ready", setup_breakout_ready),
    ("Volatility coil", setup_coil),
    ("Pullback to 20-day", setup_pullback),
    ("Trend reset at 50-day", setup_trend_reset),
]


def detect(m):
    """Return (primary_setup_name, all_matched_names, reasons) or (None,[],[])."""
    matched = []
    primary = None
    reasons = []

    for name, fn in SETUPS:
        ok, why = fn(m)
        if ok:
            matched.append(name)
            if primary is None:
                primary, reasons = name, why

    return primary, matched, reasons


# ---------------------------------------------------------------------
# Trade levels
# ---------------------------------------------------------------------

def trade_levels(df, m):
    """
    Structure-based entry, stop and targets.

    Entry: a buy stop just above yesterday's high. This is a TRIGGER, not a
    market order - it only fills if the stock actually turns up, which keeps
    you out of names that keep falling.

    Stop: below the 10-day swing low, with a small ATR buffer so ordinary
    noise doesn't take you out. Capped at 2x ATR so a wide base doesn't
    produce an absurd risk per share.

    Targets: 2R and 3R, where R is the distance from entry to stop.
    """
    atr = m["atr14"]
    prior_high = float(df["High"].iloc[-1])
    swing_low = float(df["Low"].tail(10).min())

    entry = round(prior_high + 0.05 * atr, 2)

    structural_stop = swing_low - 0.25 * atr
    max_risk_stop = entry - 2.0 * atr
    stop = round(max(structural_stop, max_risk_stop), 2)

    risk = entry - stop
    if risk <= 0:
        return None

    return {
        "entry": entry,
        "stop": stop,
        "target_2r": round(entry + 2 * risk, 2),
        "target_3r": round(entry + 3 * risk, 2),
        "risk_per_share": round(risk, 2),
        "risk_pct": round(risk / entry * 100, 2),
        "stop_basis": ("10-day swing low" if structural_stop > max_risk_stop
                       else "2x ATR cap"),
    }
