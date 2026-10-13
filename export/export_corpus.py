#!/usr/bin/env python3
"""Export pipeline (I7): Phoenix sessions -> de-identified JSONL corpus.

    python export/export_corpus.py --out corpus.jsonl \
        [--consented consented.txt] [--include-all] [--salt-file salt.txt]

This is STAGE 1 of the four-stage de-identification in the IRB protocol:
automated transforms only. Stages 2-4 (manual spot check, blinded coder
review, participant self-review window) happen on the stage-1 output
before anything is released.

Stage-1 transforms applied here:
  - consent filter: only sessions whose participant id is in --consented
    (one id per line; --include-all overrides, for sim/dev data only)
  - pseudonymization: participant id -> P-<salted-hash-prefix>; the salt file
    stays with the coordinator (coded-data key), never in the corpus
  - session-relative timestamps: wall-clock start removed; each LLM call
    carries t_rel seconds from session start
  - text redaction stubs: emails, phone numbers, CNetIDs; the name list and
    free-text NER pass are TODO (stage 1 is not the last line of defense)

One JSON object per line = one session.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "simulation"))
import make_replay  # noqa: E402

REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\bcnetid[:\s]*\w+", re.I), "[CNETID]"),
    # TODO stage-1+: roster-driven name list; NER pass for free-text names
]


def redact(text: str) -> str:
    for pat, repl in REDACTIONS:
        text = pat.sub(repl, text)
    return text


def pseudonym(ident: str, salt: str) -> str:
    return "P-" + hashlib.sha256((salt + ident).encode()).hexdigest()[:10]


def parse_ts(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def export_sessions(spans, consented, salt, include_all):
    roots = [s for s in spans if s["parentId"] is None
             and not s["name"].startswith(("Received", "self"))]
    for root in sorted(roots, key=lambda s: s["startTime"]):
        a = json.loads(root["attributes"])
        if not isinstance(a.get("input"), dict):      # unfinished/foreign root
            continue
        participant = a.get("user", {}).get("id", "")
        if not include_all and participant not in consented:
            continue
        trace_id = root["context"]["traceId"]
        t0 = parse_ts(root["startTime"])
        calls = sorted((s for s in spans
                        if s["context"]["traceId"] == trace_id
                        and s["name"] == "raw_gen_ai_request"),
                       key=lambda s: s["startTime"])
        steps = []
        for c in calls:
            import ast
            at = json.loads(c["attributes"]).get("llm", {}).get("openai", {})
            msgs = ast.literal_eval(at.get("messages", "[]")) if at.get("messages") else []
            choices = ast.literal_eval(at.get("choices", "[]")) if at.get("choices") else []
            usage = ast.literal_eval(at.get("usage", "{}")) if at.get("usage") else {}
            steps.append({
                "t_rel": round(parse_ts(c["startTime"]) - t0, 2),
                "messages": [{"role": m.get("role", "?"),
                              "content": redact(str(m.get("content", "")))}
                             for m in msgs],
                "reply": redact(choices[0]["message"]["content"] if choices else ""),
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
                "latency_s": round(float(at.get("response_time", 0) or 0), 2),
                "model": at.get("model", ""),
            })
        yield {
            "schema": "agent-trace-corpus/v0",
            "participant": pseudonym(participant, salt),
            "session": pseudonym(root["name"], salt),
            "task": redact(a.get("input", {}).get("value", "")),
            "result": redact(a.get("output", {}).get("value", "")),
            "n_calls": len(steps),
            "steps": steps,
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--phoenix", default="http://localhost:6006")
    ap.add_argument("--consented", type=Path,
                    help="file of participant ids with signed consent, one per line")
    ap.add_argument("--include-all", action="store_true",
                    help="bypass consent filter (sim/dev data ONLY)")
    ap.add_argument("--salt-file", type=Path, default=Path("export/.salt"),
                    help="pseudonymization salt; stays with the coordinator")
    args = ap.parse_args()

    consented = (set(args.consented.read_text().split())
                 if args.consented else set())
    if not consented and not args.include_all:
        sys.exit("no consented ids and --include-all not set; nothing to export")
    if not args.salt_file.exists():
        import secrets
        args.salt_file.write_text(secrets.token_hex(16))
        print(f"new salt written to {args.salt_file} — keep with coordinator, never release")
    salt = args.salt_file.read_text().strip()

    spans = make_replay.fetch_spans(args.phoenix)
    n = 0
    with args.out.open("w") as f:
        for rec in export_sessions(spans, consented, salt, args.include_all):
            f.write(json.dumps(rec) + "\n")
            n += 1
    print(f"exported {n} sessions -> {args.out}")


if __name__ == "__main__":
    main()
