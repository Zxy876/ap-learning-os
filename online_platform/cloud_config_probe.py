#!/usr/bin/env python3
import json
import os
from pathlib import Path


ENV_GROUPS = {
    "s3_compatible": [
        "APLOS_S3_BUCKET",
        "APLOS_S3_ENDPOINT_URL",
        "APLOS_S3_REGION",
        "APLOS_S3_ACCESS_KEY_ID",
        "APLOS_S3_SECRET_ACCESS_KEY",
        "APLOS_PUBLIC_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AWS_S3_BUCKET",
        "AWS_ENDPOINT_URL_S3",
    ],
    "auth": [
        "APLOS_AUTHOR_TOKEN",
        "APLOS_EXECUTOR_TOKEN",
        "APLOS_REVIEWER_TOKEN",
    ],
    "google": [
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ],
    "database": [
        "DATABASE_URL",
        "POSTGRES_URL",
        "SUPABASE_DB_URL",
    ],
}

COMMON_FILES = [
    "~/.aws/credentials",
    "~/.aws/config",
    "~/.config/rclone/rclone.conf",
    "~/.config/gcloud/application_default_credentials.json",
]


def mask(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def main():
    result = {"env": {}, "files": []}
    for group, names in ENV_GROUPS.items():
        result["env"][group] = [
            {"name": name, "present": bool(os.getenv(name)), "preview": mask(os.getenv(name))}
            for name in names
        ]
    for raw in COMMON_FILES:
        path = Path(raw).expanduser()
        result["files"].append({"path": str(path), "exists": path.exists()})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
