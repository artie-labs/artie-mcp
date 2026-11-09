---
name: monitoring
description: >
  Reports Artie pipeline health: status, per-table state, total and
  per-table lag, throughput, rows processed, recent error logs, and Postgres
  replication slot health.
  Use when the user asks whether a pipeline is healthy, stuck, behind, or
  caught up, why it is failing or a table isn't syncing, or wants lag or
  row counts — even without saying "monitor" or "health". Read-only: never
  pauses, resumes, backfills, detects or applies schema changes, even if
  asked to.
  Do not use for pipeline setup, type-support or network questions, or
  proving rows landed in the destination.
---

## Monitoring a pipeline

Resolve the pipeline with `pipeline_list`, matching `name` or `uuid` — never guess. Call only what the question needs.

| Question | Call |
|---|---|
| Running, paused, deploying, backfilling? | `pipeline_list` |
| Per-table status? | `pipeline_detail` (omit `includeRelatedObjects`) |
| Why is it failing? Error messages? | `pipeline_error_logs` |
| How far behind (total lag)? | `analytics_query` with `pipelineUUID`, `datasets[]=readerLag` and `datasets[]=ingestionLag`, RFC3339 `from`/`to`; total lag = readerLag + ingestionLag at each timestamp |
| Per-table lag, throughput, rows processed? | `pipeline_usage` with RFC3339 `from`/`to` (default: last hour UTC — always state the window); `excludeBackfills=true` to count CDC rows only |
| Overall health? | `pipeline_list` → `pipeline_detail` → `pipeline_usage` → `pipeline_error_logs` |
| Postgres slot or WAL health? | `connector_fetch_postgres_replication_slots` and `connector_fetch_postgres_settings` on the **source connector** UUID |
| Source table columns? | `connector_fetch_table_detail` on a **connector** UUID |

Scope is those reads plus `connector_list` and `data_catalog_search`. Nothing else.

## Gotchas

- `status`: `draft` | `paused` | `transfer paused` | `running`, and **may be absent** — say "not reported," never assume `draft`. `transfer paused` ≠ `paused` (capture still runs, delivery stops).
- `isDeploying`, `hasBackfillingTables`, `hasUndeployedChanges` are independent of `status` — check each; `hasUndeployedChanges: true` means saved config isn't live yet.
- `disableReplication: true` on a table is intentional — list it as excluded, not failing.
- `pipeline_usage.tableStats[].latency` is ingestion lag only (seconds), not total lag. It is nullable: `null` ≠ 0, exclude it before taking a max. `count: 0` means nothing moved in the window, not an empty table. `tableStats: []` means no metrics in that window — widen it before calling anything unhealthy. Rows key on `tableName` only, with no `uuid`/`schema`.
- Source schema drift: do not call `pipeline_detect_schema_changes` here. It is a write — on pipelines with auto-replicate or auto-history for new tables it adds the new tables to the pipeline and emails a summary. Point to the pipeline overview or [schema-change notifications](https://www.artie.com/docs/monitoring/schema-changes) instead, and hand detection back like any other change.
- `pipeline_error_logs` returns recent logged errors (`message`, `errorDetail`, table/schema, timestamps). Quote what it says and when; an empty list means no recent logged errors, not proof of health.
- Slot tools take a **source connector** UUID (`connector_list` with `includeSourceConnectors=true`), not a pipeline uuid or `sourceReaderUUID`; pass the pipeline's reader database as `databaseName`. `connector_drop_postgres_replication_slot` drops a slot — never a health check. Never invent logs, metrics, or a destination row count.
- Report what a field says, not why — a stale lag or a status mismatch has causes these tools can't show. Flag it; don't explain it.
- MCP can't verify the destination. Report rows processed, not "landed."

## When the fix requires changing something

**Stop at diagnosis** — never call a tool outside the reads above, even if told to go ahead. That includes `pipeline_update_status`, `pipeline_backfill_tables`, `pipeline_cancel_backfill_tables`, `pipeline_detect_schema_changes`, `pipeline_trigger_automatic_schema_changes`, `company_trigger_automatic_schema_changes`, `pipeline_start`, `pipeline_update`, `connector_drop_postgres_replication_slot`, `source_reader_update`, `source_reader_deploy`, and every `*_delete`, Kafka topic or user change, and Snowflake Eco Mode schedule change. Name the action and hand it back:

> `orders` has been backfilling for 6h with 0 rows processed. Fixing that means cancelling and restarting the backfill, which can truncate or drop the destination table depending on how it's started — that's a state change, so I haven't done it. Want me to pick that up?

## Reply

Lead with the pipeline's name and uuid, then lifecycle, table counts, and the lag window if used. Say "queued," never "done," for anything just detected or requested.
