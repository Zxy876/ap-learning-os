#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except ImportError:
    service_account = None
    build = None

from import_compile_snapshot import connect
from process_writebacks import WRITEBACK_HEADERS, load_json, pending_writebacks


BASE = Path(__file__).resolve().parents[1]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def credentials_from_env():
    if service_account is None or build is None:
        raise SystemExit("Google Sheets writeback requires google-api-python-client and google-auth.")
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        info = json.loads(raw_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if path:
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    adc_path = Path("~/.config/gcloud/application_default_credentials.json").expanduser()
    if adc_path.exists():
        try:
            import google.auth
            creds, _ = google.auth.default(scopes=SCOPES)
            return creds
        except Exception:
            pass
    raise SystemExit("No Google credentials found. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS.")


def col_letter(index):
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def sheet_values(service, spreadsheet_id, sheet_name, range_a1):
    return service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!{range_a1}",
    ).execute().get("values", [])


def ensure_headers(service, spreadsheet_id, sheet_name, header_row=3):
    values = sheet_values(service, spreadsheet_id, sheet_name, f"{header_row}:{header_row}")
    headers = values[0] if values else []
    mapping = {str(value).strip(): idx + 1 for idx, value in enumerate(headers) if str(value).strip()}
    updates = []
    next_col = len(headers) + 1
    for header in WRITEBACK_HEADERS.values():
        if header not in mapping:
            mapping[header] = next_col
            updates.append({
                "range": f"'{sheet_name}'!{col_letter(next_col)}{header_row}",
                "values": [[header]],
            })
            next_col += 1
    if updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    return mapping


def write_rows_to_google_sheet(conn, spreadsheet_id, rows):
    if build is None:
        raise SystemExit("Google Sheets writeback requires google-api-python-client and google-auth.")
    creds = credentials_from_env()
    service = build("sheets", "v4", credentials=creds)
    written = 0
    failed = 0
    by_sheet = {}
    for row in rows:
        sheet = row["target_sheet"] or row["source_sheet"]
        if sheet:
            by_sheet.setdefault(sheet, []).append(row)
    for sheet_name, group in by_sheet.items():
        try:
            header_map = ensure_headers(service, spreadsheet_id, sheet_name)
            data = []
            for row in group:
                target_row = row["target_row"] or row["source_row_number"]
                if not target_row:
                    failed += 1
                    conn.execute(
                        "UPDATE spreadsheet_writebacks SET status = ?, payload_json = ? WHERE id = ?",
                        ("failed", json.dumps({"error": "missing target row"}, ensure_ascii=False), row["id"]),
                    )
                    continue
                payload = load_json(row["payload_json"], {})
                values = {
                    "review_status": payload.get("final_state", ""),
                    "failure_type": payload.get("failure_type", ""),
                    "review_message": payload.get("message", ""),
                    "reviewed_at": payload.get("written_at") or "",
                    "task_date": payload.get("scheduled_date", ""),
                    "task_title": payload.get("title", ""),
                }
                for key, header in WRITEBACK_HEADERS.items():
                    col = header_map[header]
                    data.append({
                        "range": f"'{sheet_name}'!{col_letter(col)}{target_row}",
                        "values": [[values.get(key, "")]],
                    })
                conn.execute(
                    "UPDATE spreadsheet_writebacks SET status = ?, payload_json = ? WHERE id = ?",
                    (
                        "written_google",
                        json.dumps({**payload, "google_spreadsheet_id": spreadsheet_id}, ensure_ascii=False),
                        row["id"],
                    ),
                )
                written += 1
            if data:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": data},
                ).execute()
        except Exception as exc:
            failed += len(group)
            for row in group:
                conn.execute(
                    "UPDATE spreadsheet_writebacks SET status = ?, payload_json = ? WHERE id = ?",
                    ("failed", json.dumps({"error": str(exc)}, ensure_ascii=False), row["id"]),
                )
    conn.commit()
    return {"spreadsheet_id": spreadsheet_id, "pending": len(rows), "written": written, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="Apply pending AP Learning OS writebacks to Google Sheets.")
    parser.add_argument("--db", default=str(BASE / "data" / "online_platform" / "aplos_dev.sqlite3"))
    parser.add_argument("--spreadsheet-id", default=os.getenv("APLOS_GOOGLE_SHEET_ID", ""))
    args = parser.parse_args()
    if not args.spreadsheet_id:
        raise SystemExit("Missing --spreadsheet-id or APLOS_GOOGLE_SHEET_ID.")
    conn = connect(args.db)
    print(json.dumps(write_rows_to_google_sheet(conn, args.spreadsheet_id, pending_writebacks(conn)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
