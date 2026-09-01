---
name: migration
description: Plans a Fivetran-to-Artie lift-and-shift — intake questions, concept mapping, gaps that do not translate, and an ordered cutover. Use when the user is migrating off Fivetran or asks how Fivetran connectors map to Artie. Do not parse Fivetran exports, invent DMS mappings, create pipelines, or claim first-record verification.
---

# Migration lift-and-shift (Fivetran)

Intake + mapping. There is no Fivetran or DMS config parser. v1 is **Fivetran only**. If they ask about DMS or another vendor, say that mapping is not written yet and stay on questions + Artie docs.

Do not claim you read a Fivetran export, HAR, or API dump.

## Intake

Ask a short list. Do not block forever — map what they give and flag holes.

1. **Sources** — which Fivetran connectors (Postgres, MySQL, SQL Server, Salesforce, …)? Hosted how (RDS, Cloud SQL, on-prem)?
2. **Tables / schemas** — what must move first? Any Fivetran metadata schemas they should skip?
3. **Destination** — warehouse and database/schema (Snowflake, BigQuery, Redshift, Databricks, …).
4. **Sync** — log-based CDC vs query-based? Scheduled frequency?
5. **Networking** — public + IP allowlist, SSH bastion, or private (PrivateLink)?
6. **Transforms** — Fivetran transformations, dbt, or reverse ETL on the same account?
7. **Cutover** — hard cut vs dual-run? Who consumes the destination tables today?

If they already have an Artie account, `connector_list` (`includeSourceConnectors=true`) and `data_catalog_search` show what is already saved. Use search to separate business tables from leftover Fivetran metadata (`*_FIVETRAN_*`, `FIVETRAN_METADATA`, audit/log schemas). Catalog search is ingested metadata, not a live source walk — live tables are `connector_fetch_tables` on a **connector** UUID.

## Mapping reference

| Fivetran | Artie | Notes |
|---|---|---|
| Database connector (Postgres, MySQL, SQL Server, Oracle, Mongo, Dynamo, …) | Saved **source** connector + pipeline | Artie is CDC into a warehouse, not a scheduled extract. Confirm the engine is on [llms.txt](https://www.artie.com/docs/llms.txt). |
| SaaS connector (Salesforce, HubSpot, ads, …) | **No equivalent** | Artie does not extract SaaS APIs. Leave those on Fivetran or another tool, or land from a database replica if they have one. |
| Destination connector | Saved **destination** connector | Must be a [documented destination](https://www.artie.com/docs/destinations/snowflake). DuckDB → [MotherDuck](https://www.artie.com/docs/destinations/motherduck) only. |
| Sync frequency / incremental cursor | Continuous CDC | There is no “every 15 minutes” on an Artie SQL pipeline. |
| Schema / table selection | Pipeline `tables` | Chosen after create; see `pipeline-setup`. |
| History / soft deletes | Per-table history mode on the Artie pipeline | Confirm on the tables page if they need it; do not invent column names. |
| Transformations / dbt in Fivetran | **Not replaced** | Keep dbt (or warehouse SQL) **after** landing. Say this every time they mention transforms. |
| Reverse ETL / activations | **Not replaced** | Out of Artie. |
| SSH tunnel | [SSH tunnel](https://www.artie.com/docs/connection-options/ssh-tunnel) | |
| Private networking | [PrivateLink](https://www.artie.com/docs/connection-options/privatelink) or [IP allowlist](https://www.artie.com/docs/connection-options) | |
| Hybrid / on-prem agent | Artie data plane / BYOC | Point at architecture docs; do not design IAM here. |
| MAR / usage pricing | Different product | Do not convert Fivetran MAR into Artie cost. |

Anything not in that table is a **gap**. Write it on the plan as “does not translate” rather than stretching a mapping.

## Compatibility, then setup

For each **database** source that maps:

1. Hand off to `connector-compatibility` (types if they asked, SQL Server capture method, networking, permissions).
2. They save source + destination in the [Dashboard](https://app.artie.com) if those connectors do not exist yet.
3. Hand off to `pipeline-setup` for each pipeline. That skill’s done-when is `pipeline_start` 204, not a warehouse row.

Do not run those sequences yourself unless the user clearly wants you to execute after the plan. This skill produces the plan.

## Cutover plan (order)

1. List Fivetran connectors → Artie equivalent or explicit gap (especially SaaS + transforms).
2. Compatibility + networking for each mapped database source.
3. Save connectors; start Artie pipelines (`pipeline-setup`).
4. Dual-run: Fivetran and Artie both write, or Artie writes a parallel schema. MCP cannot confirm rows landed — the customer (or warehouse access) checks that.
5. Repoint consumers when they accept parity.
6. Pause / decommission Fivetran for the mapped connectors only. Leave SaaS and transform jobs where they are.

## What not to say

- Do not claim first-record verification or destination SELECT.
- Do not call `connector_create` or parse a Fivetran JSON/CSV export.
- Do not produce a DMS runbook.
