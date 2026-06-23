# Tencent Cloud CVM Deployment

This guide deploys the current AP Learning OS web prototype to a Tencent Cloud
CVM instance.

Do not send server passwords, private keys, or cloud secrets through chat. Put
secrets directly on your Mac or on the server.

## What You Need To Provide

Non-secret values:

```text
server_public_ip
ssh_user
domain_name, optional
server_os
```

Secret values to configure locally or on the server:

```text
SSH private key or password
APLOS_AUTHOR_TOKEN
APLOS_EXECUTOR_TOKEN
APLOS_REVIEWER_TOKEN
object storage keys, optional
Google credentials, optional
```

## Tencent Security Group

Open inbound ports:

```text
22/tcp    SSH
8776/tcp  AP Learning OS prototype
80/tcp    optional HTTP reverse proxy
443/tcp   optional HTTPS reverse proxy
```

For a private test, restrict `8776/tcp` to your own IP.

## Server Setup

Ubuntu example:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

Clone:

```bash
git clone https://github.com/Zxy876/ap-learning-os.git
cd ap-learning-os
```

Create env file:

```bash
cp .env.production.example .env.production
nano .env.production
```

Set strong role tokens:

```text
APLOS_AUTHOR_TOKEN=...
APLOS_EXECUTOR_TOKEN=...
APLOS_REVIEWER_TOKEN=...
```

SQLite is the default database. To use TencentDB, Supabase, Neon, or another
Postgres-compatible database, also set:

```text
APLOS_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/ap_learning_os
```

Start:

```bash
docker compose -f docker-compose.tencent.yml up -d --build
```

Start with bundled Postgres instead of SQLite:

```bash
docker compose -f docker-compose.postgres.yml up -d --build
```

Check:

```bash
docker logs -f ap-learning-os
curl http://127.0.0.1:8776/api/health
```

Open:

```text
http://SERVER_PUBLIC_IP:8776/author
http://SERVER_PUBLIC_IP:8776/workspace
http://SERVER_PUBLIC_IP:8776/review
```

If port `8776` is not open in the Tencent security group but port `80` is
already served by an nginx container, AP Learning OS can also be reverse
proxied under a subpath:

```text
http://SERVER_PUBLIC_IP/aplos/author
http://SERVER_PUBLIC_IP/aplos/workspace
http://SERVER_PUBLIC_IP/aplos/review
```

In that mode, publish local materials with base URL
`http://SERVER_PUBLIC_IP/aplos` so file URLs become `/aplos/files/...`.

## Browser Plan Upload

The Author page can compile directly from uploaded Excel plans:

1. Open `/aplos/author`.
2. Save the author token.
3. In `Compile From Excel Plans`, choose the BC plan Excel file and CSA plan
   Excel file.
4. Optionally upload a ZIP of resource PDFs. The compiler searches extracted
   resource filenames when matching the plan's resource index.
5. Click `Compile + Import From Excel Plans`.

Server-side upload defaults:

```text
APLOS_UPLOAD_ROOT=/app/uploads
APLOS_MAX_AUTHOR_UPLOAD_BYTES=104857600
```

If nginx is in front of AP Learning OS, its `client_max_body_size` must be at
least as large as the uploaded JSON payload. Base64 adds roughly 33% overhead,
so a 50 MB ZIP needs a limit above 67 MB.

Executor evidence uploads are stored under `APLOS_STORAGE_ROOT/evidence`.
The default upload limit is 20 MB. Override it with:

```text
APLOS_MAX_EVIDENCE_BYTES=20971520
```

## Import A Compile Snapshot

Compile snapshots are generated locally from the plan/resource files, then
imported into the hosted app.

On Mac:

```bash
python3 learning_os.py compile-export --start 2026-06-22 --days 30 \
  --output data/exports/tencent_compile_2026-06-22_30d.json
```

Preferred browser path:

1. Open `http://SERVER_PUBLIC_IP:8776/author`.
2. Enter the author role token if production tokens are enabled.
3. Select or paste the compile snapshot JSON.
4. Click `Import Snapshot`.
5. Click `Publish Local Materials` if source files exist on the server, or
   `Publish S3/COS` if object storage variables are configured.

CLI fallback:

```bash
scp data/exports/tencent_compile_2026-06-22_30d.json USER@SERVER:/home/USER/ap-learning-os/data/exports/
```

On server:

```bash
docker compose -f docker-compose.tencent.yml exec ap-learning-os \
  python online_platform/import_compile_snapshot.py \
    --snapshot data/exports/tencent_compile_2026-06-22_30d.json \
    --db data/online_platform/aplos.sqlite3
```

Publish materials after source files are available on the server:

```bash
docker compose -f docker-compose.tencent.yml exec ap-learning-os \
  python online_platform/publish_materials.py \
    --db data/online_platform/aplos.sqlite3 \
    --base-url http://SERVER_PUBLIC_IP:8776
```

If materials are not copied to the server, author/workspace pages still show
tasks, but file URLs for local PDF material cannot be published.

If compile snapshots were generated on a Mac and materials are copied to
`./uploads/task_materials` on the server, set a path rewrite in
`.env.production`:

```text
APLOS_LOCAL_PATH_REWRITE_FROM=/Users/name/path/AP_Learning_OS/task_materials
APLOS_LOCAL_PATH_REWRITE_TO=/app/uploads/task_materials
```

## Role Tokens In The Browser

If `APLOS_AUTHOR_TOKEN`, `APLOS_EXECUTOR_TOKEN`, or `APLOS_REVIEWER_TOKEN` are
set, each role page requires its token. Paste the matching token into the role
token field at the top of the page and click `Save Token`. The token is stored
in that browser's local storage.

## Tencent COS / Object Storage

The repository includes an S3-compatible adapter. Tencent COS can be connected
if you use a COS S3-compatible endpoint and provide:

```text
APLOS_S3_BUCKET
APLOS_S3_ENDPOINT_URL
APLOS_S3_REGION
APLOS_S3_ACCESS_KEY_ID
APLOS_S3_SECRET_ACCESS_KEY
APLOS_PUBLIC_BASE_URL
```

Then publish with:

```bash
docker compose -f docker-compose.tencent.yml exec ap-learning-os \
  python online_platform/publish_materials.py \
    --backend s3 \
    --db data/online_platform/aplos.sqlite3
```

## Current Production Gaps

- SQLite is still the default runtime database.
- Postgres schema exists, but the API has not been moved to Postgres.
- Role tokens are a simple server-side guard, not a full login system.
- HTTPS should be added before sharing widely.
