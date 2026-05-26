# Agent Cost Forecaster — Documentation

> A logging-first cost profiler and budget guard for tool-using AI agents.

This folder contains the full architecture split into focused documents. Read them in order for a complete picture, or jump to the section you need.

---

## Reading Order

| # | File | What it covers |
|---|------|----------------|
| 1 | [01-overview.md](01-overview.md) | What ACF is, the four-stage loop, founder reality check |
| 2 | [02-sdk-integration.md](02-sdk-integration.md) | Drop-in integration for existing Anthropic/OpenAI users |
| 3 | [03-community-network.md](03-community-network.md) | Community data lake, privacy model, sync layer |
| 4 | [04-mvp-scope.md](04-mvp-scope.md) | Milestones, goals/non-goals, core concepts |
| 5 | [05-architecture.md](05-architecture.md) | MVP file structure, module consolidation, SQLite decision |
| 6 | [06-claude-code-runtime.md](06-claude-code-runtime.md) | Claude Code as first target, SDK specifics, cost accounting |
| 7 | [07-execution-logging.md](07-execution-logging.md) | Observed wrapper, source URL tracking, privacy modes |
| 8 | [08-profiling-calibration.md](08-profiling-calibration.md) | Synthetic tasks, sample quality, fallback hierarchy, calibration |
| 9 | [09-prediction-budget.md](09-prediction-budget.md) | Cost formula, prediction flow, budget guard, cost drivers |
| 10 | [10-modules.md](10-modules.md) | Module reference, system diagram |
| 11 | [11-data-model.md](11-data-model.md) | All database tables, minimal MVP SQL schema |
| 12 | [12-api.md](12-api.md) | Local API + community network endpoints |
| 13 | [13-cli.md](13-cli.md) | All CLI commands + example trace |
| 14 | [14-roadmap.md](14-roadmap.md) | Six-week MVP roadmap + later-stage phases |
| 15 | [15-design-principles.md](15-design-principles.md) | All 33 design principles |

---

## Quick Navigation by Role

**I just installed ACF and want to start tracking** → [02-sdk-integration.md](02-sdk-integration.md)

**I want to understand the community data network** → [03-community-network.md](03-community-network.md)

**I'm building the MVP** → [05-architecture.md](05-architecture.md), [07-execution-logging.md](07-execution-logging.md), [11-data-model.md](11-data-model.md)

**I want to understand cost prediction** → [09-prediction-budget.md](09-prediction-budget.md)

**I need the database schema** → [11-data-model.md](11-data-model.md)

**I need the API reference** → [12-api.md](12-api.md)

**I need the CLI reference** → [13-cli.md](13-cli.md)

**I'm planning the six-week build** → [14-roadmap.md](14-roadmap.md)

---

The canonical single-file version is [../architecture.md](../architecture.md).
