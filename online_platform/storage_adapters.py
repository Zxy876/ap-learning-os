#!/usr/bin/env python3
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


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


def material_storage_key(path):
    digest = file_digest(path)
    return f"materials/{digest[:2]}/{digest}{safe_suffix(path)}"


@dataclass
class PublishedObject:
    storage_key: str
    browser_url: str


class LocalStorageAdapter:
    def __init__(self, storage_root=DEFAULT_STORAGE_ROOT, base_url=""):
        self.storage_root = Path(storage_root)
        self.base_url = base_url.rstrip("/")

    def publish(self, local_path):
        local_path = Path(local_path)
        storage_key = material_storage_key(local_path)
        output = self.storage_root / storage_key
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            shutil.copy2(local_path, output)
        browser_url = f"{self.base_url}/files/{storage_key}" if self.base_url else f"/files/{storage_key}"
        return PublishedObject(storage_key=storage_key, browser_url=browser_url)


class S3CompatibleStorageAdapter:
    def __init__(
        self,
        bucket,
        endpoint_url=None,
        region=None,
        public_base_url="",
        access_key_id=None,
        secret_access_key=None,
    ):
        try:
            import boto3
        except ImportError as exc:
            raise SystemExit("boto3 is required for --backend s3. Install it or use --backend local.") from exc
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    @classmethod
    def from_env(cls):
        bucket = os.getenv("APLOS_S3_BUCKET") or os.getenv("AWS_S3_BUCKET")
        if not bucket:
            raise SystemExit("Missing APLOS_S3_BUCKET or AWS_S3_BUCKET.")
        return cls(
            bucket=bucket,
            endpoint_url=os.getenv("APLOS_S3_ENDPOINT_URL") or os.getenv("AWS_ENDPOINT_URL_S3"),
            region=os.getenv("APLOS_S3_REGION") or os.getenv("AWS_REGION") or "auto",
            public_base_url=os.getenv("APLOS_PUBLIC_BASE_URL", ""),
            access_key_id=os.getenv("APLOS_S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("APLOS_S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

    def publish(self, local_path):
        local_path = Path(local_path)
        storage_key = material_storage_key(local_path)
        self.client.upload_file(str(local_path), self.bucket, storage_key)
        if self.public_base_url:
            browser_url = f"{self.public_base_url}/{storage_key}"
        else:
            browser_url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": storage_key},
                ExpiresIn=60 * 60 * 24 * 7,
            )
        return PublishedObject(storage_key=storage_key, browser_url=browser_url)


def adapter_from_args(args):
    if args.backend == "s3":
        return S3CompatibleStorageAdapter.from_env()
    return LocalStorageAdapter(storage_root=args.storage_root, base_url=args.base_url)

