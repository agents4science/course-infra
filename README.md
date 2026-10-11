# course-infra — Instruments for AI Agents for Science (Winter 2027)

Infrastructure for [CMSC 35370, Winter 2027](https://agents4science.github.io/2027/): the course gateway, trace capture, budgets, sandbox, and supporting tools. Design and requirements: [instrument development plan](https://agents4science.github.io/2027/instruments.html).

## Architecture

```
students ──(per-student virtual keys)──> GATEWAY (LiteLLM proxy)
                                           │  budgets, spend caps, routing
                                           ├──> commercial lane (OpenAI, Anthropic, ...)
                                           ├──> Argonne lane (ALCF inference, OpenAI-compatible)
                                           └──> trace capture ──> trace store + viewer
instructor/TAs ──> oversight dashboard (usage, budgets, sessions)
bake-offs/projects ──> sandbox runners (containers) ──> gateway
```

| Component | Instrument | Approach |
|---|---|---|
| Gateway | I1 | **LiteLLM Proxy** (decided; see DECISIONS.md): virtual keys, per-key budgets, routing, callbacks |
| Budget governor | I2 | LiteLLM budget primitives + policy layer (adapts [Bursar](https://agents4science.github.io/Bursar/) concepts) |
| Sandbox | I3 | Docker-based execution, resource-limited, default-deny network; MCP-mediated tools |
| Trace store/viewer | I4 | Gateway callbacks → Postgres + JSONL; viewer via Langfuse or Arize Phoenix (sprint-0 A/B, see DECISIONS.md) |
| Oversight dashboard | I5 | v0 = LiteLLM admin UI + trace viewer; custom fleet view later |
| Bake-off harness | I6 | Existing open eval tooling + task specs (sprint 3) |
| Consent/redaction | I7 | Post-quarter export pipeline (IRB-gated; session-relative timestamps) |

## Security requirements (IRB commitments — not optional)

TLS on all connections; encryption at rest; role-based admin access with University 2FA; students can access only their own sessions; access logging; no unauthenticated endpoints. See the instrument plan and IRB protocol.

## Quickstart (development)

```bash
cp .env.example .env            # fill in provider keys + master key
docker compose up -d            # gateway + postgres
python scripts/provision_students.py roster.csv   # one virtual key per student
```

Students then point any OpenAI-compatible client at `https://<gateway-host>/v1` with their personal key.

## Repository layout

- `gateway/config.yaml` — LiteLLM configuration: model lanes, budgets, logging
- `docker-compose.yml` — gateway + Postgres (dev); production deploys to the course AWS VM
- `scripts/provision_students.py` — create per-student keys with quarter budgets from a roster
- `DECISIONS.md` — architecture decision records (sprint 0)

## Status

Sprint 0 (October 2026). Target: gateway MVP by mid-November; freeze January 2, 2027. Timeline in the [instrument plan](https://agents4science.github.io/2027/instruments.html).
