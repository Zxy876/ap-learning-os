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

Start:

```bash
docker compose -f docker-compose.tencent.yml up -d --build
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

## Import A Compile Snapshot

For now, compile snapshots are generated locally from the plan/resource files,
then copied to the server.

On Mac:

```bash
python3 learning_os.py compile-export --start 2026-06-22 --days 30 \
  --output data/exports/tencent_compile_2026-06-22_30d.json
```

Copy to server:

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

