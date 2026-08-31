---
name: pipeline-setup
description: Creates an Artie pipeline from a source connector — creating the connector first if needed — attaches a destination and tables, and starts it. Use when the user wants a new pipeline, first pipeline, or to save a source/destination then replicate. Do not use for type-support questions, Fivetran/DMS migrations, pipeline health or error logs, or checking whether data landed in the warehouse.
---

# First pipeline setup

Take a source connector to `pipeline_start` returning `{"success": true}`. That is the done-when. Do not claim a row landed in the warehouse — MCP cannot verify that. `pipeline_usage` is lag and row counts, not a warehouse SELECT. `pipeline_error_logs` is health, not this skill.

Get saved UUIDs, or create them. Then create-from-source, `pipeline_detail` if you need to reload FullPipeline, update, start. Do not invent a third path.

## Connectors

1. Call `connector_list` with `includeSourceConnectors=true` and find the source by `label` / `uuid`. Source slugs include `postgresql`, `mysql`, `mssql`, `oracle`, `mongodb`, `dynamodb`, `documentdb`, `cockroach`, `planetscale`, `keyspaces`, `api`.
2. Call `connector_list` without that flag for destinations (`snowflake`, `bigquery`, `redshift`, `databricks`, `motherduck`, `clickhouse`, `s3`, `gcs`, `iceberg`, `delta`, and warehouse copies of `postgresql` / `mysql` / `mssql`).
3. `isValid` on the list is not a live ping. List has no `sharedConfig`.

### Saved connector

Call `connector_detail` on the UUID. That is the only extra vs list: `sharedConfig` (masked placeholders) and `defaultDatabase`. To ping it, pass that payload into `unsaved_connector_ping` and **keep `uuid` set** so stored secrets unmask. Do not invent a uuid-only ping.

### Missing connector

Ask type, label, host, user, password, and type-specific fields. Confirm before sending secrets. Do not echo passwords.

1. **`unsaved_connector_ping`** with `type`, `sharedConfig`, and `connectionRole` (`source` or `destination`). This is not a uuid ping — do not pass a pipeline uuid or `sourceReaderUUID`. Postgres needs `defaultDatabase` (database name), Oracle a service name, S3 a bucket — same field. Success is `{"success": true}`. A JSON `error` field means host or credentials failed.
2. **`connector_create`** with the same payload (no uuid). Keep the returned UUID.

Do not call `unsaved_connector_fetch_databases`, `unsaved_connector_fetch_schemas`, or `unsaved_connector_fetch_tables`. Fetch after the connector is saved.

`defaultDatabase` on ping or create is not the reader `database` on `pipeline_create_from_source`.

## Sequence (follow exactly)

Create-from-source, reload FullPipeline with `pipeline_detail` when you do not still have the create response, update, start.

1. **Source database / schema**
   - Postgres, Cockroach, Oracle, SQL Server: **`connector_fetch_databases`** on the source UUID. Ask the user which database if more than one. For Postgres, Cockroach, and Oracle the reader needs this name before start.
   - MySQL: do **not** call `connector_fetch_databases` (`HasDatabases` is false). `SHOW DATABASES` is **`connector_fetch_schemas`**. Ask which schema if more than one.
   - Do **not** copy a `defaultDatabase` field into the reader database.
2. **`pipeline_create_from_source`** with:
   - `sourceConnectorUUID` — the saved source
   - `database` — the name from step 1 when the source is Postgres, Cockroach, or Oracle
   - Do **not** pass `sourceType` (creates an empty connector)
   - Do **not** pass `destinationType` (creates a stub destination)
3. Keep the **FullPipeline** from `pipeline_create_from_source`. If you no longer have it (new chat, only a uuid from `pipeline_list`), call **`pipeline_detail`** on that uuid. Do **not** pass `includeRelatedObjects` — MCP returns 400 (that flag wraps connectors for the Dashboard UI). `pipeline_list` is a summary and is not a valid update body.
4. **`connector_fetch_tables`** on the **source** UUID. If step 1 produced a database name (Postgres, Cockroach, Oracle, SQL Server), pass it as `databaseName` — do not omit it and do not fall back to `defaultDatabase`. For MySQL, pass the chosen schema as `schemaName` and skip `databaseName`. `schemaName` is otherwise optional; Postgres defaults to `public`, SQL Server to `dbo`. If the source has schemas other than the default, or more than one schema, call `connector_fetch_schemas` on the **source** first (same `databaseName` when you have one), then pass the chosen `schemaName` into fetch-tables. Do not pass a destination schema into this call.
5. If the table list is empty, leave the draft as-is. Say the source has no tables Artie can see and **do not** call `pipeline_start`.
6. **`pipeline_update`** — full replace, not a PATCH:
   - Echo the last FullPipeline (create, a previous update, or `pipeline_detail`)
   - Set `destinationUUID` to the saved destination
   - Set `tables` to at least one `{name, schema}` from step 4 (`schema` is the **source** schema)
   - Send destination and tables **together**. A destination-only body is rejected. Omitting `tables` deletes every table.
   - Keep `dataPlaneName` from the echo. Echo the rest of `specificDestCfg`.
   - Dest landing is not the source schema. If this destination uses a warehouse database/schema (Snowflake, BigQuery, Redshift, …), call `connector_fetch_databases` / `connector_fetch_schemas` on the **destination** UUID. Those calls return available names, not “the” landing location — ask the user which database and schema to land in if more than one, the same way step 1 asks for the source database. Set `specificDestCfg.database` / `specificDestCfg.schema` to **that choice**. Do not pick the first name, do not copy step 4, and do not overwrite values already on the echo unless the user picks something else. If dest fetch is unsupported (S3, GCS, …), leave those fields as echoed.
7. **`pipeline_start`**. Success is `{"success": true}` (Dashboard HTTP 204; the MCP tool result does not include the status code). Do not call it immediately after create-from-source, and do not call it without destination + tables.

Never follow create-from-source with `pipeline_create`. That attaches another pipeline to an existing reader (fan-out).

If the user already has a pipeline and wants to add tables or change dest: `pipeline_list` → `pipeline_detail` (no `includeRelatedObjects`) → `pipeline_update` (echo FullPipeline) → `pipeline_start` if it is still a draft. Do not build the update body from `pipeline_list`.

## Fan-out (second destination, same capture)

If the user wants another destination on the **same** CDC capture, stop. Sharing a reader is [Terraform `is_shared`](https://www.artie.com/docs/guides/artie/multiple-destinations). Do not create a second dedicated reader and do not start a second capture named `artie`.

## What not to say

- Do not say data landed, first record verified, or the destination SELECT succeeded.
- Do not echo connector credentials. Passwords on `connector_detail` are placeholders.
- Do not call `pipeline_error_logs` or treat `pipeline_usage` lag as “the pipeline started.”
- Compatibility questions (types, SQL Server capture method, SSH vs PrivateLink) belong in `connector-compatibility`.
- Fivetran / DMS mapping belongs in `migration`.
