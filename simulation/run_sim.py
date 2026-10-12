#!/usr/bin/env python3
"""Run a simulated cohort through a lab spec, via the real gateway.

Usage:
    python run_sim.py lab_specs/week1_bare_agent.yaml [--gateway URL]

Requires sim cohort keys: provision first with
    python ../scripts/provision_students.py sim_roster.csv --budget-usd 50
(then copy keys.csv to simulation/sim_keys.csv)

Outputs a per-persona report: calls, errors, tokens, and gateway-side spend.
"""

import argparse
import concurrent.futures as cf
import csv
import json
import os
import random
import sys
import time

import requests
import yaml

LONG_PAD = "Background context: " + ("lorem agentis " * 400)
MED_PAD = "Context: " + ("data point; " * 80)


def session(persona: dict, key: str, lab: dict, gateway: str) -> dict:
    stats = {"id": persona["id"], "calls": 0, "ok": 0, "errors": 0,
             "prompt_tokens": 0, "completion_tokens": 0, "t_start": time.time()}
    turns = lab["session_turns"]
    n = persona["calls_per_lab"]
    pad = {"short": "", "medium": MED_PAD, "long": LONG_PAD}[persona.get("prompt_tokens", "short")]
    for i in range(n):
        body = {
            "model": lab["model"] if random.random() > persona.get("error_rate", 0) else "no-such-model",
            "messages": [{"role": "user", "content": pad + turns[i % len(turns)]}],
        }
        try:
            r = requests.post(f"{gateway}/v1/chat/completions",
                              headers={"Authorization": f"Bearer {key}"},
                              json=body, timeout=60)
            stats["calls"] += 1
            if r.status_code == 200:
                stats["ok"] += 1
                u = r.json().get("usage") or {}
                stats["prompt_tokens"] += u.get("prompt_tokens", 0)
                stats["completion_tokens"] += u.get("completion_tokens", 0)
            else:
                stats["errors"] += 1
        except requests.RequestException:
            stats["calls"] += 1
            stats["errors"] += 1
        time.sleep(persona.get("pacing_s", 1.0))
    stats["wall_s"] = round(time.time() - stats["t_start"], 1)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lab_spec")
    ap.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://localhost:4000"))
    ap.add_argument("--keys", default="sim_keys.csv")
    args = ap.parse_args()

    lab = yaml.safe_load(open(args.lab_spec))
    personas = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "personas.yaml")))["personas"]
    keys = {row["email"]: row["key"] for row in csv.DictReader(open(args.keys))}

    jobs = []
    for p in personas:
        email = f"{p['id']}@sim.invalid"
        if email not in keys:
            sys.exit(f"no key for {email}; provision the sim roster first")
        jobs.append((p, keys[email]))

    print(f"running lab '{lab['id']}' with {len(jobs)} sim students against {args.gateway}\n")
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        results = list(ex.map(lambda j: session(j[0], j[1], lab, args.gateway), jobs))

    print(f"{'persona':<14}{'calls':>6}{'ok':>5}{'err':>5}{'ptok':>8}{'ctok':>7}{'wall_s':>8}")
    for r in sorted(results, key=lambda x: x["id"]):
        print(f"{r['id']:<14}{r['calls']:>6}{r['ok']:>5}{r['errors']:>5}"
              f"{r['prompt_tokens']:>8}{r['completion_tokens']:>7}{r['wall_s']:>8}")
    print(json.dumps({"lab": lab["id"], "results": results}, indent=None), file=open("last_run.json", "w"))
    print("\nwrote last_run.json; gateway-side truth: check /key/info and spend logs per key")


if __name__ == "__main__":
    main()
