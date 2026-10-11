#!/usr/bin/env python3
"""Create one gateway virtual key per student, with a quarter budget.

Usage:
    python provision_students.py roster.csv [--budget-usd 400] [--gateway URL]

roster.csv columns: name,email,github
Writes keys.csv (email,key) — distribute individually; never commit.
"""

import argparse
import csv
import os
import sys

import requests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("roster")
    ap.add_argument("--budget-usd", type=float, default=400.0,
                    help="hard spend cap per student for the quarter")
    ap.add_argument("--gateway",
                    default=os.environ.get("GATEWAY_URL", "http://localhost:4000"))
    args = ap.parse_args()

    master_key = os.environ.get("LITELLM_MASTER_KEY")
    if not master_key:
        sys.exit("set LITELLM_MASTER_KEY")

    out = []
    with open(args.roster) as f:
        for row in csv.DictReader(f):
            resp = requests.post(
                f"{args.gateway}/key/generate",
                headers={"Authorization": f"Bearer {master_key}"},
                json={
                    "key_alias": row["email"],
                    "max_budget": args.budget_usd,  # hard cap: refused beyond this
                    "metadata": {
                        "name": row["name"],
                        "github": row["github"],
                        "cohort": "winter-2027",
                    },
                },
                timeout=30,
            )
            resp.raise_for_status()
            out.append({"email": row["email"], "key": resp.json()["key"]})
            print(f"provisioned {row['email']}")

    with open("keys.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["email", "key"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"\n{len(out)} keys written to keys.csv — distribute individually; do not commit.")


if __name__ == "__main__":
    main()
