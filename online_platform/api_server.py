#!/usr/bin/env python3
import argparse
import base64
import copy
import datetime as dt
import json
import mimetypes
import os
import re
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from import_compile_snapshot import connect, dumps, import_snapshot, stable_id, summary
from learning_os import RESOURCE_RESOLUTION_CACHE, compile_snapshot, load_config
from process_writebacks import process_writebacks
from publish_materials import publish_materials
from storage_adapters import LocalStorageAdapter, S3CompatibleStorageAdapter


DEFAULT_STORAGE_ROOT = BASE / "data" / "online_platform" / "storage"
DEFAULT_UPLOAD_ROOT = BASE / "uploads"
STATIC_ROOT = Path(__file__).resolve().parent / "static"


FINAL_STATES = {"completed", "partial", "not_completed", "failed", "blocked"}
FAILURE_TYPES = {
    "",
    "insufficient_evidence",
    "wrong_resource",
    "insufficient_time",
    "incomplete_work",
    "low_quality_work",
    "misunderstood_task",
    "access_blocked",
    "technical_blocked",
    "external_blocked",
    "other",
}

ROLE_TOKENS = {
    "author": "APLOS_AUTHOR_TOKEN",
    "executor": "APLOS_EXECUTOR_TOKEN",
    "reviewer": "APLOS_REVIEWER_TOKEN",
}


def row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def scalar(row, fallback=0):
    if row is None:
        return fallback
    if isinstance(row, dict):
        return next(iter(row.values()), fallback)
    return row[0]


