# Design Principles

## Founder Principles

1. **The first milestone is reliable observability, not prediction.** Run 100 prompts. Produce complete, traceable logs for every model call, tool call, token, source URL, and API-equivalent imputed cost.
2. **Logging-first, profiling-second, prediction-third.** The core asset is the traceable execution dataset. The calibration loop cannot close without ground-truth logs.
3. **Start with two tools and no-tool.** `web_search`, `calculator`, and the no-tool case are enough to prove the loop.
4. **Configure the target agent explicitly before generating any data.** Never mix data from different agent configurations without tracking the config.
5. **All external access must go through registered, observed tools.** Never trust the model to self-report tool usage.
6. **Do not generate synthetic tasks with an LLM before the logging loop works.** Templates first.
7. **Synthetic data is for cold start, not final truth.** Production runs are the signal that matters most.
8. **Do not build the dashboard before the CLI.** The CLI validates the prediction loop at a fraction of the cost.
9. **Do not use Postgres before SQLite becomes limiting.** Zero infrastructure is a feature for a solo founder.
10. **Do not train ML before enough logs exist.** Rule-based routing is good enough until there are hundreds of labeled runs per tool.
11. **Budget protection is a core product feature.** Every prediction must return a budget decision. Never ship without it.
12. **Privacy-safe logging is the default.** Hash production prompts. Store source URLs even when raw text is not stored.
13. **Every prediction must explain its main cost drivers.** A number without explanation is not a product.
14. **Every expensive prediction must suggest how to reduce cost.** Cost reduction advice is the upsell.
15. **CLI > API > dashboard.** For a solo founder, in that order.

## System Principles

16. **Predict distributions, not single numbers.** Always return p50 and p90.
17. **`tool_schema_tokens` is a fixed cost for all exposed tools.** Always list it first in cost drivers when it is non-trivial.
18. **Profile `result_tokens_inserted`, not `result_tokens_raw`.** Truncation policy determines the gap; only inserted tokens affect model input cost.
19. **`trace_id` connects prediction, execution, model calls, tool calls, and source URLs.** Every record should be traceable end-to-end.
20. **Separate token cost from service cost.** MCP tool API fees are not model context tokens.
21. **Make profiles model-specific.** The same tool returns different token counts under different tokenizers.
22. **Calibrate continuously.** Store both predictions and actuals for every run; treat accuracy as a product metric.
23. **Fail gracefully.** If a tool has no profile, use the fallback hierarchy and signal the gap.
24. **Design for extensibility.** Adding a new tool requires only a registry entry.
25. **Never make a model call during `fast_predict`.** The default prediction path must return in < 200 ms.
26. **Optimize for underestimation prevention before perfect routing accuracy.** An overestimate is annoying; an underestimate breaks the budget guard.
27. **Source URLs are first-class observability data.** Store them even when raw result text is not stored.
28. **If a tool or MCP server does not return source metadata, mark `source_traceability_status` as `partial`.** Never silently drop traceability information.
29. **Separate billing mode from cost basis.** A subscription-based runtime (e.g. Claude Code Pro) can still produce API-equivalent cost estimates from observed token usage, but these estimates must be labelled `cost_basis = "api_equivalent_imputed"` rather than `"actual_api_billed"`. Use `actual_api_equivalent_cost_usd` for all profiling, p50/p90 estimation, and budget guard comparisons; use `actual_cash_cost_usd` only for founder-level subscription accounting.
30. **The integration entry point must require zero infrastructure.** A user who already has `from anthropic import Anthropic` in their code must be able to start tracking with one line change and no config file. Auto-initialize storage on first use. Progressive disclosure: tracking → profiling → prediction. Never require the full executor pipeline to unlock the first value.
31. **Local-first, cloud-enhanced.** Every feature works fully offline. The community network adds value on top — it never gates local functionality. A user who opts out of sync loses nothing except access to community profiles.
32. **The raw data lake is admin-only. Community profiles are public.** Raw synced records — including prompt hashes and agent configs — are accessible only to the project admin via admin-scoped keys. Pre-computed community profiles (p50/p90 aggregates) are published by the admin and downloaded by any ACF install. No contributor or end-user can query the lake directly.
33. **Sync configuration context, not content.** Token counts, model names, tool names, cost estimates, latency, source domains, agent config metadata (temperature, truncation policy, budget limits, privacy mode), and prompt/system-prompt hashes are safe to sync. Raw prompt text, tool arguments, result content, and full source URLs are never synced.
34. **The community data flywheel is the long-term moat.** Every contributor makes predictions better for everyone. Recognize contributors publicly. The network effect — more data → richer per-config profiles → better cold-start predictions → more users — is the product's compounding advantage.
