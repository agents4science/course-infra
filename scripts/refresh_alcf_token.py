#!/usr/bin/env python3
"""Create/rotate the Argonne-lane models in the running gateway.

ALCF Inference Endpoints use Globus access tokens that expire after hours,
and LiteLLM config-file models cannot be updated via the admin API --- so the
Argonne lane is DB-managed: this script deletes any existing ALCF-lane
deployments and recreates them with a fresh token. Run once to create the
lane, then from cron (e.g. every 4h) to keep it live.

Requires one-time interactive `uvx --from alcf-ai alcf-ai auth login`.
Env: LITELLM_MASTER_KEY, GATEWAY_URL (default http://localhost:4000),
     ALCF_BASE_URL (default Sophia vLLM endpoint)
"""

import os
import subprocess
import sys

import requests

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:4000")
ALCF_HOST = "inference-api.alcf.anl.gov"
ALCF_BASE = os.environ.get(
    "ALCF_BASE_URL",
    "https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1")

# Lane models: gateway alias -> served-model name + shadow pricing ($/M tokens).
# ALCF inference is free to the course, but usage is PRICED against student
# budgets (policy decision 2026-10-12: cost-awareness applies on every lane;
# Argonne lane priced ~half of frontier so the tradeoff is real, not zero).
# Keep aliases stable; update served names as the ALCF catalog changes.
LANE = {
    "argonne-coder": {
        "served": "Qwen3-Coder-480B-A35B-Instruct-AWQ",  # verified running 2026-10-12
        "input_per_m": 0.25,
        "output_per_m": 1.00,
    },
}


def fresh_token() -> str:
    out = subprocess.run(
        ["uvx", "--from", "alcf-ai", "alcf-ai", "auth", "get-access-token"],
        capture_output=True, text=True, check=True)
    token = out.stdout.strip().splitlines()[-1]
    if not token:
        sys.exit("empty token; run `alcf-ai auth login` once interactively")
    return token


def main() -> None:
    master = os.environ.get("LITELLM_MASTER_KEY") or sys.exit("set LITELLM_MASTER_KEY")
    hdr = {"Authorization": f"Bearer {master}"}
    token = fresh_token()

    info = requests.get(f"{GATEWAY}/model/info", headers=hdr, timeout=30)
    info.raise_for_status()
    for m in info.json()["data"]:
        if ALCF_HOST in str((m.get("litellm_params") or {}).get("api_base") or ""):
            mid = m["model_info"]["id"]
            r = requests.post(f"{GATEWAY}/model/delete", headers=hdr,
                              json={"id": mid}, timeout=30)
            if r.status_code == 200:
                print(f"deleted stale deployment {m['model_name']} ({mid[:8]})")

    for alias, spec in LANE.items():
        r = requests.post(f"{GATEWAY}/model/new", headers=hdr, json={
            "model_name": alias,
            "litellm_params": {
                "model": f"openai/{spec['served']}",
                "api_base": ALCF_BASE,
                "api_key": token,
                "input_cost_per_token": spec["input_per_m"] / 1e6,
                "output_cost_per_token": spec["output_per_m"] / 1e6,
            },
        }, timeout=30)
        r.raise_for_status()
        print(f"created {alias} -> {spec['served']} "
              f"(${spec['input_per_m']}/M in, ${spec['output_per_m']}/M out)")


if __name__ == "__main__":
    main()
