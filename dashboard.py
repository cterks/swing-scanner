"""
Writes docs/data.json - the feed the web dashboard reads.

Kept separate from the report so the email and the dashboard can diverge
without breaking each other.
"""

import glob
import json
import os
from datetime import datetime


def write(rows, run_date, scanned, bench_return, out="docs/data.json"):
    os.makedirs(os.path.dirname(out), exist_ok=True)

    candidates = []
    for r in rows or []:
        candidates.append({
            "ticker": r["ticker"],
            "setup": r.get("setup"),
            "also": [s for s in r.get("all_setups", []) if s != r.get("setup")],
            "price": round(float(r["price"]), 2),
            "score": round(float(r.get("score", 0)), 3),
            "business": r.get("business"),
            "reasons": r.get("reasons", []),
            "entry": r.get("entry"),
            "stop": r.get("stop"),
            "stop_basis": r.get("stop_basis"),
            "risk_per_share": r.get("risk_per_share"),
            "risk_pct": r.get("risk_pct"),
            "target_2r": r.get("target_2r"),
            "target_3r": r.get("target_3r"),
            "fund_grade": r.get("fund_grade"),
            "fund_notes": r.get("fund_notes", []),
            "tv_url": r.get("tv_url"),
        })

    runs = sorted(os.path.basename(p)[7:-4]
                  for p in glob.glob("results/ranked_*.csv"))

    payload = {
        "run_date": run_date,
        "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "scanned": scanned,
        "bench_return_60d": round(float(bench_return) * 100, 2),
        "candidates": candidates,
        "past_runs": runs[-60:],
    }

    with open(out, "w") as f:
        json.dump(payload, f, indent=1)

    print(f"Wrote {out} ({len(candidates)} candidates)")
    return payload
