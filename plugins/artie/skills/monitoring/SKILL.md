---
name: monitoring
description: Monitor Artie CDC pipeline health through MCP.
---

# Pipeline Monitoring

Use the Artie MCP tools to inspect a saved pipeline’s lifecycle, per-table state, and ingestion metrics. Do not create or configure pipelines here, and do not claim that a destination query succeeded.

## When to Use

- A user asks whether a pipeline is running, paused, deploying, or backfilling.
- A user wants table status, ingestion lag, throughput, or Artie-processed row counts.
- A user requests a schema-change check, schema-DDL application, a pause/resume, or a backfill action.
- Do not use for pipeline creation (`pipeline-setup`), connector compatibility, network setup, or proof that data landed in a destination.

## Prerequisites

1. Inspect `tools/list` before a route that depends on a named tool. If it is unavailable on the connected server, say which capability is unavailable and use the Dashboard only for that gap; never invent metrics or a tool result.
2. Resolve a named pipeline through `pipeline_list`. Match `name` or `uuid`; never guess a UUID.
3. Obtain explicit confirmation immediately before every mutation. A schema-change check is also a mutation because it enqueues work.

## Procedure

1. Call `pipeline_list` to resolve the pipeline and report only its returned lifecycle fields. Completion: name, UUID, and lifecycle status are unambiguous.
2. Call only the intent-specific read tool below. Completion: the reply identifies the tool and time window used.
3. For an action, describe its scope and consequence, ask for confirmation, then call only after the user confirms. Completion: the reply distinguishes queued work from completed destination changes.
4. Summarize only fields returned by the tools called. Completion: the reply does not claim warehouse correctness, error-log content, or lag from lifecycle state.

## Intent Matrix

| Request | Calls after pipeline resolution | Safety rule |
|---|---|---|
| Running, paused, deployment state | `pipeline_list` | `status` is lifecycle, not health or lag. |
| Tables, per-table state, backfill state | `pipeline_detail` | Omit `includeRelatedObjects`; use table UUIDs only from this response. |
| Lag, throughput, rows processed | `pipeline_usage` | Pass RFC3339 `from` and `to`; default to the last one hour UTC if unspecified. |
| “How is my pipeline?” | `pipeline_detail` + `pipeline_usage` | Do not fetch either for a narrower question. |
| Check source schema drift | `pipeline_detect_schema_changes` | Explain that it enqueues a check and ask for confirmation. |
| Apply schema changes | `pipeline_trigger_automatic_schema_changes` | Destructive: confirm; it applies supported destination DDL for one pipeline. |
| Apply schema changes company-wide | `company_trigger_automatic_schema_changes` | Destructive and broad: confirm explicit company-wide scope. |
| Pause or resume | `pipeline_update_status` | Confirm; first deploy is `pipeline_start`, not this action. |
| Start or cancel a backfill | `pipeline_backfill_tables` / `pipeline_cancel_backfill_tables` | Destructive: confirm; use table UUIDs from `pipeline_detail`. |

## Reading Results

### `pipeline_list`

`status` is one of `draft`, `paused`, `transfer paused`, or `running`; it does not expose a failed/error state. `isDeploying`, `hasUndeployedChanges`, and `hasBackfillingTables` describe deployment/configuration/backfill state, not ingestion lag or destination correctness. `sourceReaderUUID` is a reader identifier, never a connector UUID for `connector_fetch_*` calls.

### `pipeline_detail`

Use it for tables (`uuid`, `name`, `schema`, `status`), per-table backfill state, destination configuration, and the reader UUID. Table status is `draft`, `ready_to_backfill`, `backfilling`, `streaming`, or `paused`. It is not a lag endpoint.

### `pipeline_usage`

`tableStats[].latency` is ingestion lag in seconds and can be null. `tableStats[].count` is the number of messages Artie processed in the requested interval; it is not a destination `SELECT COUNT(*)`. An empty result means no metrics in that window, which can occur for a new pipeline. Quote the exact window in the reply.

## Mutations

- `pipeline_detect_schema_changes` checks the source and queues background work; success does not return a schema diff. Review the pipeline overview or [schema-change notifications](https://www.artie.com/docs/monitoring/schema-changes) for results.
- Automatic schema-change tools apply supported **destination** DDL. Source notifications alone do not alter the destination.
- `pipeline_update_status` changes lifecycle status. `pipeline_backfill_tables` and `pipeline_cancel_backfill_tables` change backfill work. All require confirmation.

## Gaps

The following are not monitoring reads supplied by this skill: error log lines and stack traces, custom-monitor CRUD, and Postgres replication-slot-size graphs. Direct the user to the relevant [Dashboard](https://app.artie.com) view or documented monitoring integration. Never use `connector_drop_postgres_replication_slot` as a health check; it drops a replication slot.

## Pitfalls

- Do not fetch `pipeline_detail` or `pipeline_usage` “just in case.”
- Do not use `pipeline_list` as a `pipeline_update` body; it is not a FullPipeline.
- Do not claim an alert resolves synchronously after changing a monitor configuration; monitor evaluation is asynchronous and outcome depends on current data.
- Do not call a missing tool, substitute invented metrics, or claim data landed in the warehouse.

## Verification

Before responding, verify that every named tool appears in the active `tools/list` and that every mutating operation received explicit confirmation. Report the pipeline name and UUID, tools called, the metrics window when applicable, and whether an action was merely queued or completed.