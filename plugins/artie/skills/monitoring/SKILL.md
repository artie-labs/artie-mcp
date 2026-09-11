---
name: monitoring
description: >
  Reports Artie pipeline health: status, per-table state, ingestion lag,
  throughput, rows processed, and source schema drift. Use when the user
  asks whether a pipeline is healthy, stuck, behind, or caught up, why a
  table isn't syncing, or wants lag or row counts — even without saying
  "monitor" or "health". Read-only: never pauses, resumes, backfills, or
  applies schema changes, even if asked to. Do not use for pipeline setup,
  type-support or network questions, or proving rows landed in the
  destination.
---

## Monitoring a pipeline

Resolve the pipeline with `pipeline_list`, matching `name` or `uuid` — never guess. Call only what the question needs.

| Question | Call |
|---|---|
| Running, paused, deploying, backfilling? | `pipeline_list` |
| Per-table status? | `pipeline_detail` (omit `includeRelatedObjects`) |
| Lag, throughput, rows processed? | `pipeline_usage` with RFC3339 `from`/`to` (default: last hour UTC — always state the window) |
| Overall health? | `pipeline_list` → `pipeline_detail` → `pipeline_usage` |
| Source schema drift? | `pipeline_detect_schema_changes` |
| Source table columns? | `connector_fetch_table_detail` on a **connector** UUID |

Scope is those reads plus `data_catalog_search`, plus `pipeline_detect_schema_changes` (inspects the source, changes nothing).

## Gotchas

- `status`: `draft` | `paused` | `transfer paused` | `running`, and **may be absent** — say "not reported," never assume `draft`. `transfer paused` ≠ `paused` (capture still runs, delivery stops).
- `isDeploying`, `hasBackfillingTables`, `hasUndeployedChanges` are independent of `status` — check each; `hasUndeployedChanges: true` means saved config isn't live yet.
- `disableReplication: true` on a table is intentional — list it as excluded, not failing.
- `pipeline_usage.tableStats[].latency` is nullable: `null` ≠ 0, exclude it before taking a max. `count: 0` means nothing moved in the window, not an empty table. `tableStats: []` means no metrics in that window — widen it before calling anything unhealthy. Rows key on `tableName` only, with no `uuid`/`schema`.
- `pipeline_detect_schema_changes` is bodiless-success: MCP always returns `{"success": true}`, never a diff — point to the pipeline overview or [schema-change notifications](https://www.artie.com/docs/monitoring/schema-changes), don't poll for one. It never touches the destination; applying drift is `pipeline_trigger_automatic_schema_changes`, out of scope here even right after a detect.
- No error-log or slot-health tool exists. Say so, point to the [Dashboard](https://app.artie.com), and never invent logs, metrics, or a destination row count. `connector_drop_postgres_replication_slot` drops a slot — never a health check.
- Report what a field says, not why — a stale lag or a status mismatch has causes these tools can't show. Flag it; don't explain it.
- MCP can't verify the destination. Report rows processed, not "landed."

## When the fix requires changing something

**Stop at diagnosis** — never call `pipeline_update_status`, `pipeline_backfill_tables`, `pipeline_cancel_backfill_tables`, `pipeline_trigger_automatic_schema_changes`, `company_trigger_automatic_schema_changes`, `pipeline_start`, or `pipeline_update`, even if told to go ahead. Name the action and hand it back:

## Reply

Lead with the pipeline's name and uuid, then lifecycle, table counts, and the lag window if used. Say "queued," never "done," for anything just detected or requested.
