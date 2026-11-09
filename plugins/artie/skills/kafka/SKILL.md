---
name: kafka
description: >
  Inspects and changes Artie Kafka clusters, Managed or BYOC: cluster health,
  throughput, consumer lag, storage and topic sizes, topics, and Kafka users.
  Use when the user asks about a Kafka cluster, topic, partition, retention,
  tiered storage, consumer group or lag, disk usage, or Kafka users and ACLs,
  or wants to create, change or delete a topic or user — even without saying
  "Kafka". Do not use for CDC pipeline lag or health (monitoring), pipeline
  setup, creating Kafka users or reading passwords, or creating, resizing
  or deleting a cluster.
---

## Pick the cluster type first

Call `kafka_cluster_list` and match `name` or `uuid` — never guess. `isManaged` decides which tools work; the wrong family returns 400 (settings and graphs return `supported: false`).

| | Managed (`isManaged: true`) | BYOC (`isManaged: false`) |
|---|---|---|
| Config | `kafka_cluster_detail` (adds `managed`: brokers, instance type, storage, retention, `pendingChange`) | `kafka_cluster_settings` (Strimzi only; MSK gets `supported: false`) |
| Throughput | `kafka_cluster_rates` (`range` `1h` or `6h`; 409 unless `status` is `active`) | not available |
| Consumer lag | `kafka_consumer_group_details` (every group in one call) | `kafka_consumer_group_list` → `kafka_consumer_group_detail` per group |
| Users | `kafka_managed_user_list` (with ACLs) | `kafka_user_list`; detail via `kafka_user_detail` (`producer_consumer`) or `kafka_admin_user_detail` (`admin`) by `accessProfile` |

Both types: `kafka_cluster_summary`, `kafka_topic_list`, `kafka_topic_detail`, `kafka_topic_sizes`, `kafka_consumer_group_list`, `kafka_consumer_group_detail`, and on Strimzi clusters `kafka_cluster_storage_graph` and `kafka_cluster_metrics_graph` (broker, topic and partition counts, CPU, memory).

## Cluster health

Fewest calls for "is my cluster healthy?":

1. `kafka_cluster_list` row: `status` (`draft`, `active`, `deploying`, `failed` with `statusMessage`, `deleted`).
2. Throughput and lag — Managed: one `kafka_cluster_rates` (cluster messages and bytes per second, per-topic messages in, per-group lag and `readPerSecond`). BYOC: `kafka_consumer_group_detail` for the groups the user cares about (`topics[].partitions[].lag`).
3. Storage: `kafka_cluster_storage_graph` (disk use over `from`/`to` against `threshold`), then `kafka_topic_sizes` for the biggest topics (`partitions[].sizeBytes`, plus `remoteSizeBytes` when tiered).

- `supported: false` on a graph or settings read means that data doesn't exist for this cluster — say so and quote `reason`.
- Lists and sizes are cached (topics 2 min, consumer groups 2 min or 10 s on Managed). Pass `forceRefresh=true` only when the user needs it fresh.
- `kafka_topic_latest_message` returns real message contents from partition 0, and only if the company allows reading messages. Call it only when the user asks to see a message, and don't repeat values they didn't ask for.

## Topic changes

Every change needs explicit user confirmation of the exact cluster, topic and values. Read first: `kafka_topic_list` or `kafka_topic_detail` for current `partitionCount`, `retentionMS`, `tieredStorage` and `artieManaged`.

| Change | Tool | Notes |
|---|---|---|
| Create | `kafka_topic_create` | `topic`, `partitionCount`, `replicationFactor`, optional `configEntries`. BYOC (shared) cluster: name must start with `<companyUUID>.customer.`. Managed: any name except `__*` and `strimzi.cruisecontrol.*`. |
| Retention, tiered storage | `kafka_topic_settings_update` | Send only what changes. `retentionMS` ≥ 86400000 (1 day) or `-1` (forever). `tieredStorage`: `on` → `paused` → `off`; `off` deletes the topic's remote data. |
| Partitions | `kafka_topic_partitions_increase` | `currentPartitionCount` + `newPartitionCount`. Can't be undone; breaks per-key ordering. On BYOC, refused on Artie-managed topics. |
| Delete | `kafka_topic_delete` | Deletes the topic and every message. |

- Never change or delete a topic with `artieManaged: true` unless the user named that exact topic and confirmed. Shortening retention on one can drop change events before Artie pipelines read them. `kafka_topic_detail` `pipelines` lists the Artie pipelines on it — name them when confirming.
- Prefer `kafka_topic_settings_update` over `kafka_topic_retention_update` (retention only).
- Managed changes return 409 unless the cluster is `active`. A 400 says why the rules refused it — quote it.

## Users

- Managed: `kafka_managed_user_list`, `kafka_managed_user_update` (replaces **all** ACLs — send the full list; password stays the same), `kafka_managed_user_delete`. Both are company-admin only. `kafka_user_*` and `kafka_admin_user_*` return 400 here.
- BYOC: `kafka_user_list` lists every user, admins included. Delete with `kafka_user_delete` (`producer_consumer`) or `kafka_admin_user_delete` (`admin`). A 200 with `warning` means deletion is still pending.
- Deleting a user cuts off every client using it within seconds. Confirm the username first.

## Not available through MCP

Send the user to the [Artie Dashboard](https://app.artie.com) or the Artie Terraform provider / API for:

- Creating Kafka users and reading or rotating passwords (agents never handle Kafka credentials).
- Creating, renaming, resizing (brokers, instance type, storage), restoring or deleting a cluster; broker settings, allowed CIDRs, storage autoscale, cluster-wide tiered storage.
- Reading more than the latest message of a topic.

## Reply

Lead with the cluster's name, uuid and type (Managed or BYOC), then what you found. For a change, say what was sent and what the tool returned — "deletion pending" when it returned a warning.
