# Architecture Decision Records — Sprint 0

## ADR-1: Gateway base = LiteLLM Proxy (accepted 2026-10-11)

**Decision.** Build I1 on LiteLLM Proxy rather than from scratch or on a commercial AI gateway.

**Why.** Out of the box it provides: per-student *virtual keys* with independent budgets and rate limits; hard spend caps (`max_budget`) with automatic refusal — the I2 enforcement primitive; OpenAI-compatible routing to multiple providers, covering both lanes (commercial APIs and the ALCF inference service's OpenAI-compatible endpoint) behind one base URL; per-key spend tracking in Postgres; and logging callbacks for full request/response trace capture. Open source and widely deployed; students use standard OpenAI-style clients.

**Consequences.** Sprint 1 is configuration + hardening + a trace-capture callback, not proxy construction. We accept dependency on LiteLLM's release cadence and pin a version at the January freeze.

**Alternatives rejected.** From-scratch FastAPI proxy (weeks replicating key/budget machinery); commercial gateways (closed; data-handling questions under the IRB protocol).

## ADR-2: Trace schema = gateway-native JSON, OpenInference-compatible (accepted)

Every request/response pair is captured by gateway callback as JSON (session id, event sequence, model, params, token counts, cost, tool metadata, content), stored in Postgres and exportable as JSONL per session. Field names follow OpenTelemetry GenAI / OpenInference conventions where they exist so standard viewers work without translation. The IRB export pipeline (I7) consumes this format; released corpora convert absolute timestamps to session-relative times (IRB commitment).

## ADR-3: Trace viewer = Arize Phoenix (accepted 2026-10-12)

**Decision.** Phoenix, fed by LiteLLM's OpenTelemetry callback (`callbacks: ["otel"]` → OTLP http → Phoenix).

**Verified against real traffic** (94-call simulated cohort + live ALCF requests): full prompt and response content captured, model/usage/timing attributes present, and per-student identity available in span metadata (`user_api_key_auth_metadata`: name, cohort) — sufficient for in-class autopsies ("show this student's session"). Single-container deployment suits a one-TA operation; Langfuse remains the fallback if quarter use reveals gaps (its deployment is substantially heavier: clickhouse + redis + object store).

**Session grouping (wired 2026-10-12).** Every request carries `metadata: {session_id, student, step}` (plus the OpenAI `user` field), which the gateway propagates into span attributes as `requester_metadata` — verified. Sessions are retrieved in Phoenix by searching/filtering on the session id (e.g., `week1live-diligent-1012-0603`). Remaining: adopt the same convention in the student starter kit and lab templates so student traces group without effort; note Phoenix's native sessions view keys on the OpenInference `session.id` attribute, which LiteLLM does not emit — attribute search is the working mechanism.

## ADR-4: Sandbox = Docker with resource limits and default-deny networking (accepted)

Labs: students run the course sandbox image locally (week-0 setup installs Docker). Bake-offs and projects: the course sandbox service on the AWS VM runs submissions in containers with CPU/memory/time limits and no network by default, with allow-listed egress (gateway + specific data hosts) when a task requires it. Firecracker/gVisor deferred; plain Docker with hard limits fits the course threat model — revisit if red-team week says otherwise.

Implemented 2026-10-13: `sandbox/Dockerfile` (python:3.12-slim + course_kit from the agent-starter repo, unprivileged user) and `sandbox/run_sandboxed.py` (1 CPU / 1 GB / 256 pids / read-only mount / timeout; joins the compose `sandbox` network, which is `internal: true`, so only gateway and Phoenix are reachable — egress verified blocked). Key is injected as env, never on disk.

## ADR-5: Hosting = AWS via UChicago enterprise agreement (decided 2026-10-11)

One always-on instance (gateway, Postgres, viewer, dashboards) plus burst capacity for sandbox runners. Security configuration per the IRB commitments (see README).
