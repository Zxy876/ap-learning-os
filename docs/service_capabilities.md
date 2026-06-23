# Service Capabilities

This document tracks server-side capabilities beyond the local macOS workflow.

## Object Storage

Implemented:

- local storage adapter
- S3-compatible adapter scaffold
- material publication from `local_target` to `storage_key` and `browser_url`

Local command:

```bash
python3 online_platform/publish_materials.py \
  --backend local \
  --db data/online_platform/aplos_dev.sqlite3 \
  --base-url http://127.0.0.1:8776
```

S3-compatible command:

```bash
python3 online_platform/publish_materials.py \
  --backend s3 \
  --db data/online_platform/aplos_dev.sqlite3
```

S3-compatible environment variables:

```text
APLOS_S3_BUCKET
APLOS_S3_ENDPOINT_URL
APLOS_S3_REGION
APLOS_S3_ACCESS_KEY_ID
APLOS_S3_SECRET_ACCESS_KEY
APLOS_PUBLIC_BASE_URL
```

If `APLOS_PUBLIC_BASE_URL` is missing, the adapter generates temporary
presigned URLs.

## Role Tokens

Implemented as a local/server skeleton:

```text
APLOS_AUTHOR_TOKEN
APLOS_EXECUTOR_TOKEN
APLOS_REVIEWER_TOKEN
```

When these variables are unset, local development remains open. When set, API
clients must send:

```text
Authorization: Bearer TOKEN
```

This is not a production identity system. Hosted deployment still needs a real
auth provider such as Clerk, Auth.js, Supabase Auth, or Google OAuth.

## Excel Writeback

Implemented:

- review decisions create `spreadsheet_writebacks`
- writeback processor writes review columns into a derived `.xlsx`
- default behavior never overwrites the source workbook

Command:

```bash
python3 online_platform/process_writebacks.py \
  --db data/online_platform/aplos_dev.sqlite3
```

Generated columns:

```text
APLOS Review Status
APLOS Failure Type
APLOS Review Message
APLOS Reviewed At
APLOS Task Date
APLOS Task Title
```

Use `--in-place` only when intentionally writing into the source workbook.

## Cloud Config Probe

Implemented:

```bash
python3 online_platform/cloud_config_probe.py
```

The probe reports whether known env vars and common credential files exist. It
masks values and does not print secrets.

## Not Yet Implemented

- Google Sheets API writeback
- production Postgres migration
- real user invitation and organization permissions
- deployed HTTPS server
- production object storage authorization policy

