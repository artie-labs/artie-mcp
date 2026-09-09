---
name: monitoring
description: >
  Reads the health of an existing Artie pipeline and explains what it finds:
  whether it is running, paused, deploying, or backfilling; per-table state;
  ingestion lag, throughput, and rows processed; and whether the source
  schema has drifted. Use when the user asks whether a pipeline is healthy,
  stuck, behind, or caught up, why a table is not syncing, how far behind it
  is, whether anything changed in the source, or wants lag or row counts —
  even if they name a pipeline without saying "monitor" or "health". This
  skill diagnoses and reports; it does not alter a pipeline or a destination.
  Do not use it to create or deploy a pipeline, to pause, resume, or backfill,
  to apply schema changes to the destination, to answer type-support or
  network questions, or to prove rows landed in the destination — MCP cannot
  run a warehouse SELECT.
---

## Monitoring a pipeline

Resolve the pipeline with `pipeline_list` and match on `name` or `uuid`. Never guess a UUID. Then call only the tool the question needs — a status question does not need lag, and prefetching `pipeline_usage` on every request burns a metrics call for nothing.

| Question | Call |
|---|---|
| Is it running, paused, deploying, or backfilling? | `pipeline_list` |
| Which tables are streaming, backfilling, or off? | `pipeline_detail` (omit `includeRelatedObjects`) |
| Lag, throughput, or rows processed? | `pipeline_usage` with RFC3339 `from`/`to`; default to the last hour UTC |
| Is it healthy overall? | `pipeline_list`, then `pipeline_detail`, then `pipeline_usage` |
| Did the source schema change? | `pipeline_detect_schema_changes` — queues a source check, see below |
| What columns does a source table have? | `connector_fetch_table_detail` on a **connector** UUID |

Those reads plus `data_catalog_search` are the whole surface of this skill. All are `readOnlyHint: true` except `pipeline_detect_schema_changes`, which is included because it inspects the source and changes nothing.

### Reading the fields

`pipeline_list` rows carry four independent health signals. `status` alone does not answer "is it working":

- `status` — lifecycle only: `draft`, `paused`, `transfer paused`, or `running`. **The field is optional and may be absent**; say "not reported" rather than assuming `draft`. `transfer paused` is its own state (capture still running, delivery stopped), not a synonym for `paused`.
- `isDeploying: true` — a deploy is in flight, so table state is mid-change.
- `hasBackfillingTables: true` — at least one table is backfilling. Do not infer this from `status`.
- `hasUndeployedChanges: true` — saved config is **not live yet**. Report this: the user is often looking at a change they think already applied.

`pipeline_detail.tables[]` gives `uuid`, `name`, `schema`, `status`, `backfillStage`, `destinationTableName`, and `disableReplication`. A table with `disableReplication: true` is **intentionally off** — list it as excluded, never as a failure.

`pipeline_usage.tableStats[]` gives `tableName`, `count`, and `latency`:

- `latency` is ingestion lag in seconds and **is nullable**. `null` means no lag was reported for that table in the window — not zero, and not caught up. Exclude nulls before taking a maximum, and name the tables you excluded.
- `count` is rows Artie processed inside the requested window. It is not a destination `SELECT COUNT(*)`, and `count: 0` means nothing moved in that window, not that the table is empty.
- Rows are keyed by `tableName` only — no `uuid` and no `schema`. If two replicated tables share a name across schemas you cannot tell their rows apart; say so instead of picking one.
- `tableStats: []` means there were no metrics in that window. Widen the window before calling anything unhealthy.

Always state the window you queried.

### Schema drift

`pipeline_detect_schema_changes` queues a background check of the **source**. Two things follow from that:

- It is a bodiless-success tool: on success MCP always returns `{"success": true}`, never the upstream's `204` or a body to describe. There is no diff in that response. Say the check is queued and point the user at the pipeline overview or [schema-change notifications](https://www.artie.com/docs/monitoring/schema-changes). Polling `pipeline_detail` afterwards will not show a diff either — do not loop. An error naming the pipeline UUID as not found means that UUID is not a pipeline.
- It reads the source and alters nothing. Applying the drift to the destination is a different tool, `pipeline_trigger_automatic_schema_changes`, and that one **is** destructive DDL and is out of scope here. Detecting drift is never permission to apply it. If the user wants it applied, say that is a state change and hand it back.

## When the fix requires changing something

Diagnosing often lands on an action: resume it, backfill that table, apply the drift. **This skill stops at the diagnosis.** Do not call `pipeline_update_status`, `pipeline_backfill_tables`, `pipeline_cancel_backfill_tables`, `pipeline_trigger_automatic_schema_changes`, `company_trigger_automatic_schema_changes`, `pipeline_start`, or `pipeline_update` from here — not even when the user says to go ahead, and not even when the fix looks obvious.

Instead, finish the read, then name the action you would take and hand it back:

> `orders` has been backfilling for 6h with 0 rows processed. Fixing that means cancelling and restarting the backfill, which can truncate or drop the destination table depending on how it is started — that is a state change, so I have not done it. Want me to pick that up?

This matters because a backfill takes a required `beforeBackfill` argument whose values include `truncate_table` and `drop_table`, and because these tools are bodiless-success: MCP returns `{"success": true}` for a queued job with no diff to undo from. Getting one wrong from inside a health check is a bad trade for saving a round trip.

## Gotchas

- `pipeline_list` is a summary, not a `FullPipeline`. It is not a `pipeline_update` body.
- `sourceReaderUUID` is a reader id. It is not a connector UUID and not a pipeline UUID — passing it to `connector_fetch_*` 404s.
- `pipeline_detail` with `includeRelatedObjects` is a Dashboard flag and is rejected by the policy. Omit it.
- `connector_drop_postgres_replication_slot` **drops** a replication slot. It is not a slot-health check, and there is no read that reports slot health — say so and point at the Dashboard.
- `data_catalog_search` is ingested metadata, not a live source walk.
- There is no error-log tool and no custom-monitor tool. When a capability is missing from `tools/list`, say plainly that it is not available on the connected server and point to the [Artie Dashboard](https://app.artie.com). Never invent log lines, metrics, or destination row counts.
- Report what a field says, not why it says it. A stale-looking lag, a zero `count`, or a table status that disagrees with the pipeline status has causes these tools cannot show you. Flag the discrepancy and say what you would check next; do not assert a reason you cannot see.
- MCP cannot verify the destination. "Is the data there?" is answerable only as "Artie processed N rows in this window" — say that instead of confirming a landing.

## Reply

```
**{pipeline name}** · `{uuid}`
Lifecycle: {status, or "not reported"}{, deploying / backfilling / undeployed changes if set}
Tables: {n} streaming, {n} backfilling, {n} replication disabled
Lag (window {from} → {to} UTC): highest {n}s on {table}; no lag reported for {tables}
Rows processed in window: {n}
{Blank line, then anything needing attention, or "Nothing needs attention."}
Calls: {tools used}
```

Adapt the lines to the question — a status-only question should not carry an empty lag line. If the answer implies an action, close with the action you would take and leave it to the user.
