# pipeline_start failures

Read this only when `pipeline_start` 400s or times out. After a `{"success": true}`, do not use this file.

## Slot already in use

If the 400 says two readers share slot `artie`:

If `source_reader_detail` or `source_reader_update` is missing from `tools/list`, send them to the [Artie Dashboard](https://app.artie.com) to set a unique replication slot, then retry `pipeline_start`.

Otherwise:

1. `source_reader_detail` with path `uuid` = the pipeline's `sourceReaderUUID` (not a connector uuid).
2. Set `settings.replicationSlotOverride` to a unique lowercase name (digits/underscores, ≤63).
3. `source_reader_update` with that same path `uuid` and the echoed reader as the body (not wrapped in `pipeline`). Omitting `name`, `database`, or `connectorUUID` blanks them.
4. Call `pipeline_start` again.

## WAL level

If the 400 says WAL level is `replica` (or not `logical`): that is a Postgres server setting, not an Artie config. Tell them to set `wal_level = logical` and restart Postgres, then call `pipeline_start` again. Do not `ALTER SYSTEM` yourself.

## Timeout

`pipeline_detail` once (omit `includeRelatedObjects`).

- `status=running` or `isDeploying=true` — `pipeline_start` already succeeded. Stop.
- Still `draft` — call `pipeline_start` once more. Do not loop.

## After success

`ready_to_backfill` after `{"success": true}` is the queued snapshot, not a stall. Deploy and warehouse rows are outside this skill, as are health, lag, and whether a row landed.
