# Online Platform Data Layer

This folder contains the first importable data layer for the online AP Learning
OS.

It is not the final hosted app. It is a local database harness that proves the
compiler snapshot can become durable records:

```text
compile_snapshot.json -> SQL tables -> author/executor/reviewer APIs later
```

## Smoke Test

Generate a snapshot:

```bash
python3 learning_os.py compile-export --start 2026-06-22 --days 7
```

Import it into a local SQLite database:

```bash
python3 online_platform/import_compile_snapshot.py \
  --snapshot data/exports/compile_snapshot_2026-06-22_7d.json \
  --db data/online_platform/aplos_dev.sqlite3
```

Inspect summary:

```bash
python3 online_platform/import_compile_snapshot.py \
  --snapshot data/exports/compile_snapshot_2026-06-22_7d.json \
  --db data/online_platform/aplos_dev.sqlite3 \
  --summary-only
```

## What This Imports

- organization placeholder
- uploaded plan source placeholders
- compile snapshot
- phase pools
- plan rows
- plan steps
- material records
- task instances

Local files are not uploaded here. They are recorded as `upload_required`
materials. The hosted version must upload them to object storage and replace
local paths with storage keys.

## Why SQLite First

The user has not provided a server, Postgres URL, object storage bucket, or auth
provider yet. SQLite lets us validate the importer contract now without
inventing credentials.

The schema is intentionally close to the Postgres model in
`docs/online_platform_api.md`.

