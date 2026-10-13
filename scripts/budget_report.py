#!/usr/bin/env python3
"""Budget governor (I2): spend vs cap for every course key, with warning tiers.

    python scripts/budget_report.py [--json out.json] [--warn-only]

Tiers: OK < 50% <= NOTICE < 80% <= WARNING < 95% <= CRITICAL (100% = key dead,
the gateway's hard cap already enforces that). Run from cron; pipe --warn-only
output to the course channel or the mailer (TODO when roster emails are live).
"""

import argparse
import json
import os
import sys

import requests

GATEWAY = os.environ.get("AGENTS_GATEWAY_URL", "http://localhost:4000")
MASTER = os.environ.get("LITELLM_MASTER_KEY")

TIERS = [(0.95, "CRITICAL"), (0.80, "WARNING"), (0.50, "NOTICE"), (0.0, "OK")]


def list_keys():
    keys, page = [], 1
    while True:
        r = requests.get(f"{GATEWAY}/key/list",
                         params={"return_full_object": "true",
                                 "page": page, "size": 100},
                         headers={"Authorization": f"Bearer {MASTER}"},
                         timeout=15)
        r.raise_for_status()
        batch = r.json().get("keys", [])
        keys += batch
        if len(batch) < 100:
            return keys
        page += 1


def tier(frac: float) -> str:
    return next(name for cut, name in TIERS if frac >= cut)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=argparse.FileType("w"))
    ap.add_argument("--warn-only", action="store_true",
                    help="only print WARNING and CRITICAL rows")
    args = ap.parse_args()
    if not MASTER:
        sys.exit("set LITELLM_MASTER_KEY")

    rows = []
    for k in list_keys():
        cap = k.get("max_budget")
        if not cap:          # master/service keys: no cap, not a student
            continue
        spend = float(k.get("spend") or 0.0)
        frac = spend / cap
        rows.append({"student": k.get("key_alias") or k["key_name"],
                     "spend": round(spend, 4), "cap": cap,
                     "pct": round(100 * frac, 1), "tier": tier(frac),
                     "blocked": bool(k.get("blocked"))})

    rows.sort(key=lambda r: -r["pct"])
    if args.json:
        json.dump(rows, args.json, indent=2)
    shown = [r for r in rows
             if not args.warn_only or r["tier"] in ("WARNING", "CRITICAL")]
    if not shown:
        print("all keys below warning thresholds")
        return
    w = max(len(r["student"]) for r in shown)
    for r in shown:
        print(f"{r['student']:{w}s}  ${r['spend']:>9.4f} / ${r['cap']:<7.2f} "
              f"{r['pct']:5.1f}%  {r['tier']}"
              + ("  [BLOCKED]" if r["blocked"] else ""))


if __name__ == "__main__":
    main()
