#!/usr/bin/env python3
"""Run a student submission in the course sandbox.

    python sandbox/run_sandboxed.py path/to/submission_dir \
        --key sk-... --entry agent.py --task "..." [--timeout 300]

Guarantees:
  - runs as unprivileged user in the course image (pinned deps, course_kit baked in)
  - joins the compose network, so the ONLY reachable services are the gateway
    and Phoenix (no internet: --network has no default route out via the
    internal flag on the sandbox network)
  - 1 CPU, 1 GB RAM, 256 pids, read-only submission mount, wall-clock timeout
  - the student's gateway key is injected as an env var, never written to disk

Exit code is the submission's exit code; 124 on timeout.
"""

import argparse
import subprocess
import sys
from pathlib import Path

IMAGE = "agents4science/sandbox:latest"
NETWORK = "course-infra_sandbox"


def run(submission: Path, key: str, entry: str, task: str, timeout: int) -> int:
    cmd = [
        "docker", "run", "--rm",
        "--network", NETWORK,
        "--cpus", "1", "--memory", "1g", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp:size=64m",
        "-v", f"{submission.resolve()}:/submission:ro",
        "-e", f"AGENTS_GATEWAY_KEY={key}",
        "-e", "AGENTS_GATEWAY_URL=http://gateway:4000",
        "-e", "AGENTS_TRACE_URL=http://phoenix:6006/v1/traces",
        "-e", f"AGENTS_STUDENT={submission.name}",
        IMAGE, "timeout", str(timeout), "python", entry, task,
    ]
    proc = subprocess.run(cmd)
    return proc.returncode


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("submission", type=Path)
    ap.add_argument("--key", required=True)
    ap.add_argument("--entry", default="agent.py")
    ap.add_argument("--task", default="What is 123456 * 654321?")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    sys.exit(run(a.submission, a.key, a.entry, a.task, a.timeout))
