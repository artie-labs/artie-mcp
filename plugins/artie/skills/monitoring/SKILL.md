---
name: monitoring
description: Checks Artie pipeline health from MCP — list status, per-table status, ingestion lag, rows processed, schema-change detect/apply, pause/resume. Use when the user asks whether a pipeline is running or paused, wants lag, throughput, rows synced, a schema-change check, or monitors. Do not use to create pipelines, answer type-support questions, invent lag numbers, or claim a row landed in the warehouse.
---

# Pipeline monitoring

Call the tools. Do not send lag/throughput questions to the Dashboard instead of `pipeline_usage`.

If a named tool is missing from `tools/list`, the hosted pin is older than this skill — say so, then use Dashboard only for that gap. Do not invent numbers.

## Sequence (health / lag / “is it working?”)

Run 1–3 every time. 4–6 only if they asked.

1. **`pipeline_list`** — find the pipeline (`name` / `uuid`). Do not guess UUIDs.
2. **`pipeline_detail`** — `uuid` only. **Omit `includeRelatedObjects`** (MCP 400). Per-table `status` and table UUIDs live here, not on the list row.
3. **`pipeline_usage`** — `uuid`, `from`, `to` as RFC3339. Default window if they did not specify: last **1 hour** (`from` = now−1h, `to` = now, UTC). This is lag and rows processed.
4. Schema check or apply DDL — **Schema changes**, only if they asked.
5. Pause / resume — **`pipeline_update_status`**, only if they asked. Confirm first.
6. Kick or cancel a backfill — **Backfill**, only if they asked. Confirm first. Table UUIDs come from step 2, not `connector_fetch_tables`.

Then emit the **summary** at the bottom. Do not stop after `pipeline_list` on a lag or health question.

## Tools

### `pipeline_list`

Inventory. Match on `name` / `uuid`.

`status`: `draft` | `paused` | `transfer paused` | `running`. There is no failed / error status.

| Field | Means | Does **not** mean |
|---|---|---|
| `status` | Lifecycle | Lag, stack traces, warehouse correctness |
| `isDeploying` | Deploy in progress | Lag |
| `hasUndeployedChanges` | Saved config not deployed | Lag or schema drift |
| `hasBackfillingTables` | At least one table in initial backfill | Dest SELECT succeeded |
| `lastDeployedAt` | Last deploy time | Last row flushed |
| `sourceReaderUUID` | Reader id | A **connector** UUID — do not pass it to `connector_fetch_*` |

List rows have no `tables`. Not a FullPipeline. Not a `pipeline_update` body.

### `pipeline_detail`

`GET` by pipeline `uuid`. Omit `includeRelatedObjects`.

Use for: which tables this pipeline streams (`name`, `schema`, `uuid`, `status`), `destinationUUID`, `specificDestCfg`, `sourceReaderUUID` (for `source_reader_detail` / `source_reader_update`, not `connector_fetch_*`).

Table `status`: `draft` | `ready_to_backfill` | `backfilling` | `streaming` | `paused`.

This is **not** lag. Lag is `pipeline_usage`.

### `pipeline_usage`

Lag and throughput. Required args: pipeline `uuid`, `from`, `to` (RFC3339).

Response `tableStats[]`:

| Field | Meaning |
|---|---|
| `tableName` | Table |
| `count` | Rows Transfer/Reader **processed** in the window (Datadog). Not `SELECT COUNT(*)` on the warehouse. |
| `latency` | Ingestion lag in **seconds** (null if no sample) |

Empty `tableStats` = no metrics in that window (often a brand-new pipeline). Quote the window you used.

Not slot size, not warehouse correctness, not `pipeline_list.status`.

### Schema changes

Only if they asked for a source check or to apply destination DDL.

- **`pipeline_detect_schema_changes`** (`uuid`) — write. Enqueues a background source check (new/removed/altered tables or columns). Success is `{"success": true}` (Dashboard HTTP 204); **no diff payload**. Watch the pipeline overview / [schema change notifications](https://www.artie.com/docs/monitoring/schema-changes). `hasUndeployedChanges` is not this result.
- **`pipeline_trigger_automatic_schema_changes`** — apply supported **destination** DDL for one pipeline. Confirm first (destructive).
- **`company_trigger_automatic_schema_changes`** — same for every eligible pipeline. Confirm first.

Notifications report source changes. They do not by themselves alter the destination. [Schema evolution](https://www.artie.com/docs/guides/artie/schema-evolution).

### `pipeline_update_status`

Sets pipeline `status` (e.g. `paused` / `running`). Confirm before calling. Not a health **read** — use list + usage for that. First deploy of a draft is `pipeline_start` (`pipeline-setup`).

### Backfill

- **`pipeline_backfill_tables`** — `tableUUIDs` from `pipeline_detail`. Destructive; confirm. Not `pipeline_start`.
- **`pipeline_cancel_backfill_tables`** — cancel in-flight backfill by table UUID. Confirm.

`hasBackfillingTables` / table `status` = `backfilling` is the read side.

### Not MCP (do not invent a tool)

- Error log lines / stack traces — pipeline in the [Dashboard](https://app.artie.com)
- Custom monitor CRUD (volume, lag thresholds, slot-size alerts) — [custom monitors](https://www.artie.com/docs/monitoring/custom-monitors)
- Postgres replication **slot size** graphs — analytics / [integrations](https://www.artie.com/docs/monitoring/integrations)
- `connector_drop_postgres_replication_slot` **drops** a slot; it is not a health check

## Summary (always, after the calls)

Lead with **name and UUID**. Then one block:

```
Status: <pipeline_list.status>  deploying=<isDeploying>  undeployed=<hasUndeployedChanges>  backfilling=<hasBackfillingTables>
Tables: <n>  <name.schema status, …>     // from pipeline_detail
Window: <from> → <to>
Lag / rows (pipeline_usage):
  <tableName>: lag=<latency s or n/a>  rows=<count>
```

Call out the worst lag and any table not `streaming`. Say explicitly: these row counts are Artie processed messages, not a destination SELECT.

If they asked why it failed and you have no error-log tool: status + usage + Dashboard logs. Do not guess a stack trace.

## What not to say

- When they ask about lag, throughput, or rows synced, call **`pipeline_usage`**. That is the lag tool (`latency` in seconds, `count` for the window).
- Do not claim data landed or a destination SELECT succeeded.
- Creating a pipeline belongs in `pipeline-setup`. Types / network belong in `connector-compatibility`.
