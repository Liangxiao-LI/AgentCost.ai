# Agent Cost Forecaster — Overview

## Project Overview

Agent Cost Forecaster is a logging-first cost profiler and budget guard for tool-using AI agents. It instruments a real target agent, observes every model call, tool call, token count, and source URL, and builds empirical p50/p90 profiles from those logs. Once enough runs are logged, those profiles drive cost predictions for future runs.

The system is self-improving: every execution feeds back into the profiling and calibration loop.

```
Stage 1 — Log:      acf run              → observe model calls + tool calls → log tokens, URLs, api_equivalent_cost_usd
Stage 2 — Profile:  acf profiles         → compute p50/p90 per tool and prompt category
Stage 3 — Predict:  acf predict          → estimate cost from empirical profiles → apply budget guard
Stage 4 — Validate: acf run-batch --heldout → compare predicted vs actual → p90 coverage
```

Every install also participates in the **ACF Community Data Network**. When sync is enabled (default), anonymized token usage records are batched and sent to the central data lake. Community profiles — p50/p90 distributions trained on all contributors — are downloaded and used as the highest-priority fallback in the prediction engine. The more contributors join, the more accurate the estimates become for everyone.

This document is organized from product thesis → MVP → runtime → data model → CLI/API → roadmap. Full-system complexity is introduced only after the MVP scope is clear. Anything not on the six-week critical path is marked **later-stage**.

---

## Founder Reality Check

The long-term product is a self-improving cost forecasting system for tool-using AI agents. The first thing to prove is not prediction — it is **reliable observability**.

> **A logging-first cost profiler and budget guard for tool-using AI agents.**

Before logs exist, prediction can only use conservative heuristics. Real prediction quality begins only after enough runs are logged and profiled. The core asset is the traceable execution dataset, not the prediction algorithm.

> **logging-first → profiling-second → prediction-third**
