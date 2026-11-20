---
name: pipeline-setup
description: >
  Creates an Artie CDC pipeline from a source and destination, then
  optionally starts it. Use when the user wants a new pipeline, a first
  pipeline, CDC, a stream or sync, or to replicate a source into a warehouse
  — even if they have not saved the connector yet and want to provide
  connection details now, or they already have saved connectors. Also use
  to attach a Snowflake Eco Mode schedule to a pipeline. Do not
  use for type-support or network questions, pipeline health or lag,
  checking whether data landed in the warehouse, adding tables to a running
  pipeline, attaching a second destination to an existing reader (fan-out),
  or Fivetran lift-and-shift.
---

## Progress

Only attaching a Snowflake Eco Mode schedule to an existing pipeline? Skip this checklist and follow [Snowflake Eco Mode](#snowflake-eco-mode).

Copy this checklist and mark steps as you go. Stop at a failed gate. Do not skip ahead.

- [ ] Step 1: Acquire a source connector. Call `connector_list` with `includeSourceConnectors=true`. If they named one, match `label` / `uuid` and do not re-ask. If none, ask: saved source, or create one now?
- [ ] Step 2: Ping the source with `unsaved_connector_ping`. Stop if ping fails.
  - Saved Postgres, Cockroach, Oracle, or MySQL source: skip the ping and run step 7's catalog fetch now, before any destination is created — it reaches the same host. Keep the result for step 7.
  - Any other saved source: ping it. Call `connector_detail`, pass that body into `unsaved_connector_ping` with its `uuid`, and add `connectionRole=source`.
  - New: Ask for type, label, host, port, user, password, and type-specific fields. Confirm. `sharedConfig` is the inner config (`host`, `port`, `user`, `password` for Postgres). `defaultDatabase` is a **top-level** field, not inside `sharedConfig`. Do not send `uuid`. Add `connectionRole=source`.
- [ ] Step 3: Create the source if it is new. Call `connector_create` with type, label, `sharedConfig`, and `defaultDatabase` from the ping. Drop `uuid` and `connectionRole` (`connectionRole` is ping-only). Keep the returned UUID. Skip if it was already saved.
- [ ] Step 4: Acquire a destination connector. Call `connector_list` **without** `includeSourceConnectors`. If they named one, match `label` / `uuid` and do not re-ask. If none, ask: saved destination, or create one now?
- [ ] Step 5: Ping the destination with `unsaved_connector_ping`, new or saved, with `connectionRole=destination`. New: same body as step 2. Saved: the `connector_detail` body with its `uuid`, as for other saved sources in step 2. Stop if ping fails.
- [ ] Step 6: Create the destination if it is new. Same as step 3 (`connectionRole` is ping-only). Keep the UUID. Skip if it was already saved.
- [ ] Step 7: Choose the reader database (or MySQL schema). This is not `defaultDatabase` from the connector. Ask if more than one. If the fetch fails with a connection or auth error, stop — the source needs fixing in the [Artie Dashboard](https://app.artie.com) (MCP can't edit connectors).
  - Postgres / Cockroach / Oracle: `connector_fetch_databases` on the **source** UUID. Keep that name for steps 8–9.
  - MySQL: do not call `fetch_databases`. Call `connector_fetch_schemas` (`SHOW DATABASES`). Do not pass `database` on create-from-source.
- [ ] Step 8: Create the draft with `pipeline_create_from_source` (`sourceConnectorUUID`, plus `database` when step 7 produced one for Postgres/Cockroach/Oracle). Keep the FullPipeline.
- [ ] Step 9: Choose tables. Call `connector_fetch_tables` on the **source** UUID (`databaseName` / `schemaName` are query args). Pass `databaseName` when step 7 produced one for Postgres/Cockroach/Oracle. For MySQL pass the chosen schema as `schemaName` and skip `databaseName`. Do not pass a destination schema. Tables are in `items` (`name`, `schema`). Ask which to replicate. If `items` is empty, leave the draft and do not start.
- [ ] Step 10: Choose dest landing. Overlay this onto `specificDestCfg` in step 12.
  - S3 / GCS: skip catalog fetch. Set `specificDestCfg.bucketName` to the bucket (`defaultDatabase` from the ping body, or from `connector_detail` for a saved destination).
  - Else: `connector_fetch_databases` on the **destination** UUID. If either fetch 400s with a connection or auth error (unreachable host, bad credentials, permission denied), stop — the destination needs fixing in the [Artie Dashboard](https://app.artie.com). Any other 400, or an empty list, means that level doesn't exist: skip database. Then `connector_fetch_schemas` with `databaseName` when you have one — on any other 400, skip schema (BigQuery has datasets only). Ask if more than one. Set `specificDestCfg.database` and, when the dest has schemas, `specificDestCfg.schema`. Do not copy the source schema. Do not pick the first name. Dests with schemas (Snowflake, Redshift, Postgres, …) require `specificDestCfg.schema` unless `useSameSchemaAsSource` (do not set that).
- [ ] Step 11: Name the pipeline. Default is `From {source label}`. Ask if they want a different name.
- [ ] Step 12: Echo the plan (source, dest, landing, tables, name, and the Eco Mode schedule if any). Wait for confirm. Then `pipeline_update` with path `uuid` = the pipeline UUID and body key `pipeline` (not a flat FullPipeline). Echo the last FullPipeline **into `pipeline`**, overlay `name`, `destinationUUID`, `specificDestCfg` (from step 10), and `tables` (`{name, schema}` from step 9; `schema` is the **source** schema). Keep `sourceReaderUUID` and `dataPlaneName` from the echo. If they want an Eco Mode schedule (Snowflake destination only), add `snowflakeEcoScheduleUUID` (see [Snowflake Eco Mode](#snowflake-eco-mode)).
- [ ] Step 13: Ask whether to start now or leave it as a draft. If draft: stop. If start: for a Postgres source, first call `connector_fetch_postgres_settings` (source UUID, `databaseName` from step 7); if `wal_level` is not `logical`, do not start — follow WAL level in [references/start-failures.md](references/start-failures.md). If the fetch itself fails, do not start: leave the draft and say why (a connection or auth error means the saved connector needs fixing in the [Artie Dashboard](https://app.artie.com)). It uses `connectors:read`, the same scope as the catalog fetches, so it isn't expected to be denied here. Then `pipeline_start`. Success is `{"success": true}` — stop. Do not call `pipeline_usage`, do not poll table status, do not claim a row landed. Health, lag, and whether a row landed are outside this skill. If `pipeline_start` 400s or times out, read [references/start-failures.md](references/start-failures.md).

## Gotchas

### Ping and create

- Ping a connector, not a pipeline uuid or `sourceReaderUUID`.
- Postgres ping/create needs top-level `defaultDatabase` (database name). Oracle: that same field is the service name. S3: that same field is the bucket. Do not put it inside `sharedConfig`.
- `unsaved_connector_ping` succeeds with `{"success": true}`. A 422 means the connection failed (unreachable host, bad credentials, missing permissions); quote its error, which says why. A 400 means the request body is wrong — fix the body, not the credentials. Do not switch to a different saved connector. Stop on a 422; a saved connector that fails needs fixing in the [Artie Dashboard](https://app.artie.com).
- Do not echo the password. Do not call `unsaved_connector_fetch_*` — fetch after the connector is saved.
- If `connector_create` or `unsaved_connector_ping` is missing from `tools/list`, or ping returns 403 (it needs the `connectors:write` scope):
  - New connector: send them to the [Artie Dashboard](https://app.artie.com) to save it, then resume.
  - Saved connector: don't block on the ping. A warehouse destination still gets a live check from step 10's catalog fetch. Otherwise (an S3/GCS destination, or a source with no catalog fetch before the draft), say the connector couldn't be checked and continue only if they agree.

### Catalog

- Dest fetch returns available names, not “the” landing location.
- If a dest fetch 400s and its error describes a connection or auth failure (unreachable host, bad credentials, permission denied), stop and send them to the [Artie Dashboard](https://app.artie.com) to fix the connector. Any other 400 means that catalog level does not exist for the type — skip it. Do not copy the source schema.

### Draft and start

- Pass `sourceConnectorUUID`, not `sourceType`. `sourceType` creates an empty stub source and ignores the connector from steps 1–3.
- Never follow `pipeline_create_from_source` with `pipeline_create`. That attaches a second pipeline to the same reader (fan-out).
- `pipeline_list` is not a FullPipeline. If you lose the create response, reload with `pipeline_detail` and omit `includeRelatedObjects`.
- `pipeline_update` is a full replace, not a PATCH. Args are `uuid` + `pipeline`. Send `destinationUUID`, `specificDestCfg`, and `tables` together. Omitting `tables` deletes every table. Keep `sourceReaderUUID` and `dataPlaneName` from the echo.
- Do not call `pipeline_start` until destination and tables are saved.

### Snowflake Eco Mode

- A schedule sets peak hours; outside them, attached pipelines use its off-peak flush rules. List with `snowflake_eco_schedule_list` and offer only schedules whose `environmentUUID` matches the pipeline's (`pipeline_update` rejects one from another environment). Ask which one, or whether to create one with `snowflake_eco_schedule_create` (`name`, `environmentUUID` = the pipeline's, `settings`: `timezone`, `days`, `startTimeOfDay`, `endTimeOfDay`, `offPeakFlushIntervalSeconds`, `offPeakBufferRows`, `offPeakFlushSizeKb`). Confirm before creating.
- New pipeline: set `snowflakeEcoScheduleUUID` in the step 12 `pipeline_update` body.
- Existing pipeline:
  1. Resolve it with `pipeline_list`, then `pipeline_detail` (omit `includeRelatedObjects`).
  2. Snowflake destination only: find its `destinationUUID` in `connector_list` (without `includeSourceConnectors`); stop unless `type` is `snowflake`.
  3. Pick or create the schedule as above.
  4. Echo the plan (pipeline, schedule) and wait for confirm.
  5. Call `pipeline_detail` again, then `pipeline_update` with that fresh body in `pipeline`, changing only `snowflakeEcoScheduleUUID`. Keep `tables` — `pipeline_update` is a full replace and omitting `tables` deletes every table.
  6. Tell them it's saved. On a running pipeline, Artie's Eco Mode job applies the schedule on its next run; no deploy is needed. If the fresh `pipeline_detail` already had `hasUndeployedChanges: true`, other saved changes are still waiting for a deploy from the [Artie Dashboard](https://app.artie.com) (every `pipeline_update` sets it, so don't read it afterwards).
- `snowflake_eco_schedule_delete` fails while a pipeline uses the schedule. Confirm before deleting.
