---
name: monitoring
description: >
  Reports Artie pipeline health: status, per-table state, total and
  per-table lag, throughput, rows processed, recent error logs, and Postgres
  replication slot and WAL health. Use when the user asks whether a pipeline
  is healthy, stuck, behind, or caught up, why it is failing, won't start,
  or a table isn't syncing, or wants lag or row counts — even without
  saying "monitor" or "health". Read-only: never pauses, resumes,
  backfills, detects or applies schema changes, even if asked to. Do not
  use for pipeline setup, type-support or network questions, Kafka
  clusters, or proving rows landed in the destination.
---

## Monitoring a pipeline

Resolve the pipeline with `pipeline_list`, matching `name` or `uuid` — never guess. Its row already has `status`, `isDeploying`, `hasBackfillingTables`, `hasUndeployedChanges`, `lastDeployError`, `lastDeployFailedAt`, `sourceType` and `sourceReaderUUID`. Then call only what the question needs.

| Question | Calls after `pipeline_list` |
|---|---|
| Running, paused, deploying, backfilling? | none — answer from the row |
| How far behind? | `analytics_query` (see [Lag](#lag)) |
| Which tables are behind? Rows synced? | `pipeline_usage` with RFC3339 `from`/`to` (see [Lag](#lag)) |
| Per-table status? | `pipeline_detail` (omit `includeRelatedObjects`) |
| Why is it failing? | `pipeline_error_logs` |
| Won't start or keeps failing? | [Won't start](#wont-start-or-keeps-failing) |
| Postgres slot or WAL growing? | [Slots](#postgres-slots-and-wal) |
| Overall health? | `pipeline_detail` → `analytics_query` → `pipeline_usage` → `pipeline_error_logs` |
| Source table columns? | `connector_fetch_table_detail` on a **connector** UUID |

Reads in scope: the tools above, plus `connector_list`, `source_reader_detail`, `connector_fetch_postgres_settings`, `connector_fetch_postgres_replication_slots` and `data_catalog_search`. Nothing else.

## Lag

- Total lag: one `analytics_query` with `pipelineUUID`, `datasets[]=readerLag`, `datasets[]=ingestionLag`, RFC3339 `from`/`to` (default: last hour UTC — always state the window). Total lag = readerLag + ingestionLag at each timestamp, matched by timestamp. Ingestion lag is only reported when Artie flushes, so a timestamp with only one dataset counts the missing one as 0 (an idle stretch has reader lag only), as the Dashboard's lag chart does. Report the total at the latest timestamp either dataset has, and the max in the window.
- Each dataset comes back as `datasets.<name>` with its own `unit` and `err`. Read `unit`; don't assume seconds. A non-null `err` means that dataset is unavailable — say so, don't treat it as zero. `ingestionLag` with no points and a null `err` is normal for a Kafka destination: `readerLag` is then the whole lag.
- Per table: `pipeline_usage` with the same window. `tableStats[].latency` is ingestion lag only, in seconds — never call it total lag. `count` is rows processed; pass `excludeBackfills=true` to count CDC rows only.
- Throughput over time: `analytics_query` `datasets[]=rowsSyncedByTime`.

## Won't start or keeps failing

1. `pipeline_list` row: quote `lastDeployError` and `lastDeployFailedAt` when set.
2. Postgres source only: `source_reader_detail` with `sourceReaderUUID` → `connectorUUID` and `database`. If it's denied, use `connector_list` with `includeSourceConnectors=true`; if more than one Postgres source could match, ask which one and its database. Then `connector_fetch_postgres_settings` (`uuid` = `connectorUUID`, `databaseName` = `database`). `wal_level` must be `logical`; check `max_replication_slots` and `max_wal_senders` leave room for Artie.
3. Postgres source only: `connector_fetch_postgres_replication_slots` with the same args. Look for the reader's slot (`settings.replicationSlotOverride`, else `artie`). No entry with that `name` means the slot doesn't exist — normal before the pipeline's first start. If you fell back to `connector_list`, you can't see the override: report every slot's `active` and `walStatus` instead of assuming `artie`.
4. `pipeline_error_logs`. Quote the newest messages and their timestamps.

Stop there and report which step showed the problem.

## Postgres slots and WAL

Get `connectorUUID` and `database` as in step 2 above, then `connector_fetch_postgres_replication_slots`.

- `active: false` on the reader's slot means nothing is reading it; WAL keeps growing while it stays inactive.
- `retainedWALBytes` is the WAL the slot holds on the source. Report it in GB.
- `walStatus` is Postgres's `wal_status`: `unreserved` means the slot is about to lose WAL it needs; `lost` means it can no longer be used. On Postgres 12 and older it is always `N/A`.
- The reader's slot is missing if no entry's `name` matches (see step 3).
- `connector_fetch_postgres_settings` `max_slot_wal_keep_size` caps retained WAL (`-1` = no cap). It doesn't exist on Postgres 12 and older.
- Settings are changed on the database, not through Artie. Dropping a slot is a change — hand it back.

## Gotchas

- `status`: `draft` | `paused` | `transfer paused` | `running`, and **may be absent** — say "not reported," never assume `draft`. `transfer paused` ≠ `paused` (capture still runs, delivery stops).
- `isDeploying`, `hasBackfillingTables`, `hasUndeployedChanges` are independent of `status` — check each; `hasUndeployedChanges: true` means saved config isn't live yet.
- `disableReplication: true` on a table is intentional — list it as excluded, not failing.
- `pipeline_usage` `latency` is nullable: `null` ≠ 0, exclude it before taking a max. `count: 0` means nothing moved in the window, not an empty table. `tableStats: []` means no metrics in that window — widen it before calling anything unhealthy. Rows key on `tableName` only, with no `uuid`/`schema`.
- `pipeline_error_logs`: an empty list means no recent logged errors, not proof of health.
- Slot and settings tools take a **source connector** UUID, never a pipeline uuid or `sourceReaderUUID`. `source_reader_detail` can hold credentials — never echo its output; use only `connectorUUID`, `database` and the slot override.
- Source schema drift: do not call `pipeline_detect_schema_changes`. It is a write — on pipelines with auto-replicate or auto-history for new tables it adds the new tables and emails a summary. Point to [schema-change notifications](https://www.artie.com/docs/monitoring/schema-changes) and hand detection back.
- Report what a field says, not why — a stale lag or a status mismatch has causes these tools can't show. Flag it; don't explain it. Never invent logs, metrics, or a destination row count.
- MCP can't verify the destination. Report rows processed, not "landed."

## When the fix requires changing something

**Stop at diagnosis** — never call a tool outside the reads above, even if told to go ahead. That includes `pipeline_update_status`, `pipeline_backfill_tables`, `pipeline_cancel_backfill_tables`, `pipeline_detect_schema_changes`, `pipeline_trigger_automatic_schema_changes`, `company_trigger_automatic_schema_changes`, `pipeline_start`, `pipeline_update`, `connector_drop_postgres_replication_slot`, `source_reader_update`, `source_reader_deploy`, and every `*_delete`, Kafka topic or user change, and Snowflake Eco Mode schedule change. Name the action and hand it back:

> `orders` has been backfilling for 6h with 0 rows processed. Fixing that means cancelling and restarting the backfill, which can truncate or drop the destination table depending on how it's started — that's a state change, so I haven't done it. Want me to pick that up?

## Reply

Lead with the pipeline's name and uuid, then lifecycle. If you checked lag or rows synced, always give the window, then total lag, the tables behind and row counts as asked. This skill changes nothing, so never say a fix is queued or done.
