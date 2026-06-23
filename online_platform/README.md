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

Run the local API skeleton:

```bash
python3 online_platform/api_server.py \
  --db data/online_platform/aplos_dev.sqlite3 \
  --port 8776
```

Example API calls:

```bash
curl "http://127.0.0.1:8776/api/workspace/today?date=2026-06-22"
curl "http://127.0.0.1:8776/api/review/queue"
```

Create evidence for a task:

```bash
curl -X POST "http://127.0.0.1:8776/api/tasks/TASK_ID/evidence" \
  -H "Content-Type: application/json" \
  -d '{"artifact_type":"note","text_note":"Worked in browser for 35 minutes."}'
```

Submit and decide review:

```bash
curl -X POST "http://127.0.0.1:8776/api/tasks/TASK_ID/review-requests"
curl -X POST "http://127.0.0.1:8776/api/review/requests/REVIEW_ID/decision" \
  -H "Content-Type: application/json" \
  -d '{"final_state":"not_completed","failure_type":"insufficient_evidence","message":"Need clearer screenshot evidence."}'
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
