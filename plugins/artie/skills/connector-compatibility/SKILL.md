---
name: connector-compatibility
description: >
  Answers whether an Artie source, destination, capture method, type, or
  network path is documented before pipeline setup. Use for compatibility,
  supported-source, supported-destination, SQL Server capture, permissions,
  IP allowlisting, SSH-tunnel, PrivateLink, or type-mapping questions. Do not
  use to create, start, or monitor a pipeline, test credentials, or claim
  support when the current docs are silent.
---

## Check connector compatibility

This is a read-only documentation workflow. Start with [Artie docs index](https://www.artie.com/docs/llms.txt), then read the current page for the named source, destination, or connection method. The index is the source of truth; do not use a remembered support matrix.

1. Identify the requested source, destination, and any required capture, network, or type constraint. Ask only for a missing constraint that changes the answer.
2. Confirm that the source and destination each have a current Artie documentation page. A documented connector does **not** by itself prove a particular source-to-destination type mapping.
3. Read the applicable source and destination pages for prerequisites, supported capture methods, and permissions. Quote the relevant constraint and link the page.
4. For connectivity, choose the documented default that fits the architecture:
   - Publicly reachable database: [fixed data-plane IP allowlisting](https://www.artie.com/docs/connection-options).
   - Private database with a reachable bastion: [SSH tunnel](https://www.artie.com/docs/connection-options/ssh-tunnel).
   - Private AWS connectivity: [AWS PrivateLink](https://www.artie.com/docs/connection-options/privatelink).
5. For type questions, read [Artie’s typing library](https://www.artie.com/docs/guides/artie/arties-typing-library) plus the source/destination pages. State only documented behavior; an undocumented mapping is **not documented**, not unsupported.
6. Reply with `supported`, `not documented`, or `blocked by prerequisite`; name the prerequisite or uncertainty and link the evidence. Hand off setup to `pipeline-setup` only after compatibility is clear.

## SQL Server capture

Use the current [SQL Server overview](https://www.artie.com/docs/sources/microsoft-sql-server/overview) before recommending a method. It currently documents transaction-log backups, CDC capture instances, change tracking, and active transaction-log access through SQL. Match the method to the customer's available infrastructure and permissions; do not invent a ranking, latency expectation, or configuration beyond the linked setup page.

## Gotchas

- Do not call `connector_create`, `unsaved_connector_ping`, or any pipeline mutation. Compatibility does not prove credentials, network reachability, or a successful deployment.
- `connector_list` may answer which connectors are already saved, but not whether a connector type or type mapping is supported.
- Do not infer a destination's schema, a source's permissions, or supported type conversions from another connector. Use the specific page.
- Pipeline health, lag, schema-drift detection, and rows processed belong to `monitoring`; Artie MCP cannot verify that a particular row landed in the destination. Fivetran/DMS cutovers belong to `migration`.
