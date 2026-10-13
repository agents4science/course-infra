#!/usr/bin/env python3
"""Bake-off harness: run every submission against a task set, score, rank.

    python bakeoff/run_bakeoff.py bakeoff/tasks/bakeoff1.yaml submissions_dir \
        --keys keys.csv [--out results/]

Layout: submissions_dir/<student>/agent.py  (entry overridable in the task file).
keys.csv: student,key rows (the provisioning output) — each submission runs
under its owner's key, so spend hits their budget and traces carry their name.

Per task we record: correct (check against stdout), wall-clock seconds, and
dollar cost (key spend delta via the gateway /key/info). Leaderboard ranks by
points, tiebreak lower cost then lower time. Outputs results.json +
leaderboard.md in --out.
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sandbox"))
from run_sandboxed import run as sandboxed_run  # noqa: E402

GATEWAY = "http://localhost:4000"


def key_spend(key: str, master: str) -> float:
    r = requests.get(f"{GATEWAY}/key/info", params={"key": key},
                     headers={"Authorization": f"Bearer {master}"}, timeout=10)
    r.raise_for_status()
    return float(r.json()["info"].get("spend") or 0.0)


def check_output(task: dict, stdout: str) -> bool:
    text = stdout.replace(",", "").lower()
    if "check" in task:
        return task["check"].lower() in text
    return any(c.lower() in text for c in task.get("check_any", []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("taskfile", type=Path)
    ap.add_argument("submissions", type=Path)
    ap.add_argument("--keys", type=Path, required=True)
    ap.add_argument("--master", default=None, help="gateway master key (or $LITELLM_MASTER_KEY)")
    ap.add_argument("--out", type=Path, default=Path("bakeoff_results"))
    args = ap.parse_args()

    import os
    master = args.master or os.environ.get("LITELLM_MASTER_KEY")
    if not master:
        sys.exit("need --master or LITELLM_MASTER_KEY for cost accounting")

    spec = yaml.safe_load(args.taskfile.read_text())
    # keys.csv has student,key or email,key; index by both id and email local part
    keys = {}
    for row in csv.DictReader(args.keys.open()):
        ident = row.get("student") or row["email"]
        keys[ident] = row["key"]
        keys[ident.split("@")[0]] = row["key"]

    results = []
    for sub in sorted(p for p in args.submissions.iterdir() if p.is_dir()):
        student = sub.name
        key = keys.get(student)
        if not key:
            print(f"!! no key for {student}, skipping", file=sys.stderr)
            continue
        row = {"student": student, "tasks": {}, "points": 0,
               "cost": 0.0, "seconds": 0.0}
        before = key_spend(key, master)
        for task in spec["tasks"]:
            t0 = time.monotonic()
            code, out, err = sandboxed_run(
                sub, key, spec.get("entry", "agent.py"), task["prompt"],
                spec.get("timeout", 180), capture=True,
                session=f"{spec['name']}-{student}-{task['id']}")
            dt = time.monotonic() - t0
            ok = code == 0 and check_output(task, out)
            row["tasks"][task["id"]] = {
                "correct": ok, "exit": code, "seconds": round(dt, 1),
                "stdout_tail": out[-400:], "stderr_tail": err[-400:]}
            row["points"] += task.get("points", 1) if ok else 0
            row["seconds"] += dt
            print(f"{student:20s} {task['id']:16s} "
                  f"{'PASS' if ok else 'fail':4s} {dt:6.1f}s")
        # gateway batches spend writes (~10 s); settle before reading the total
        time.sleep(12)
        row["cost"] = round(key_spend(key, master) - before, 6)
        row["seconds"] = round(row["seconds"], 1)
        results.append(row)
        print(f"{student:20s} {'TOTAL':16s} {row['points']} pts "
              f"{row['seconds']:6.1f}s ${row['cost']:.4f}")

    results.sort(key=lambda r: (-r["points"], r["cost"], r["seconds"]))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2))

    task_ids = [t["id"] for t in spec["tasks"]]
    lines = [f"# {spec['name']} leaderboard", "",
             "| rank | student | points | cost | time | " +
             " | ".join(task_ids) + " |",
             "|---|---|---|---|---|" + "---|" * len(task_ids)]
    for i, r in enumerate(results, 1):
        marks = " | ".join("✓" if r["tasks"][t]["correct"] else "✗"
                           for t in task_ids)
        lines.append(f"| {i} | {r['student']} | {r['points']} | "
                     f"${r['cost']:.4f} | {r['seconds']}s | {marks} |")
    (args.out / "leaderboard.md").write_text("\n".join(lines) + "\n")
    print(f"\nwrote {args.out}/results.json and leaderboard.md")


if __name__ == "__main__":
    main()
