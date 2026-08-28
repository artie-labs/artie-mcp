---
name: pipeline-setup
description: Creates a draft Artie pipeline from a saved source connector, attaches a saved destination and tables, and starts it. Use when the user already has connectors in the Artie Dashboard and wants a new pipeline, first pipeline, or to replicate an existing source. Do not use for type-support questions, Fivetran/DMS migrations, entering credentials, or checking whether data landed in the warehouse.
---

# First pipeline setup

Take a **saved** source connector to `pipeline_start` returning `{"success": true}`. That is the done-when. Do not claim a row landed in the warehouse — MCP cannot verify that.

This only works on connectors already saved in the Dashboard. There is no credential-entry tool.

## Preconditions

1. Call `connector_list` with `includeSourceConnectors=true` and find the source by `label` / `uuid`. Source slugs include `postgresql`, `mysql`, `mssql`, `oracle`, `mongodb`, `dynamodb`, `documentdb`, `cockroach`, `planetscale`, `keyspaces`, `api`.
2. Call `connector_list` without that flag for destinations (`snowflake`, `bigquery`, `redshift`, `databricks`, `motherduck`, `clickhouse`, `s3`, `gcs`, `iceberg`, `delta`, and warehouse copies of `postgresql` / `mysql` / `mssql`).
3. If the source or destination is missing, stop. Tell the user to save it in the [Artie Dashboard](https://app.artie.com), then resume this skill. Do not call `connector_create` or any `unsaved_*` tool.

## Sequence (follow exactly)

Do not invent a second path. Create-from-source, echo, start.

1. **`connector_fetch_databases`** on the source UUID. Ask the user which database if more than one. For Postgres, Cockroach, and Oracle the reader needs this name before start.
2. **`pipeline_create_from_source`** with:
   - `sourceConnectorUUID` — the saved source
   - `database` — the name from step 1 (do **not** copy a `defaultDatabase` field; that is not the reader database)
   - Do **not** pass `sourceType` (creates an empty connector)
   - Do **not** pass `destinationType` (creates a stub destination)
3. Keep the **FullPipeline** in the create response. `pipeline_list` is a summary and is not a valid update body. `pipeline_detail` is not on MCP.
4. **`connector_fetch_tables`** on the **source** UUID. If step 1 produced a database name (Postgres, Cockroach, Oracle), pass it as `databaseName` — do not omit it and do not fall back to `defaultDatabase`. `schemaName` is optional; Postgres defaults to `public`, SQL Server to `dbo`. If the source has schemas other than the default, or more than one schema, call `connector_fetch_schemas` on the **source** first (same `databaseName` when you have one), then pass the chosen `schemaName` into fetch-tables. Do not pass a destination schema into this call.
5. If the table list is empty, leave the draft as-is. Say the source has no tables Artie can see and **do not** call `pipeline_start`.
6. **`pipeline_update`** — full replace, not a PATCH:
   - Echo the last FullPipeline
   - Set `destinationUUID` to the saved destination
   - Set `tables` to at least one `{name, schema}` from step 4 (`schema` is the **source** schema)
   - Send destination and tables **together**. A destination-only body is rejected. Omitting `tables` deletes every table.
   - Keep `dataPlaneName` from the echo. Echo the rest of `specificDestCfg`.
   - Dest landing is not the source schema. If this destination uses a warehouse database/schema (Snowflake, BigQuery, Redshift, …), call `connector_fetch_databases` / `connector_fetch_schemas` on the **destination** UUID. Those calls return available names, not “the” landing location — ask the user which database and schema to land in if more than one, the same way step 1 asks for the source database. Set `specificDestCfg.database` / `specificDestCfg.schema` to **that choice**. Do not pick the first name, do not copy step 4, and do not overwrite values already on the echo unless the user picks something else. If dest fetch is unsupported (S3, GCS, …), leave those fields as echoed.
7. **`pipeline_start`**. Success is `{"success": true}` (Dashboard HTTP 204; the MCP tool result does not include the status code). Do not call it immediately after create-from-source, and do not call it without destination + tables.

Never follow create-from-source with `pipeline_create`. That attaches another pipeline to an existing reader (fan-out).

## Fan-out (second destination, same capture)

If the user wants another destination on the **same** CDC capture, stop. Sharing a reader is [Terraform `is_shared`](https://www.artie.com/docs/guides/artie/multiple-destinations). Do not create a second dedicated reader and do not start a second capture named `artie`.

## What not to say

- Do not say data landed, first record verified, or the destination SELECT succeeded.
- Do not enter or echo connector credentials.
- Compatibility questions (types, SQL Server capture method, SSH vs PrivateLink) belong in `connector-compatibility`.
- Fivetran / DMS mapping belongs in `migration`.
