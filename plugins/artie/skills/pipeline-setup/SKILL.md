---
name: pipeline-setup
description: >
  Creates an Artie CDC pipeline from a source and destination, then
  optionally starts it. Use when the user wants a new pipeline, a first
  pipeline, CDC, a stream or sync, or to replicate a source into a warehouse
  — even if they have not saved the connector yet and want to provide
  connection details now, or they already have saved connectors. Do not
  use for type-support or network questions, pipeline health or lag,
  checking whether data landed in the warehouse, adding tables to a running
  pipeline, attaching a second destination to an existing reader (fan-out),
  or Fivetran lift-and-shift.
---

## Progress

Copy this checklist and mark steps as you go. Stop at a failed gate. Do not skip ahead.

- [ ] Step 1: Acquire a source connector. Call `connector_list` with `includeSourceConnectors=true`. If they named one, match `label` / `uuid` and do not re-ask. If none, ask: saved source, or create one now?
- [ ] Step 2: Ping the source with `unsaved_connector_ping`. Stop if ping fails.
  - Saved: Call `connector_detail`. Pass that whole body into `unsaved_connector_ping`. Leave `uuid` on it. Add `connectionRole=source`. `connector_detail` does not return the real password; `uuid` is how Dashboard loads it.
  - New: Ask for type, label, host, port, user, password, and type-specific fields. Confirm. `sharedConfig` is the inner config (`host`, `port`, `user`, `password` for Postgres). `defaultDatabase` is a **top-level** field, not inside `sharedConfig`. Do not send `uuid`. Add `connectionRole=source`.
- [ ] Step 3: Create the source if it is new. Call `connector_create` with type, label, `sharedConfig`, and `defaultDatabase` from the ping. Drop `uuid` and `connectionRole` (`connectionRole` is ping-only). Keep the returned UUID. Skip if it was already saved.
- [ ] Step 4: Acquire a destination connector. Call `connector_list` **without** `includeSourceConnectors`. If they named one, match `label` / `uuid` and do not re-ask. If none, ask: saved destination, or create one now?
- [ ] Step 5: Ping the destination with `unsaved_connector_ping`. Same two bodies as step 2, but `connectionRole=destination`. Stop if ping fails.
- [ ] Step 6: Create the destination if it is new. Same as step 3 (`connectionRole` is ping-only). Keep the UUID. Skip if it was already saved.
- [ ] Step 7: Choose the reader database (or MySQL schema). This is not `defaultDatabase` from the connector. Ask if more than one.
  - Postgres / Cockroach / Oracle: `connector_fetch_databases` on the **source** UUID. Keep that name for steps 8–9.
  - MySQL: do not call `fetch_databases`. Call `connector_fetch_schemas` (`SHOW DATABASES`). Do not pass `database` on create-from-source.
- [ ] Step 8: Create the draft with `pipeline_create_from_source` (`sourceConnectorUUID`, plus `database` when step 7 produced one for Postgres/Cockroach/Oracle). Keep the FullPipeline.
- [ ] Step 9: Choose tables. Call `connector_fetch_tables` on the **source** UUID (`databaseName` / `schemaName` are query args). Pass `databaseName` when step 7 produced one for Postgres/Cockroach/Oracle. For MySQL pass the chosen schema as `schemaName` and skip `databaseName`. Do not pass a destination schema. Tables are in `items` (`name`, `schema`). Ask which to replicate. If `items` is empty, leave the draft and do not start.
- [ ] Step 10: Choose dest landing. Overlay this onto `specificDestCfg` in step 12.
  - S3 / GCS: skip catalog fetch. Set `specificDestCfg.bucketName` to the bucket from ping (`defaultDatabase`).
  - Else: `connector_fetch_databases` on the **destination** UUID. If it 400s or is empty, skip database. Then `connector_fetch_schemas` with `databaseName` when you have one — if that 400s, skip schema (BigQuery has datasets only). Ask if more than one. Set `specificDestCfg.database` and, when the dest has schemas, `specificDestCfg.schema`. Do not copy the source schema. Do not pick the first name. Dests with schemas (Snowflake, Redshift, Postgres, …) require `specificDestCfg.schema` unless `useSameSchemaAsSource` (do not set that).
- [ ] Step 11: Name the pipeline. Default is `From {source label}`. Ask if they want a different name.
- [ ] Step 12: Echo the plan (source, dest, landing, tables, name). Wait for confirm. Then `pipeline_update` with path `uuid` = the pipeline UUID and body key `pipeline` (not a flat FullPipeline). Echo the last FullPipeline **into `pipeline`**, overlay `name`, `destinationUUID`, `specificDestCfg` (from step 10), and `tables` (`{name, schema}` from step 9; `schema` is the **source** schema). Keep `sourceReaderUUID` and `dataPlaneName` from the echo.
- [ ] Step 13: Ask whether to start now or leave it as a draft. If start: `pipeline_start`. Success is `{"success": true}` — stop. Do not call `pipeline_usage`, do not poll table status, do not claim a row landed. Health / lag / “did it land?” is `monitoring`. If `pipeline_start` 400s or times out, read [references/start-failures.md](references/start-failures.md).

## Gotchas

### Ping and create

- Ping a connector, not a pipeline uuid or `sourceReaderUUID`.
- Postgres ping/create needs top-level `defaultDatabase` (database name). Oracle: that same field is the service name. S3: that same field is the bucket. Do not put it inside `sharedConfig`.
- `unsaved_connector_ping` succeeds with `{"success": true}`. If it errors with `response status 200 is not approved by the policy`, the host or password is wrong. Do not switch to a different saved connector. Stop.
- Do not echo the password. Do not call `unsaved_connector_fetch_*` — fetch after the connector is saved.
- If `connector_create` or `unsaved_connector_ping` is missing from `tools/list`, send them to the [Artie Dashboard](https://app.artie.com) to save the connector, then resume.

### Catalog

- Dest fetch returns available names, not “the” landing location.
- If dest fetch 400s, that catalog level does not exist for the type — skip it. Do not copy the source schema.

### Draft and start

- Pass `sourceConnectorUUID`, not `sourceType`. `sourceType` creates an empty stub source and ignores the connector from steps 1–3.
- Never follow `pipeline_create_from_source` with `pipeline_create`. That attaches a second pipeline to the same reader (fan-out).
- `pipeline_list` is not a FullPipeline. If you lose the create response, reload with `pipeline_detail` and omit `includeRelatedObjects`.
- `pipeline_update` is a full replace, not a PATCH. Args are `uuid` + `pipeline`. Send `destinationUUID`, `specificDestCfg`, and `tables` together. Omitting `tables` deletes every table. Keep `sourceReaderUUID` and `dataPlaneName` from the echo.
- Do not call `pipeline_start` until destination and tables are saved.
