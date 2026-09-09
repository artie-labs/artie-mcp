---
name: monitoring
description: >
  Checks Artie pipeline health: status, tables, lag, throughput, rows processed,
  schema changes, pause/resume, and backfills. Use when a user asks whether a
  pipeline is healthy, running, paused, backfilling, or wants its lag or
  throughput. Do not use to create pipelines, answer connector compatibility
  questions, or prove data landed in the destination.
---

## Monitoring a pipeline

Resolve a named pipeline with `pipeline_list` by `name` or `uuid`; never guess a UUID. Call only the tool needed for the question.

| Question | Call |
|---|---|
| Is it running, paused, deploying, or backfilling? | `pipeline_list` |
| Which tables are streaming or backfilling? | `pipeline_detail` (omit `includeRelatedObjects`) |
| What is the lag, throughput, or processed row count? | `pipeline_usage` with RFC3339 `from` and `to`; use the last hour UTC if unspecified |
| How is the pipeline overall? | `pipeline_list`, `pipeline_detail`, and `pipeline_usage` |
| Check source schema drift | Ask for confirmation, then `pipeline_detect_schema_changes` |
| Apply schema changes, pause/resume, or start/cancel a backfill | Explain the effect, ask for confirmation, then call the specific tool below |

`pipeline_usage.tableStats[].latency` is ingestion lag in seconds. `count` is rows Artie processed in the requested interval, not a destination `SELECT COUNT(*)`. An empty result means there were no metrics in that window. Include the time window in the reply.

`pipeline_list.status` is lifecycle state, not lag or destination correctness. `pipeline_detail` returns table UUIDs and per-table state; use those UUIDs for backfill calls, never `connector_fetch_tables`. `sourceReaderUUID` is not a connector UUID.

## Actions

All actions require explicit confirmation immediately before the call:

- `pipeline_detect_schema_changes` queues a background source check. It returns no schema diff; review the pipeline overview or [schema-change notifications](https://www.artie.com/docs/monitoring/schema-changes).
- `pipeline_trigger_automatic_schema_changes` applies supported destination DDL for one pipeline. `company_trigger_automatic_schema_changes` does so for every eligible pipeline.
- `pipeline_update_status` pauses or resumes an existing pipeline. First deploy is `pipeline_start`, which belongs in `pipeline-setup`.
- `pipeline_backfill_tables` starts a backfill and `pipeline_cancel_backfill_tables` cancels one. Use table UUIDs from `pipeline_detail`.

If a required tool is missing from `tools/list`, say that capability is unavailable in the connected server and direct the user to the [Artie Dashboard](https://app.artie.com) for that gap. Do not invent metrics, error logs, or destination results. Never use `connector_drop_postgres_replication_slot` as a health check: it drops a replication slot.

## Reply

Report the pipeline name and UUID, calls made, lifecycle/table status, and the metrics window when used. Call out tables not streaming and the highest reported lag. Distinguish a queued action from a completed destination change.