def json_loads(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def json_default(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)


def today_tasks(conn, date):
    active_compile_ids = active_compile_ids_by_course(conn)
    rows = conn.execute(
        """
        SELECT ti.id, ti.plan_compile_id, ti.scheduled_date, ti.course, ti.unit, ti.phase, ti.title, ti.runner, ti.kind,
               ti.status, ti.target_minutes, ti.observable_goal, ti.completion_criteria_json,
               ti.source_lineage_json, ti.browser_workflow_json
        FROM task_instances ti
        JOIN plan_compiles pc ON pc.id = ti.plan_compile_id
        WHERE ti.scheduled_date = ?
        ORDER BY ti.course, ti.title
        """,
        (date,),
    ).fetchall()
    tasks = []
    for row in rows:
        if active_compile_ids.get(row["course"]) == row["plan_compile_id"]:
            tasks.append(task_payload(conn, row["id"], include_materials=False))
    return tasks


def compile_tasks_for_date(conn, compile_id, date):
    row = find_plan_compile(conn, compile_id)
    if not row:
        raise KeyError("compile not found")
    rows = conn.execute(
        """
        SELECT ti.id
        FROM task_instances ti
        WHERE ti.plan_compile_id = ? AND ti.scheduled_date = ?
        ORDER BY ti.course, ti.title
        """,
        (row["id"], date),
    ).fetchall()
    return [task_payload(conn, item["id"], include_materials=True) for item in rows]


def active_compile_ids_by_course(conn):
    rows = conn.execute(
        """
        SELECT id, status, courses_json, imported_at
        FROM plan_compiles
        WHERE status IN ('active', 'compiled')
        ORDER BY imported_at DESC
        """
    ).fetchall()
    active = {}
    compiled_fallback = {}
    for row in rows:
        courses = json_loads(row["courses_json"], [])
        for course in courses:
            if row["status"] == "active" and course not in active:
                active[course] = row["id"]
            elif row["status"] == "compiled" and course not in compiled_fallback:
                compiled_fallback[course] = row["id"]
    for course, compile_id in compiled_fallback.items():
        active.setdefault(course, compile_id)
    return active


def task_payload(conn, task_id, include_materials=True):
    row = conn.execute("SELECT * FROM task_instances WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    task = row_to_dict(row)
    task["completion_criteria"] = json_loads(task.pop("completion_criteria_json"), [])
    task["source_lineage"] = json_loads(task.pop("source_lineage_json"), {})
    task["browser_workflow"] = json_loads(task.pop("browser_workflow_json"), [])
    task["evidence_count"] = scalar(conn.execute(
        "SELECT COUNT(*) FROM evidence_artifacts WHERE task_instance_id = ?",
        (task_id,),
    ).fetchone())
    task["open_review_request_count"] = scalar(conn.execute(
        "SELECT COUNT(*) FROM review_requests WHERE task_instance_id = ? AND status = 'open'",
        (task_id,),
    ).fetchone())
    if include_materials:
        material_rows = conn.execute(
            """
            SELECT tm.role, tm.open_order, mr.*
            FROM task_materials tm
            JOIN material_records mr ON mr.id = tm.material_record_id
            WHERE tm.task_instance_id = ?
            ORDER BY tm.open_order
            """,
            (task_id,),
        ).fetchall()
        task["materials"] = [material_payload(row) for row in material_rows]
        task["evidence"] = [
            row_to_dict(item)
            for item in conn.execute(
                "SELECT * FROM evidence_artifacts WHERE task_instance_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        ]
    return task


def material_payload(row):
    data = row_to_dict(row)
    data["index"] = json_loads(data.pop("index_json"), {})
    for key in ["upload_required", "browser_openable", "missing"]:
        data[key] = bool(data[key])
    return data


def storage_path(storage_root, storage_key):
    if not storage_key or ".." in storage_key:
        return None
    path = (storage_root / storage_key).resolve()
    try:
        path.relative_to(storage_root.resolve())
    except ValueError:
        return None
    return path


def safe_filename(name):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "evidence.bin").strip(".-")
    return cleaned or "evidence.bin"


def decode_upload_file(file_payload, required=False):
    if not file_payload:
        if required:
            raise ValueError("required file is missing")
        return None
    raw = file_payload.get("data_base64") or ""
    if "," in raw and raw.split(",", 1)[0].startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError(f"{file_payload.get('filename') or 'uploaded file'} is not valid base64") from exc
    max_bytes = int(os.getenv("APLOS_MAX_AUTHOR_UPLOAD_BYTES", str(100 * 1024 * 1024)))
    if len(data) > max_bytes:
        raise ValueError(f"uploaded file is too large; max {max_bytes} bytes")
    return {
        "filename": safe_filename(file_payload.get("filename") or "upload.bin"),
        "content_type": file_payload.get("content_type") or "",
        "data": data,
    }


def safe_extract_zip(zip_path, output_dir):
    extracted = 0
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                continue
            target = (output_dir / member_path).resolve()
            try:
                target.relative_to(output_dir.resolve())
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as source, target.open("wb") as dest:
                dest.write(source.read())
            extracted += 1
    return extracted


def infer_plan_course(filename):
    name = filename.lower()
    if any(token in name for token in ["csa", "computer", "java", "计算机"]):
        return "AP_CSA"
    if any(token in name for token in ["bc", "calculus", "微积分"]):
        return "AP_Calculus_BC"
    return None


def review_queue(conn):
    rows = conn.execute(
        """
        SELECT rr.id AS review_request_id, rr.status AS review_status, rr.created_at AS requested_at,
               ti.id AS task_instance_id, ti.scheduled_date, ti.course, ti.unit, ti.phase,
               ti.title, ti.status AS task_status, ti.target_minutes,
               COUNT(ea.id) AS evidence_count
        FROM review_requests rr
        JOIN task_instances ti ON ti.id = rr.task_instance_id
        LEFT JOIN evidence_artifacts ea ON ea.task_instance_id = ti.id
        WHERE rr.status = 'open'
        GROUP BY rr.id
        ORDER BY rr.created_at ASC
        """
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def compile_summaries(conn):
    rows = conn.execute(
        """
        SELECT pc.*
        FROM plan_compiles pc
        ORDER BY pc.imported_at DESC
        """
    ).fetchall()
    summaries = []
    for row in rows:
        payload = row_to_dict(row)
        payload["courses"] = json_loads(payload.pop("courses_json"), [])
        payload["rules"] = json_loads(payload.pop("rules_json"), {})
        payload.pop("source_snapshot_json", None)
        payload["phase_pools"] = scalar(conn.execute("SELECT COUNT(*) FROM phase_pools WHERE plan_compile_id = ?", (row["id"],)).fetchone())
        payload["plan_steps"] = scalar(conn.execute("SELECT COUNT(*) FROM plan_steps WHERE plan_compile_id = ?", (row["id"],)).fetchone())
        payload["task_instances"] = scalar(conn.execute("SELECT COUNT(*) FROM task_instances WHERE plan_compile_id = ?", (row["id"],)).fetchone())
        payload["material_records"] = scalar(conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ?", (row["id"],)).fetchone())
        payload["published_materials"] = scalar(conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND browser_url != ''", (row["id"],)).fetchone())
        payload["missing_materials"] = scalar(conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND missing = 1", (row["id"],)).fetchone())
        summaries.append(payload)
    return summaries


def find_plan_compile(conn, compile_id):
    return conn.execute(
        "SELECT * FROM plan_compiles WHERE compile_id = ? OR id = ?",
        (compile_id, compile_id),
    ).fetchone()


def publish_compile(conn, compile_id):
    row = find_plan_compile(conn, compile_id)
    if not row:
        raise KeyError("compile not found")
    courses = json_loads(row["courses_json"], [])
    now = dt.datetime.now().isoformat()
    for course in courses:
        related = conn.execute(
            """
            SELECT id, courses_json
            FROM plan_compiles
            WHERE id != ? AND status IN ('active', 'compiled')
            """,
            (row["id"],),
        ).fetchall()
        for item in related:
            if course in json_loads(item["courses_json"], []):
                conn.execute("UPDATE plan_compiles SET status = 'archived' WHERE id = ?", (item["id"],))
    conn.execute("UPDATE plan_compiles SET status = 'active', generated_at = COALESCE(NULLIF(generated_at, ''), ?) WHERE id = ?", (now, row["id"]))
    conn.commit()
    return next((item for item in compile_summaries(conn) if item["id"] == row["id"]), None)


def writeback_queue(conn):
    rows = conn.execute(
        """
        SELECT sw.id, sw.status, sw.target_sheet, sw.target_row, sw.target_column,
               sw.created_at, sw.payload_json, pr.source_workbook
        FROM spreadsheet_writebacks sw
        LEFT JOIN plan_rows pr ON pr.id = sw.plan_row_id
        ORDER BY sw.created_at DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        item = row_to_dict(row)
        item["payload"] = json_loads(item.pop("payload_json"), {})
        out.append(item)
    return out


def add_evidence(conn, task_id, payload):
    if not conn.execute("SELECT 1 FROM task_instances WHERE id = ?", (task_id,)).fetchone():
        raise KeyError("task not found")
    artifact_type = payload.get("artifact_type") or "note"
    evidence_id = stable_id("evidence", task_id, artifact_type, payload.get("storage_key"), payload.get("text_note"), dt.datetime.now().isoformat())
    conn.execute(
        """
        INSERT INTO evidence_artifacts
          (id, task_instance_id, artifact_type, storage_key, text_note, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            task_id,
            artifact_type,
            payload.get("storage_key") or "",
            payload.get("text_note") or "",
            dumps(payload.get("metadata") or {}),
        ),
    )
    conn.execute("UPDATE task_instances SET status = 'needs_review' WHERE id = ? AND status = 'planned'", (task_id,))
    conn.commit()
    return row_to_dict(conn.execute("SELECT * FROM evidence_artifacts WHERE id = ?", (evidence_id,)).fetchone())


def add_evidence_upload(conn, storage_root, task_id, payload):
    if not conn.execute("SELECT 1 FROM task_instances WHERE id = ?", (task_id,)).fetchone():
        raise KeyError("task not found")
    raw = payload.get("data_base64") or ""
    if "," in raw and raw.split(",", 1)[0].startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("data_base64 must be valid base64") from exc
    max_bytes = int(os.getenv("APLOS_MAX_EVIDENCE_BYTES", str(20 * 1024 * 1024)))
    if len(data) > max_bytes:
        raise ValueError(f"evidence file is too large; max {max_bytes} bytes")
    filename = safe_filename(payload.get("filename") or "evidence.bin")
    evidence_id = stable_id("evidence", task_id, filename, len(data), dt.datetime.now().isoformat())
    storage_key = f"evidence/{task_id}/{evidence_id}-{filename}"
    output_path = storage_path(storage_root, storage_key)
    if not output_path:
        raise ValueError("invalid storage key")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    conn.execute(
        """
        INSERT INTO evidence_artifacts
          (id, task_instance_id, artifact_type, storage_key, text_note, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            task_id,
            payload.get("artifact_type") or "file",
            storage_key,
            payload.get("text_note") or "",
            dumps({
                "filename": filename,
                "content_type": payload.get("content_type") or "",
                "size_bytes": len(data),
            }),
        ),
    )
    conn.execute("UPDATE task_instances SET status = 'needs_review' WHERE id = ? AND status = 'planned'", (task_id,))
    conn.commit()
    return row_to_dict(conn.execute("SELECT * FROM evidence_artifacts WHERE id = ?", (evidence_id,)).fetchone())


def create_review_request(conn, task_id):
    if not conn.execute("SELECT 1 FROM task_instances WHERE id = ?", (task_id,)).fetchone():
        raise KeyError("task not found")
    existing = conn.execute(
        "SELECT * FROM review_requests WHERE task_instance_id = ? AND status = 'open'",
        (task_id,),
    ).fetchone()
    if existing:
        return row_to_dict(existing)
    request_id = stable_id("review", task_id, dt.datetime.now().isoformat())
    conn.execute(
        "INSERT INTO review_requests (id, task_instance_id, status) VALUES (?, ?, 'open')",
        (request_id, task_id),
    )
    conn.execute("UPDATE task_instances SET status = 'needs_review' WHERE id = ?", (task_id,))
    conn.commit()
    return row_to_dict(conn.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone())


def compile_from_uploaded_plans(conn, storage_root, payload):
    plan_payloads = payload.get("plan_files") or []
    if payload.get("bc_plan_file"):
        plan_payloads.append({**payload["bc_plan_file"], "course": "AP_Calculus_BC"})
    if payload.get("csa_plan_file"):
        plan_payloads.append({**payload["csa_plan_file"], "course": "AP_CSA"})
    if not plan_payloads:
        raise ValueError("choose at least one plan Excel file")
    plan_files = [decode_upload_file(item, required=True) | {"course": item.get("course")} for item in plan_payloads]
    resource_zip = decode_upload_file(payload.get("resource_zip_file"), required=False)

    start = dt.date.fromisoformat(payload.get("start_date") or dt.date.today().isoformat())
    days = int(payload.get("days") or 30)
    if days < 1 or days > 370:
        raise ValueError("days must be between 1 and 370")

    upload_id = stable_id("authorupload", start.isoformat(), days, ",".join(item["filename"] for item in plan_files), dt.datetime.now().isoformat())
    upload_root = Path(os.getenv("APLOS_UPLOAD_ROOT", str(DEFAULT_UPLOAD_ROOT))) / "author" / upload_id
    plans_dir = upload_root / "plans"
    resources_dir = upload_root / "resources"
    plans_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    uploaded_courses = {}
    unknown_files = []
    for item in plan_files:
        course = item.get("course") or infer_plan_course(item["filename"])
        plan_path = plans_dir / item["filename"]
        plan_path.write_bytes(item["data"])
        if course in {"AP_Calculus_BC", "AP_CSA"}:
            uploaded_courses[course] = str(plan_path)
        else:
            unknown_files.append(item["filename"])
    if unknown_files:
        raise ValueError(f"could not infer course from plan filename(s): {', '.join(unknown_files)}")

    extracted_files = 0
    if resource_zip:
        zip_path = upload_root / resource_zip["filename"]
        zip_path.write_bytes(resource_zip["data"])
        extracted_files = safe_extract_zip(zip_path, resources_dir)

    config = copy.deepcopy(load_config())
    config["workspace_root"] = str(resources_dir)
    config.setdefault("plans", {})
    config["plans"].update(uploaded_courses)
    RESOURCE_RESOLUTION_CACHE.clear()
    course = payload.get("course") or (next(iter(uploaded_courses)) if len(uploaded_courses) == 1 else None)
    snapshot = compile_snapshot(config, start, days, course=course, include_materials=True)

    snapshot_path = upload_root / f"compile_snapshot_{snapshot['compile_id']}.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    plan_compile_id = import_snapshot(
        conn,
        snapshot,
        payload.get("organization_id") or "org_uploaded_ap_learning_os",
        payload.get("organization_name") or "Uploaded AP Learning OS",
    )
    conn.execute("UPDATE plan_compiles SET status = 'sandbox' WHERE id = ?", (plan_compile_id,))
    conn.commit()
    public_base_url = payload.get("base_url") or os.getenv("APLOS_PUBLIC_BASE_URL", "")
    publish_result = publish_materials(conn, LocalStorageAdapter(storage_root, public_base_url)) if payload.get("publish_materials", True) else None
    result = summary(conn, plan_compile_id)
    result.update({
        "upload_id": upload_id,
        "snapshot_path": str(snapshot_path),
        "uploaded_courses": sorted(uploaded_courses),
        "resource_zip_extracted_files": extracted_files,
        "publish_result": publish_result,
    })
    return result


def decide_review(conn, review_request_id, payload):
    final_state = payload.get("final_state")
    if final_state not in FINAL_STATES:
        raise ValueError(f"final_state must be one of {sorted(FINAL_STATES)}")
    failure_type = payload.get("failure_type") or ""
    if failure_type not in FAILURE_TYPES:
        raise ValueError(f"failure_type must be one of {sorted(FAILURE_TYPES)}")
    request = conn.execute(
        "SELECT * FROM review_requests WHERE id = ?",
        (review_request_id,),
    ).fetchone()
    if not request:
        raise KeyError("review request not found")
    if request["status"] != "open":
        raise ValueError("review request is already decided")
    task = conn.execute(
        """
        SELECT ti.*, ps.plan_row_id
        FROM task_instances ti
        LEFT JOIN plan_steps ps ON ps.id = ti.plan_step_id
        WHERE ti.id = ?
        """,
        (request["task_instance_id"],),
    ).fetchone()
    decision_id = stable_id("decision", review_request_id, final_state, dt.datetime.now().isoformat())
    conn.execute(
        """
        INSERT INTO review_decisions
          (id, review_request_id, final_state, failure_type, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            review_request_id,
            final_state,
            failure_type,
            payload.get("message") or "",
        ),
    )
    conn.execute("UPDATE review_requests SET status = 'decided' WHERE id = ?", (review_request_id,))
    conn.execute("UPDATE task_instances SET status = ? WHERE id = ?", (final_state, task["id"]))

    if final_state != "completed":
        delay_days = int(payload.get("delay_days") or 1)
        delay_scope = payload.get("delay_scope") or "course_local"
        scheduled = dt.date.fromisoformat(task["scheduled_date"])
        conn.execute(
            """
            INSERT INTO schedule_delay_events
              (id, task_instance_id, course, effective_date, days, scope, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stable_id("delay", task["id"], decision_id),
                task["id"],
                task["course"],
                (scheduled + dt.timedelta(days=1)).isoformat(),
                delay_days,
                delay_scope,
                final_state,
            ),
        )

    writeback_payload = {
        "task_instance_id": task["id"],
        "scheduled_date": task["scheduled_date"],
        "course": task["course"],
        "title": task["title"],
        "final_state": final_state,
        "failure_type": failure_type,
        "message": payload.get("message") or "",
    }
    target_row = None
    target_sheet = ""
    if task["plan_row_id"]:
        plan_row = conn.execute("SELECT source_sheet, source_row_number FROM plan_rows WHERE id = ?", (task["plan_row_id"],)).fetchone()
        if plan_row:
            target_sheet = plan_row["source_sheet"] or ""
            target_row = plan_row["source_row_number"]
    conn.execute(
        """
        INSERT INTO spreadsheet_writebacks
          (id, review_decision_id, plan_row_id, target_sheet, target_row, target_column, status, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            stable_id("writeback", decision_id, task["plan_row_id"]),
            decision_id,
            task["plan_row_id"],
            target_sheet,
            target_row,
            payload.get("target_column") or "review_status",
            dumps(writeback_payload),
        ),
    )
    conn.commit()
    return {
        "decision": row_to_dict(conn.execute("SELECT * FROM review_decisions WHERE id = ?", (decision_id,)).fetchone()),
        "task": task_payload(conn, task["id"], include_materials=False),
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "APLearningOSAPI/0.1"

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    @property
    def conn(self):
        return self.server.conn

    def require_role(self, role):
        if os.getenv("APLOS_DISABLE_ROLE_TOKENS", "1").lower() in {"1", "true", "yes"}:
            return True
        token_name = ROLE_TOKENS[role]
        expected = os.getenv(token_name)
        if not expected:
            return True
        auth = self.headers.get("Authorization", "")
        supplied = auth.removeprefix("Bearer ").strip()
        if supplied == expected:
            return True
        self.send_json(403, {"error": f"{role} token required"})
        return False

    def require_any_role(self, roles):
        if os.getenv("APLOS_DISABLE_ROLE_TOKENS", "1").lower() in {"1", "true", "yes"}:
            return True
        configured = [(role, os.getenv(ROLE_TOKENS[role])) for role in roles]
        configured = [(role, token) for role, token in configured if token]
        if not configured:
            return True
        auth = self.headers.get("Authorization", "")
        supplied = auth.removeprefix("Bearer ").strip()
        if any(supplied == token for _, token in configured):
            return True
        self.send_json(403, {"error": f"one of these role tokens is required: {', '.join(roles)}"})
        return False

    def send_file(self, storage_key, include_body=True):
        file_path = storage_path(self.server.storage_root, storage_key)
        if not file_path or not file_path.exists() or not file_path.is_file():
            self.send_json(404, {"error": "file not found"})
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = file_path.read_bytes() if include_body else b""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def send_static(self, relative_path, include_body=True):
        if relative_path in {"", "/", "workspace", "review", "author"}:
            relative_path = "index.html"
        if ".." in relative_path:
            self.send_json(404, {"error": "not found"})
            return
        file_path = (STATIC_ROOT / relative_path.lstrip("/")).resolve()
        try:
            file_path.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self.send_json(404, {"error": "not found"})
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_json(404, {"error": "not found"})
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = file_path.read_bytes() if include_body else b""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_json(200, {"ok": True})

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/files/"):
            self.send_file(path.removeprefix("/files/").lstrip("/"), include_body=False)
            return
        if path.startswith("/static/"):
            self.send_static(path.removeprefix("/static/"), include_body=False)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if path in {"/", "/workspace", "/review", "/author"}:
                self.send_static(path.lstrip("/"))
                return
            if path.startswith("/static/"):
                self.send_static(path.removeprefix("/static/"))
                return
            if path == "/api/health":
                self.send_json(200, {"ok": True})
                return
            if path == "/api/workspace/today":
                if not self.require_role("executor"):
                    return
                date = query.get("date", [dt.date.today().isoformat()])[0]
                self.send_json(200, {"date": date, "tasks": today_tasks(self.conn, date)})
                return
            if path.startswith("/api/tasks/"):
                if not self.require_any_role(["executor", "reviewer"]):
                    return
                task_id = path.split("/")[-1]
                task = task_payload(self.conn, task_id)
                if not task:
                    self.send_json(404, {"error": "task not found"})
                    return
                self.send_json(200, task)
                return
            if path.startswith("/files/"):
                self.send_file(path.removeprefix("/files/").lstrip("/"))
                return
            if path == "/api/review/queue":
                if not self.require_role("reviewer"):
                    return
                self.send_json(200, {"review_requests": review_queue(self.conn)})
                return
            if path == "/api/author/compiles":
                if not self.require_role("author"):
                    return
                self.send_json(200, {"compiles": compile_summaries(self.conn)})
                return
            if path.startswith("/api/author/compiles/") and path.endswith("/summary"):
                if not self.require_role("author"):
                    return
                compile_id = path.split("/")[-2]
                row = find_plan_compile(self.conn, compile_id)
                if not row:
                    self.send_json(404, {"error": "compile not found"})
                    return
                payload = row_to_dict(row)
                payload["task_instances"] = scalar(self.conn.execute("SELECT COUNT(*) FROM task_instances WHERE plan_compile_id = ?", (row["id"],)).fetchone())
                payload["upload_required_materials"] = scalar(self.conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND upload_required = 1", (row["id"],)).fetchone())
                payload["missing_materials"] = scalar(self.conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND missing = 1", (row["id"],)).fetchone())
                self.send_json(200, payload)
                return
            if path.startswith("/api/author/compiles/") and path.endswith("/preview"):
                if not self.require_role("author"):
                    return
                compile_id = path.split("/")[-2]
                date = query.get("date", [dt.date.today().isoformat()])[0]
                self.send_json(200, {
                    "compile_id": compile_id,
                    "date": date,
                    "tasks": compile_tasks_for_date(self.conn, compile_id, date),
                })
                return
            if path == "/api/writebacks":
                if not self.require_role("author"):
                    return
                self.send_json(200, {"writebacks": writeback_queue(self.conn)})
                return
            self.send_json(404, {"error": "not found"})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            payload = self.read_json()
            if path.startswith("/api/tasks/") and path.endswith("/evidence"):
                if not self.require_role("executor"):
                    return
                task_id = path.split("/")[-2]
                self.send_json(201, add_evidence(self.conn, task_id, payload))
                return
            if path.startswith("/api/tasks/") and path.endswith("/evidence-upload"):
                if not self.require_role("executor"):
                    return
                task_id = path.split("/")[-2]
                self.send_json(201, add_evidence_upload(self.conn, self.server.storage_root, task_id, payload))
                return
            if path.startswith("/api/tasks/") and path.endswith("/review-requests"):
                if not self.require_role("executor"):
                    return
                task_id = path.split("/")[-2]
                self.send_json(201, create_review_request(self.conn, task_id))
                return
            if path.startswith("/api/review/requests/") and path.endswith("/decision"):
                if not self.require_role("reviewer"):
                    return
                review_request_id = path.split("/")[-2]
                self.send_json(201, decide_review(self.conn, review_request_id, payload))
                return
            if path == "/api/author/compiles/import":
                if not self.require_role("author"):
                    return
                snapshot = payload.get("snapshot")
                if isinstance(snapshot, str):
                    snapshot = json.loads(snapshot)
                if not isinstance(snapshot, dict):
                    raise ValueError("snapshot must be a compile snapshot object or JSON string")
                if snapshot.get("schema_version") != "aplos.compile_snapshot.v1":
                    raise ValueError(f"unsupported schema_version: {snapshot.get('schema_version')}")
                plan_compile_id = import_snapshot(
                    self.conn,
                    snapshot,
                    payload.get("organization_id") or "org_hosted_ap_learning_os",
                    payload.get("organization_name") or "Hosted AP Learning OS",
                )
                self.conn.execute("UPDATE plan_compiles SET status = 'sandbox' WHERE id = ?", (plan_compile_id,))
                self.conn.commit()
                self.send_json(201, summary(self.conn, plan_compile_id))
                return
            if path.startswith("/api/author/compiles/") and path.endswith("/publish"):
                if not self.require_role("author"):
                    return
                compile_id = path.split("/")[-2]
                self.send_json(200, publish_compile(self.conn, compile_id))
                return
            if path == "/api/author/materials/publish":
                if not self.require_role("author"):
                    return
                backend = (payload.get("backend") if payload else None) or os.getenv("APLOS_STORAGE_BACKEND", "local")
                if backend == "s3":
                    adapter = S3CompatibleStorageAdapter.from_env()
                elif backend == "local":
                    public_base_url = (payload.get("base_url") if payload else None) or os.getenv("APLOS_PUBLIC_BASE_URL", "")
                    adapter = LocalStorageAdapter(self.server.storage_root, public_base_url)
                else:
                    raise ValueError("backend must be local or s3")
                self.send_json(200, publish_materials(self.conn, adapter))
                return
            if path == "/api/author/compile-from-plans":
                if not self.require_role("author"):
                    return
                self.send_json(201, compile_from_uploaded_plans(self.conn, self.server.storage_root, payload))
                return
            if path == "/api/writebacks/run":
                if not self.require_role("author"):
                    return
                self.send_json(200, process_writebacks(
                    self.conn,
                    output_dir=payload.get("output_dir") if payload else None,
                    in_place=bool(payload.get("in_place")) if payload else False,
                ))
                return
            self.send_json(404, {"error": "not found"})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


class ApiServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, db_path, storage_root):
        super().__init__(server_address, handler_class)
        self.conn = connect(db_path)
        self.storage_root = Path(storage_root)


def main():
    parser = argparse.ArgumentParser(description="Run the local AP Learning OS online-platform API skeleton.")
    parser.add_argument("--db", default=os.getenv("APLOS_DB_PATH", str(BASE / "data" / "online_platform" / "aplos_dev.sqlite3")))
    parser.add_argument("--host", default=os.getenv("APLOS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("APLOS_PORT", "8776")))
    parser.add_argument("--storage-root", default=os.getenv("APLOS_STORAGE_ROOT", str(DEFAULT_STORAGE_ROOT)))
    args = parser.parse_args()
    server = ApiServer((args.host, args.port), ApiHandler, args.db, args.storage_root)
    print(f"AP Learning OS API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
