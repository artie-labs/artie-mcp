---
name: connector-compatibility
description: Answers Artie connector compatibility questions from published docs — supported sources and destinations, SQL Server capture methods, networking (IP allowlist, SSH tunnel, PrivateLink), and source permissions. Use when the user asks whether a type, source, destination, DuckDB, capture method, or network path is supported before setup. Do not use to create or start pipelines, ping unsaved credentials, or invent a type-support matrix when docs are silent.
---

# Connector compatibility advisor

Docs consultant. There is no live type-support or capture-method API. Answer from published Artie docs. If docs do not cover the type or method, say so — do not invent a matrix.

Start at the docs index: [https://www.artie.com/docs/llms.txt](https://www.artie.com/docs/llms.txt). Open the specific page next. Prefer those pages over memory.

## What you can answer

### Sources and destinations

Published connectors are listed under [Sources](https://www.artie.com/docs/sources/postgresql) and [Destinations](https://www.artie.com/docs/destinations/snowflake) in llms.txt.

- **DuckDB:** Artie destinations include [MotherDuck](https://www.artie.com/docs/destinations/motherduck) only. There is no local DuckDB source or destination.
- A destination appearing in docs is not the same as “this company’s saved connectors.” For what is already saved, `connector_list` (destinations by default; `includeSourceConnectors=true` for sources).
- `connector_fetch_tables` takes a **connector** UUID. A pipeline UUID 404s.

### Data types

There is no per-connector yes/no type matrix in docs.

- General behavior: [Artie's typing library](https://www.artie.com/docs/guides/artie/arties-typing-library) (relational vs non-relational inference; Postgres unconstrained numerics land as strings unless overridden).
- Source-specific notes live on that source page (for example Postgres TOAST on [PostgreSQL](https://www.artie.com/docs/sources/postgresql)).
- If the user names a type and the page is silent, say **unknown — not documented** and point at the source page. Do not guess Oracle / SQL Server / custom-Postgres mappings.

### SQL Server capture methods

Artie documents four methods on [SQL Server overview](https://www.artie.com/docs/sources/microsoft-sql-server/overview). Recommend from that page, not from a private ranking:

| Method | When docs say to use it | Page |
|---|---|---|
| Transaction-log backups | Read completed `.trn` files from a filesystem the data plane can see. Latency follows backup cadence. | Overview |
| CDC with capture instances | CDC enabled at database and table. Default log-based CDC. | [Capture instances](https://www.artie.com/docs/sources/microsoft-sql-server/capture-instances) |
| Change tracking | Lightweight alternative when CDC cannot be enabled. Artie re-reads the row by PK. | [Change tracking](https://www.artie.com/docs/sources/microsoft-sql-server/change-tracking) |
| Active transaction log via SQL access | SQL Server on VM or Azure managed instance only. Needs `FULL`/`BULK_LOGGED`, sysadmin, supplemental logging, PK on each table. | [SQL access](https://www.artie.com/docs/sources/microsoft-sql-server/sql-access) |

Ask which of those constraints they already meet. Do not pick a method if they have not answered.

### Networking

Three documented options: [Connection options](https://www.artie.com/docs/connection-options).

| Option | Use when | Playbook |
|---|---|---|
| Fixed IP allowlist | The database is reachable on the public internet (or a NAT the data plane can hit) and security will allowlist Artie egress IPs. | Customer adds the CIDRs on that page to the DB firewall. Artie connects directly. |
| [SSH tunnel](https://www.artie.com/docs/connection-options/ssh-tunnel) | The database is not directly reachable; a bastion is. | Customer runs the bastion and gives Artie tunnel credentials in the Dashboard. Artie connects through the tunnel. |
| [AWS PrivateLink](https://www.artie.com/docs/connection-options/privatelink) | Traffic must stay off the public internet in AWS. | Customer and Artie complete the PrivateLink setup on that page. |

Recommend one from architecture (public vs private, AWS vs not, bastion vs none). Do not run reachability tests. Unsaved ping sends credentials and is not on MCP.

VPC peering is not a documented Artie connection option. Do not offer it.

### Permissions and backfill

- Permissions: open the **source** page and use its service-account / grants accordion. Do not invent a cross-engine checklist.
- Backfill: [Backfills](https://www.artie.com/docs/pipelines/backfill) — Artie backfills a newly onboarded table by default, in parallel with CDC. There is no MCP tool that picks a backfill method from table size. If they ask “which method is good for me,” summarize that page and stop.

## What you must not do

- Do not create or start a pipeline. Hand off to `pipeline-setup` once connectors are saved in the Dashboard.
- Do not call `connector_create` or `unsaved_*`.
- Do not claim a type is supported or unsupported without a doc sentence you can quote.
- Fivetran / DMS mapping belongs in `migration`.
