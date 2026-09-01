---
name: monitoring
description: Checks Artie pipeline health from MCP list fields and schema-change tools, and routes lag, throughput, error logs, and custom monitors to the Dashboard. Use when the user asks whether a pipeline is running or paused, wants a schema-change check, or asks about lag, rows synced, alerts, or monitors. Do not use to create pipelines, answer type-support questions, invent lag numbers, or claim a row landed in the warehouse.
---

# Pipeline monitoring

List status from MCP. Lag, error logs, and custom monitors are Dashboard-only — there is no tool for them on this pin. Do not invent `pipeline_usage`, `pipeline_detail`, `pipeline_error_logs`, or a monitor CRUD tool.

## Sequence

1. **`pipeline_list`**. Match on `name` / `uuid`. Do not guess UUIDs. This is a summary, not a FullPipeline and not a `pipeline_update` body.
2. Lead with **name and UUID**. Read the list fields below. Stop unless they asked for a schema-change check or to change status.
3. Schema drift or applying destination DDL — only the tools in **Schema changes**, and only when they asked.
4. Everything else (lag, throughput, error logs, monitors, slot size) — Dashboard / docs. Do not substitute a proxy.

## What `pipeline_list` can tell you

Status enum is `draft` | `paused` | `transfer paused` | `running`. There is no failed / error status on this list.

| Field | Means | Does **not** mean |
|---|---|---|
| `status` | Lifecycle: draft, paused, transfer paused, or running | Replication lag, runtime errors, or warehouse correctness |
| `isDeploying` | A deploy is in progress | Lag |
| `hasUndeployedChanges` | Saved config has not been deployed | Lag, schema drift, or a failed pipeline |
| `hasBackfillingTables` | At least one table is backfilling | Destination SELECT succeeded or backfill finished |
| `lastDeployedAt` | Last deploy time | Last row flushed |
| `destinationUUID` / `sourceType` | Attached dest and source engine | Which tables this pipeline streams |
| `sourceReaderUUID` | Reader id | A **connector** UUID — do not pass it to `connector_fetch_*` |

List rows have no `tables`. `connector_fetch_tables` is the connector catalog, not this pipeline's allowlist. `connector_fetch_table_detail` is column metadata, not lag or row counts.

If they ask why it failed, or for log lines: no error-log tool on MCP. Send them to the pipeline in the [Artie Dashboard](https://app.artie.com).

## Lag, throughput, rows synced

No usage or analytics tool on MCP. Do not quote lag, row counts, or slot size you did not fetch.

Send them to the [analytics portal](https://app.artie.com/analytics) and [Analytics portal](https://www.artie.com/docs/monitoring/analytics-portal). Same metrics can go to Datadog or Grafana Cloud — [Monitoring integrations](https://www.artie.com/docs/monitoring/integrations).

## Custom monitors and alerts

Creating, listing, or reading custom monitors is Dashboard-only. Point at [custom monitors](https://www.artie.com/docs/monitoring/custom-monitors) (volume, ingestion lag, PostgreSQL replication-slot size) and [enabling notifications](https://www.artie.com/docs/account/enabling-notifications). Real-time error events: [webhooks](https://www.artie.com/docs/api/webhooks/overview). Do not call a monitor or alert tool.

## Schema changes

Only if they asked for a source check or to apply destination DDL.

1. Resolve the UUID from `pipeline_list`.
2. **`pipeline_detect_schema_changes`** — write. Enqueues a background check for new, removed, or altered tables/columns. Success is `{"success": true}` (Dashboard HTTP 204); there is no diff payload. If the pipeline has auto-replicate or auto-history for new tables, newly discovered tables can be added. Watch the pipeline overview and [schema change notifications](https://www.artie.com/docs/monitoring/schema-changes). `hasUndeployedChanges` is not the result of this check.

If they want Artie to apply supported destination schema diffs, confirm first (destructive):

- One pipeline: **`pipeline_trigger_automatic_schema_changes`**
- All eligible pipelines: **`company_trigger_automatic_schema_changes`**

Notifications report source changes. They do not by themselves alter the destination. See [schema evolution](https://www.artie.com/docs/guides/artie/schema-evolution).

## Pause or resume

**`pipeline_update_status`** sets status (pause / resume an already-configured pipeline). Confirm before calling. For first deploy, use `pipeline_start` (`pipeline-setup`). Do not call `pipeline_update_status` to *read* health.

## What not to say

- Do not claim data landed, first record verified, or a destination SELECT succeeded.
- Do not answer “how many seconds of lag?” from `hasUndeployedChanges`, `isDeploying`, or `lastDeployedAt`.
- Do not call `connector_create` or `unsaved_*`. Do not ping unsaved credentials.
- Do not drop a Postgres replication slot to “check” slot health (`connector_drop_postgres_replication_slot` is destructive).
- Creating a pipeline belongs in `pipeline-setup`. Type / capture method / network support belongs in `connector-compatibility`.
