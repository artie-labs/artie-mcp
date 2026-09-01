---
name: pipeline-setup
description: >
  Creates an Artie CDC pipeline from a source and destination, then starts it.
  Use when the user wants a new pipeline, a first pipeline, or to replicate a
  source into a warehouse — even if they have not saved the connector yet and
  want to provide connection details now. Do not use for type-support or
  network questions, pipeline health or lag, or
  checking whether data landed in the warehouse.
---

## Progress

Stop at a failed gate. Do not skip ahead.

- [ ] Step 1: Acquire a source connector. Call `connector_list` with `includeSourceConnectors=true`. If they named one, match `label` / `uuid` and do not re-ask. If none, ask: saved source, or create one now?
- [ ] Step 2: Ping the source with `unsaved_connector_ping`. Stop if ping fails.
  - Saved: Call `connector_detail`, echo it, **keep `uuid`**, add `connectionRole=source`.
  - New: Collect type, label, host, user, password, and type-specific fields. Confirm, then ping with **no uuid** and `connectionRole=source`.
- [ ] Step 3: Create the source if it is new. Call `connector_create` with the same body as the ping (no uuid). Keep the UUID. Skip if it was already saved.
- [ ] Step 4: Acquire a destination connector. Call `connector_list` **without** `includeSourceConnectors`. If they named one, match `label` / `uuid` and do not re-ask. If none, ask: saved destination, or create one now?
- [ ] Step 5: Ping the destination with `unsaved_connector_ping`. Same two bodies as step 2, but `connectionRole=destination`. Stop if ping fails.
- [ ] Step 6: Create the destination if it is new. Call `connector_create` with the same body as the ping (no uuid). Keep the UUID. Skip if it was already saved.
- [ ] Step 7: Choose the source database (or MySQL schema). Ask if more than one. This is the reader database, not `defaultDatabase` from the connector.
- [ ] Step 8: Create the draft pipeline with `pipeline_create_from_source` (`sourceConnectorUUID`, plus `database` when step 7 produced one for Postgres/Cockroach/Oracle). Keep the FullPipeline.
- [ ] Step 9: Choose tables. Call `connector_fetch_tables` on the **source** UUID. Ask which to replicate. If the list is empty, leave the draft and do not start.
- [ ] Step 10: Choose dest landing if the destination has databases/schemas. Fetch on the **destination** UUID, ask if more than one, set `specificDestCfg.database` / `specificDestCfg.schema`. Do not copy the source schema. Skip for S3/GCS.
- [ ] Step 11: Name the pipeline. Default is `From {source label}`. Ask if they want a different name.
- [ ] Step 12: Save the draft with `pipeline_update`. Echo the FullPipeline. Set `name`, `destinationUUID`, and `tables` (`{name, schema}` from step 9; `schema` is the **source** schema) in the same body.
- [ ] Step 13: Ask whether to start now or leave it as a draft. If start: `pipeline_start`. Success is `{"success": true}` — stop. Do not call `pipeline_usage`, do not poll table status, do not claim a row landed.

## Gotchas

### Ping and create

- `unsaved_connector_ping` is the ping for both saved and new connectors. Saved: send the `connector_detail` body and keep `uuid` so Dashboard uses the stored password. New: omit `uuid` and put `password` in `sharedConfig`.
- Ping a connector, not a pipeline uuid or `sourceReaderUUID`.
- Postgres ping/create needs `defaultDatabase` (database name), Oracle a service name, S3 a bucket name.
- `unsaved_connector_ping` succeeds with `{"success": true}`. If it errors with `response status 200 is not approved by the policy`, the host or password is wrong. Do not switch to a different saved connector. Stop.
- Do not echo the password. Do not call `unsaved_connector_fetch_*` — fetch after the connector is saved.
- If `connector_create` or `unsaved_connector_ping` is missing from `tools/list`, send them to the [Artie Dashboard](https://app.artie.com) to save the connector, then resume.

### Catalog

- Postgres / Cockroach / Oracle: `connector_fetch_databases` on the **source** UUID, then pass that name as `database` on `pipeline_create_from_source`. MySQL: do not call `fetch_databases` — use `connector_fetch_schemas` (`SHOW DATABASES`) and do not pass `database` on create-from-source.
- Pass `databaseName` into `connector_fetch_tables` when step 7 produced one. For MySQL pass the chosen schema as `schemaName` and skip `databaseName`. Do not pass a destination schema into that call.
- Dest fetch returns available names, not “the” landing location. Do not pick the first name.

### Draft and start

- Pass `sourceConnectorUUID`, not `sourceType`. `sourceType` creates an empty stub source and ignores the connector from steps 1–3.
- Never follow `pipeline_create_from_source` with `pipeline_create`. That attaches a second pipeline to the same reader (fan-out).
- `pipeline_list` is not a FullPipeline. If you lose the create response, reload with `pipeline_detail` and omit `includeRelatedObjects`.
- `pipeline_update` is a full replace, not a PATCH. Send destination and tables together. Omitting `tables` deletes every table. Keep `dataPlaneName` from the echo.
- Do not call `pipeline_start` until destination and tables are saved. If `pipeline_start` 400s that two readers share slot `artie`: `source_reader_detail` on `sourceReaderUUID`, set `settings.replicationSlotOverride` to a unique lowercase name (digits/underscores, ≤63), `source_reader_update` with the echoed reader, then call `pipeline_start` again.
- If `pipeline_start` 400s that WAL level is `replica` (or not `logical`): that is a Postgres server setting, not an Artie config. Tell them to set `wal_level = logical` and restart Postgres, then call `pipeline_start` again. Do not `ALTER SYSTEM` yourself.
- If `pipeline_start` times out: `pipeline_detail` once (omit `includeRelatedObjects`). `status=running` or `isDeploying=true` means `pipeline_start` already succeeded — stop. Still `draft` → call `pipeline_start` once more. Do not loop.
- `ready_to_backfill` after `pipeline_start` returns `{"success": true}` is the queued snapshot, not a stall. Deploy and warehouse rows are outside this skill.
