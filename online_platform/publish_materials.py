#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from import_compile_snapshot import connect


BASE = Path(__file__).resolve().parents[1]
DEFAULT_STORAGE_ROOT = BASE / "data" / "online_platform" / "storage"


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_suffix(path):
    suffix = Path(path).suffix.lower()
    return suffix if suffix and len(suffix) <= 12 else ".bin"


def publish_materials(conn, storage_root, base_url=""):
    storage_root = Path(storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT id, local_target, external_url, storage_key, browser_url
        FROM material_records
        WHERE missing = 0
        ORDER BY id
        """
    ).fetchall()
    result = {
        "checked": 0,
        "published": 0,
        "already_published": 0,
        "external_urls": 0,
        "missing_local_files": [],
    }
    for row in rows:
        result["checked"] += 1
        if row["external_url"]:
            conn.execute(
                "UPDATE material_records SET browser_url = ? WHERE id = ?",
                (row["external_url"], row["id"]),
            )
            result["external_urls"] += 1
            continue
        if row["storage_key"] and row["browser_url"]:
            result["already_published"] += 1
            continue
        local_target = row["local_target"]
        if not local_target or not Path(local_target).exists():
            result["missing_local_files"].append({"material_id": row["id"], "local_target": local_target})
            continue
        digest = file_digest(local_target)
        storage_key = f"materials/{digest[:2]}/{digest}{safe_suffix(local_target)}"
        output = storage_root / storage_key
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            shutil.copy2(local_target, output)
        browser_url = f"{base_url.rstrip('/')}/files/{storage_key}" if base_url else f"/files/{storage_key}"
        conn.execute(
            "UPDATE material_records SET storage_key = ?, browser_url = ? WHERE id = ?",
            (storage_key, browser_url, row["id"]),
        )
        result["published"] += 1
    conn.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description="Publish local material files into local browser-addressable storage.")
    parser.add_argument("--db", default=str(BASE / "data" / "online_platform" / "aplos_dev.sqlite3"))
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT))
    parser.add_argument("--base-url", default="", help="optional public base URL, for example http://127.0.0.1:8776")
    args = parser.parse_args()
    conn = connect(args.db)
    print(json.dumps(publish_materials(conn, args.storage_root, args.base_url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

