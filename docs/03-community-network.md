# Community Data Network, Privacy, and Sync

## Community Data Network

Every ACF install is a node in a shared intelligence network. Users contribute anonymized call data; the network returns better predictions than any single user could build alone.

### The Flywheel

```
More contributors → more anonymized call data
  → richer community profiles (p50/p90 per model × tool × config)
    → better predictions for every user, including day-0 cold-start
      → more contributors
```

Community profiles are the highest-priority fallback in the prediction engine. A new user installing ACF today gets day-1 predictions backed by millions of calls from the community — not just conservative hardcoded defaults.

### Contributor Identity

On first install, ACF generates a random anonymous `contributor_id` (UUID v4) and stores it in `~/.acf/contributor.json`. This is the only persistent identifier. It is never linked to a name, email, or IP address server-side. The contributor ID is included in every sync batch so the ingestion API can attribute contributions.

### First-Run Disclosure

Shown once on first install, before any sync occurs:

```
ACF Community Data Network
──────────────────────────────────────────────────────────────
ACF syncs anonymized usage data to a shared data lake to
improve cost predictions for everyone.

What IS synced:     model, token counts, tool names, cost
                    estimates, latency, source domains, agent
                    config metadata, prompt hash (not raw text)
What is NOT synced: raw prompts, tool arguments, result
                    content, full source URLs

Data access:        Raw data lake is readable only by the
                    project admin. Community profiles (pre-
                    computed aggregates) are public.

Your contributor ID: acf-7f3a...  (anonymous, stored locally)

To opt out at any time: acf sync --disable
Learn more: https://agentcost.ai/privacy
──────────────────────────────────────────────────────────────
```

### Access Control

| Role | Access |
|------|--------|
| **Admin** | Full raw data lake — all synced fields, arbitrary lake queries, contributor stats, profile recomputation |
| **Anyone** | `GET /v1/community/profiles` — pre-computed, published aggregates only |

The raw data lake is not accessible to contributors or the general public. All contributor-facing recognition (leaderboard, badges) is computed by the admin and served via the public website at `agentcost.ai/contributors`.

### Contributor Recognition

- Public contributors wall at `agentcost.ai/contributors` and pinned to the GitHub repo
- `acf contributor status` shows rank and badge (fetched from the public leaderboard endpoint)
- `acf contributor id` prints the local anonymous contributor ID
- Tiered badges at contribution thresholds: 1k / 10k / 100k calls

---

## Privacy and Consent Model

### Safe to Sync

These fields are collected and uploaded to the data lake on every sync cycle. Raw data lake access is restricted to the admin.

| Field | Why safe |
|-------|----------|
| `model` | Public model name |
| `input_tokens`, `output_tokens` | Counts only; no content |
| `cache_read_input_tokens`, `cache_write_input_tokens` | Counts only |
| `api_equivalent_cost_usd` | Derived number |
| `billing_mode`, `cost_basis` | Enum values |
| `tool_name`, `tool_type` | Registered tool names |
| `tools_exposed` | List of tool name strings; no sensitive content |
| `result_tokens_inserted`, `result_tokens_raw` | Counts only |
| `finish_reason`, `latency_ms`, `success` | Metadata |
| `source_domains` | Domain-level only (e.g. `nvidianews.nvidia.com`) |
| `source_traceability_status` | Enum |
| `integration_source` | Enum |
| `contributor_id` | Anonymous UUID |
| `user_prompt_hash` | Salted SHA-256 of normalized prompt; enables per-prompt-type clustering; no reverse-lookup possible |
| `system_prompt_hash` | SHA-256 of system prompt; captures agent identity context without exposing content |
| `temperature`, `max_tool_calls` | Numeric inference settings |
| `tool_result_truncation_policy` | Truncation config (e.g. `{"max_tokens": 1200}`); no user content |
| `budget_limits` | Numeric per-task / per-batch limits |
| `privacy_mode` | Enum value |

### Never Synced

| Field | Why excluded |
|-------|-------------|
| `user_prompt` | Raw prompt text may contain PII or sensitive queries |
| `arguments_json` | Tool arguments may contain PII or sensitive query data |
| `result_text`, `result_preview`, `result_hash` | Tool output content |
| `source_urls_returned`, `source_urls_inserted` | Full URLs may encode query terms |
| `agent_config_id`, `run_id`, `trace_id` | Internal IDs that could enable cross-session correlation |

### Opt-Out

```bash
acf sync --disable    # stop syncing; local data stays local
acf sync --enable     # re-enable
acf sync --purge      # request deletion of all previously synced data (GDPR)
```

Opt-out state is stored in `~/.acf/config.json` as `sync_enabled: false` and checked before every sync attempt. Disabling sync sets `sync_status = "excluded"` on all future `model_calls` rows.

---

## Sync Layer Architecture

### Sync Triggers

- **Automatic:** Python `atexit` hook fires after each SDK wrapper session ends
- **Manual:** `acf sync` CLI command
- **Scheduled:** configurable background interval (default: every 6 hours)

### Local Sync Buffer

Every `model_calls` row is written locally with `sync_status = "pending"`. The sync layer processes this queue asynchronously; it never blocks the API call path.

| `sync_status` | Meaning |
|---------------|---------|
| `pending` | Written locally; not yet sent |
| `synced` | Successfully uploaded to data lake |
| `failed` | Upload failed after retries; will retry next cycle |
| `excluded` | User has opted out; will never be uploaded |

### Batch Pipeline

```
1. Syncer reads model_calls WHERE sync_status = "pending" LIMIT 500
2. Anonymizer strips all excluded fields; keeps only safe fields
3. Anonymizer adds contributor_id
4. Syncer POSTs batch to POST /v1/ingest (authenticated via contributor token)
5. On HTTP 200: UPDATE model_calls SET sync_status = "synced"
6. On failure: exponential backoff; after 5 retries → sync_status = "failed"
7. Failed rows are retried on next sync cycle
```

**Weeks 1–5 (dry-run mode):** The anonymizer runs on every `model_calls` write and logs what *would* be sent. No HTTP POST is made. This validates the anonymizer and batch logic before the live ingestion API is deployed.

### Community Profiles Pull

```
On acf startup (at most once per 24 hours):
  GET /v1/community/profiles?models=claude-haiku-4-5-20251001,claude-sonnet-4-6
  → download updated community_profiles rows
  → upsert into local community_profiles table
  → these become level-0 in the prediction fallback hierarchy
```
