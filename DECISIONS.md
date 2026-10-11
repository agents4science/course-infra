# Architecture Decision Records — Sprint 0

## ADR-1: Gateway base = LiteLLM Proxy (accepted 2026-10-11)

**Decision.** Build I1 on LiteLLM Proxy rather than from scratch or on a commercial AI gateway.

**Why.** Out of the box it provides: per-student *virtual keys* with independent budgets and rate limits; hard spend caps (`max_budget`) with automatic refusal — the I2 enforcement primitive; OpenAI-compatible routing to multiple providers, covering both lanes (commercial APIs and the ALCF inference service's OpenAI-compatible endpoint) behind one base URL; per-key spend tracking in Postgres; and logging callbacks for full request/response trace capture. Open source and widely deployed; students use standard OpenAI-style clients.

**Consequences.** Sprint 1 is configuration + hardening + a trace-capture callback, not proxy construction. We accept dependency on LiteLLM's release cadence and pin a version at the January freeze.

**Alternatives rejected.** From-scratch FastAPI proxy (weeks replicating key/budget machinery); commercial gateways (closed; data-handling questions under the IRB protocol).

## ADR-2: Trace schema = gateway-native JSON, OpenInference-compatible (accepted)

Every request/response pair is captured by gateway callback as JSON (session id, event sequence, model, params, token counts, cost, tool metadata, content), stored in Postgres and exportable as JSONL per session. Field names follow OpenTelemetry GenAI / OpenInference conventions where they exist so standard viewers work without translation. The IRB export pipeline (I7) consumes this format; released corpora convert absolute timestamps to session-relative times (IRB commitment).

## ADR-3: Trace viewer — A/B in sprint 2 (open)

Candidates: **Langfuse** (self-hosted; native LiteLLM integration; heavier deployment) vs. **Arize Phoenix** (single container; OpenInference-native; lighter). Decide by running both against real traces in sprint 2. Requirement: good enough to scrub a session live in class during autopsies.

## ADR-4: Sandbox = Docker with resource limits and default-deny networking (accepted)

Labs: students run the course sandbox image locally (week-0 setup installs Docker). Bake-offs and projects: the course sandbox service on the AWS VM runs submissions in containers with CPU/memory/time limits and no network by default, with allow-listed egress (gateway + specific data hosts) when a task requires it. Firecracker/gVisor deferred; plain Docker with hard limits fits the course threat model — revisit if red-team week says otherwise.

## ADR-5: Hosting = AWS via UChicago enterprise agreement (decided 2026-10-11)

One always-on instance (gateway, Postgres, viewer, dashboards) plus burst capacity for sandbox runners. Security configuration per the IRB commitments (see README).
