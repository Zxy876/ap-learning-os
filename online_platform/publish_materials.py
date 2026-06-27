#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from import_compile_snapshot import connect
from storage_adapters import BASE, DEFAULT_STORAGE_ROOT, LocalStorageAdapter, adapter_from_args, file_digest


PDF_PREVIEW_MIN_BYTES = int(os.getenv("APLOS_PDF_PREVIEW_MIN_BYTES", str(8 * 1024 * 1024)))
PDF_PREVIEW_MAX_PAGES = int(os.getenv("APLOS_PDF_PREVIEW_MAX_PAGES", "80"))
PDF_PREVIEW_SCALE = float(os.getenv("APLOS_PDF_PREVIEW_SCALE", "1.35"))
PDF_PREVIEW_JPEG_QUALITY = int(os.getenv("APLOS_PDF_PREVIEW_JPEG_QUALITY", "72"))


def rewrite_local_target(local_target):
    rewrites = {}
    raw = os.getenv("APLOS_LOCAL_PATH_REWRITES_JSON", "")
    if raw:
        rewrites.update(json.loads(raw))
    source = os.getenv("APLOS_LOCAL_PATH_REWRITE_FROM", "")
    target = os.getenv("APLOS_LOCAL_PATH_REWRITE_TO", "")
    if source and target:
        rewrites[source] = target
    for old_prefix, new_prefix in sorted(rewrites.items(), key=lambda item: len(item[0]), reverse=True):
        if local_target.startswith(old_prefix):
            return f"{new_prefix.rstrip('/')}/{local_target[len(old_prefix):].lstrip('/')}"
    return local_target


def preview_storage_key(source_path):
    digest = file_digest(source_path)
    return f"material_previews/{digest[:2]}/{digest}-preview.pdf"


def linearized_storage_key(source_path):
    digest = file_digest(source_path)
    return f"material_previews/{digest[:2]}/{digest}-linearized.pdf"


def create_linearized_pdf(source_path, output_path):
    if not shutil.which("qpdf"):
        return None
    source_path = Path(source_path)
    output_path = Path(output_path)
    if source_path.suffix.lower() != ".pdf" or source_path.stat().st_size < PDF_PREVIEW_MIN_BYTES:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["qpdf", "--linearize", str(source_path), str(output_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        if output_path.exists():
            output_path.unlink()
        return None
    return output_path if output_path.exists() else None


def create_pdf_preview(source_path, output_path):
    try:
        import fitz
    except Exception:
        return None
    source_path = Path(source_path)
    output_path = Path(output_path)
    if source_path.suffix.lower() != ".pdf" or source_path.stat().st_size < PDF_PREVIEW_MIN_BYTES:
        return None
    source = fitz.open(source_path)
    try:
        if source.page_count > PDF_PREVIEW_MAX_PAGES:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        matrix = fitz.Matrix(PDF_PREVIEW_SCALE, PDF_PREVIEW_SCALE)
        for page in source:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_bytes = pix.tobytes("jpeg", jpg_quality=PDF_PREVIEW_JPEG_QUALITY)
            out_page = doc.new_page(width=page.rect.width, height=page.rect.height)
            out_page.insert_image(page.rect, stream=image_bytes)
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
    finally:
        source.close()
    return output_path


def publish_browser_target(adapter, local_target):
    published = adapter.publish(local_target)
    if not isinstance(adapter, LocalStorageAdapter):
        return published
    source = Path(local_target)
    preview_key = preview_storage_key(source)
    preview_path = adapter.storage_root / preview_key
    preview = create_pdf_preview(source, preview_path)
    if preview and preview.exists() and preview.stat().st_size < source.stat().st_size:
        browser_url = f"{adapter.base_url}/files/{preview_key}" if adapter.base_url else f"/files/{preview_key}"
        return type(published)(storage_key=preview_key, browser_url=browser_url)
    linear_key = linearized_storage_key(source)
    linear_path = adapter.storage_root / linear_key
    linearized = create_linearized_pdf(source, linear_path)
    if linearized:
        browser_url = f"{adapter.base_url}/files/{linear_key}" if adapter.base_url else f"/files/{linear_key}"
        return type(published)(storage_key=linear_key, browser_url=browser_url)
    return published


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
        "non_file_targets": [],
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
        local_target = rewrite_local_target(row["local_target"])
        if not local_target or not Path(local_target).exists():
            result["missing_local_files"].append({"material_id": row["id"], "local_target": local_target})
            continue
        if not Path(local_target).is_file():
            result["non_file_targets"].append({"material_id": row["id"], "local_target": local_target})
            continue
        published = publish_browser_target(adapter, local_target)
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
