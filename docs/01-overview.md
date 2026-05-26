# Agent Cost Forecaster — Overview

## Project Overview

Agent Cost Forecaster is a logging-first cost profiler and budget guard for tool-using AI agents. It instruments a real target agent, observes every model call, tool call, token count, and source URL, and builds empirical p50/p90 profiles from those logs. Once enough runs are logged, those profiles drive cost predictions for future runs.

The system is self-improving: every execution feeds back into the profiling and calibration loop. The four stages — Log → Profile → Predict → Validate — are described in the [README](../README.md).

Every install also participates in the **ACF Community Data Network**. When sync is enabled, anonymized token usage records are batched and sent to the central data lake. Community profiles — p50/p90 distributions trained on all contributors — are downloaded and used as the highest-priority fallback in the prediction engine. See [03-community-network.md](03-community-network.md) for the full sync design.

Anything not on the six-week critical path is marked **later-stage** or **Phase 5+** throughout these docs.

---

## Founder Reality Check

The long-term product is a self-improving cost forecasting system for tool-using AI agents. The first thing to prove is not prediction — it is **reliable observability**.

> **A logging-first cost profiler and budget guard for tool-using AI agents.**

Before logs exist, prediction can only use conservative heuristics. Real prediction quality begins only after enough runs are logged and profiled. The core asset is the traceable execution dataset, not the prediction algorithm.

> **logging-first → profiling-second → prediction-third**
