# Local Online API Smoke Flow

This document covers the local HTTP API skeleton in `online_platform/api_server.py`.

The API is not production auth, storage, or deployment. It is a runnable proof
that the online A/B/C workflow can operate against imported compile data.

## Prepare Data

```bash
python3 learning_os.py compile-export \
  --start 2026-06-22 \
  --days 7 \
  --output data/exports/api_smoke_2026-06-22_7d.json

python3 online_platform/import_compile_snapshot.py \
  --snapshot data/exports/api_smoke_2026-06-22_7d.json \
  --db data/online_platform/api_smoke.sqlite3
```

## Start API

```bash
python3 online_platform/api_server.py \
  --db data/online_platform/api_smoke.sqlite3 \
  --port 8776
```

Health check:

```bash
curl "http://127.0.0.1:8776/api/health"
```

## B: Executor Routes

Get today's tasks:

```bash
curl "http://127.0.0.1:8776/api/workspace/today?date=2026-06-22"
```

Get a task with materials/evidence:

```bash
curl "http://127.0.0.1:8776/api/tasks/TASK_ID"
```

Add evidence:

```bash
curl -X POST "http://127.0.0.1:8776/api/tasks/TASK_ID/evidence" \
  -H "Content-Type: application/json" \
  -d '{"artifact_type":"note","text_note":"Worked in browser for 35 minutes."}'
```

Submit review request:

```bash
curl -X POST "http://127.0.0.1:8776/api/tasks/TASK_ID/review-requests"
```

## C: Reviewer Routes

Open review queue:

```bash
curl "http://127.0.0.1:8776/api/review/queue"
```

Decide review:

```bash
curl -X POST "http://127.0.0.1:8776/api/review/requests/REVIEW_ID/decision" \
  -H "Content-Type: application/json" \
  -d '{
    "final_state": "not_completed",
    "failure_type": "insufficient_evidence",
    "message": "Need clearer screenshot evidence.",
    "delay_scope": "course_local",
    "delay_days": 1
  }'
```

Effects:

- task status changes to the final state
- review request closes
- review decision is stored
- non-completed decisions create a schedule delay event
- spreadsheet writeback is queued with source sheet and source row

## A: Author Route

Get compile summary:

```bash
curl "http://127.0.0.1:8776/api/author/compiles/COMPILE_ID/summary"
```

## Verified Smoke Result

Using a 2-day compile from `2026-06-22`:

```text
task_instances: 4
task_materials: 32
review decision: not_completed
schedule_delay_events: 1
spreadsheet_writebacks: 1 pending row writeback
```

