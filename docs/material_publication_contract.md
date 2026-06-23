# Material Publication Contract

The local compiler and importer know which materials a task needs, but a web
executor cannot open local macOS file paths. Materials must be published into a
browser-addressable store.

Local MVP:

```text
local_target -> data/online_platform/storage/{storage_key} -> /files/{storage_key}
```

Hosted version:

```text
local_target/uploaded file -> S3/R2/Supabase Storage object -> signed URL or CDN URL
```

## Local Command

```bash
python3 online_platform/publish_materials.py \
  --db data/online_platform/aplos_dev.sqlite3 \
  --base-url http://127.0.0.1:8776
```

This updates `material_records`:

```text
storage_key
browser_url
```

`browser_url` is what the B/executor browser workflow should open.

## API File Route

The local API serves published files through:

```text
GET /files/{storage_key}
HEAD /files/{storage_key}
```

Example:

```bash
curl -I "http://127.0.0.1:8776/files/materials/42/example.pdf"
```

## Import Rules

Materials with `target_type = url` do not need local publication. Their
`browser_url` should be the external URL.

Materials with `upload_required = true` must be published before a browser-only
workflow can use them.

Materials with `missing = true` should stay visible in the author sandbox and
block publish unless the author explicitly accepts the missing item.

## Verified Local Smoke

Using a 1-day compile from `2026-06-22`:

```text
material_records: 14
published: 14
missing_local_files: 0
HEAD /files/...: 200 application/pdf
```

## Production Replacement

Replace `publish_materials.py` with an object-storage adapter that:

- uploads files to storage
- records `storage_key`
- records a stable `browser_url` or signed URL policy
- keeps source lineage and page ranges intact
- avoids exposing private files without authorization

