#!/usr/bin/env python3
"""Refresh the Argonne-lane Globus token in the running gateway.

ALCF Inference Endpoints use Globus access tokens that expire after hours.
This script (1) obtains a fresh token via the alcf-ai CLI (requires one-time
interactive `alcf-ai auth login` by the operator), then (2) updates every
gateway model deployment whose api_base points at the ALCF service.

Run from cron, e.g.:  0 */4 * * *  .../refresh_alcf_token.py

Env: LITELLM_MASTER_KEY, GATEWAY_URL (default http://localhost:4000)
"""

import os
import subprocess
import sys

import requests

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:4000")
ALCF_HOST = "inference-api.alcf.anl.gov"


def fresh_token() -> str:
    out = subprocess.run(
        ["uvx", "--from", "alcf-ai", "alcf-ai", "auth", "get-access-token"],
        capture_output=True, text=True, check=True,
    )
    token = out.stdout.strip()
    if not token:
        sys.exit("alcf-ai returned empty token; run `alcf-ai auth login` once interactively")
    return token


def main() -> None:
    master = os.environ.get("LITELLM_MASTER_KEY") or sys.exit("set LITELLM_MASTER_KEY")
    hdr = {"Authorization": f"Bearer {master}"}
    token = fresh_token()

    info = requests.get(f"{GATEWAY}/model/info", headers=hdr, timeout=30)
    info.raise_for_status()
    updated = 0
    for m in info.json()["data"]:
        base = (m.get("litellm_params") or {}).get("api_base") or ""
        if ALCF_HOST in base:
            resp = requests.post(
                f"{GATEWAY}/model/update",
                headers=hdr,
                json={"model_id": m["model_info"]["id"],
                      "litellm_params": {**m["litellm_params"], "api_key": token}},
                timeout=30,
            )
            resp.raise_for_status()
            updated += 1
            print(f"refreshed token for {m['model_name']}")
    if updated == 0:
        print("no ALCF-lane models found in gateway (check api_base config)")


if __name__ == "__main__":
    main()
