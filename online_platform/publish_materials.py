#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from import_compile_snapshot import connect
from storage_adapters import BASE, DEFAULT_STORAGE_ROOT, adapter_from_args


def publish_materials(conn, adapter):
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
        published = adapter.publish(local_target)
        conn.execute(
            "UPDATE material_records SET storage_key = ?, browser_url = ? WHERE id = ?",
            (published.storage_key, published.browser_url, row["id"]),
        )
        result["published"] += 1
    conn.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description="Publish local material files into local browser-addressable storage.")
    parser.add_argument("--db", default=str(BASE / "data" / "online_platform" / "aplos_dev.sqlite3"))
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT))
    parser.add_argument("--base-url", default="", help="optional public base URL, for example http://127.0.0.1:8776")
    parser.add_argument("--backend", choices=["local", "s3"], default="local")
    args = parser.parse_args()
    conn = connect(args.db)
    print(json.dumps(publish_materials(conn, adapter_from_args(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
