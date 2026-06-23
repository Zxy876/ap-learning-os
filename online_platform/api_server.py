#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from import_compile_snapshot import connect, dumps, stable_id


BASE = Path(__file__).resolve().parents[1]
DEFAULT_STORAGE_ROOT = BASE / "data" / "online_platform" / "storage"
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


def row_to_dict(row):
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def json_loads(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def today_tasks(conn, date):
    rows = conn.execute(
        """
        SELECT id, scheduled_date, course, unit, phase, title, runner, kind,
               status, target_minutes, observable_goal, completion_criteria_json,
               source_lineage_json, browser_workflow_json
        FROM task_instances
        WHERE scheduled_date = ?
        ORDER BY course, title
        """,
        (date,),
    ).fetchall()
    return [task_payload(conn, row["id"], include_materials=False) for row in rows]


def task_payload(conn, task_id, include_materials=True):
    row = conn.execute("SELECT * FROM task_instances WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    task = row_to_dict(row)
    task["completion_criteria"] = json_loads(task.pop("completion_criteria_json"), [])
    task["source_lineage"] = json_loads(task.pop("source_lineage_json"), {})
    task["browser_workflow"] = json_loads(task.pop("browser_workflow_json"), [])
    task["evidence_count"] = conn.execute(
        "SELECT COUNT(*) FROM evidence_artifacts WHERE task_instance_id = ?",
        (task_id,),
    ).fetchone()[0]
    task["open_review_request_count"] = conn.execute(
        "SELECT COUNT(*) FROM review_requests WHERE task_instance_id = ? AND status = 'open'",
        (task_id,),
    ).fetchone()[0]
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
        payload["phase_pools"] = conn.execute("SELECT COUNT(*) FROM phase_pools WHERE plan_compile_id = ?", (row["id"],)).fetchone()[0]
        payload["plan_steps"] = conn.execute("SELECT COUNT(*) FROM plan_steps WHERE plan_compile_id = ?", (row["id"],)).fetchone()[0]
        payload["task_instances"] = conn.execute("SELECT COUNT(*) FROM task_instances WHERE plan_compile_id = ?", (row["id"],)).fetchone()[0]
        payload["material_records"] = conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ?", (row["id"],)).fetchone()[0]
        payload["published_materials"] = conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND browser_url != ''", (row["id"],)).fetchone()[0]
        payload["missing_materials"] = conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND missing = 1", (row["id"],)).fetchone()[0]
        summaries.append(payload)
    return summaries


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
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
                date = query.get("date", [dt.date.today().isoformat()])[0]
                self.send_json(200, {"date": date, "tasks": today_tasks(self.conn, date)})
                return
            if path.startswith("/api/tasks/"):
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
                self.send_json(200, {"review_requests": review_queue(self.conn)})
                return
            if path == "/api/author/compiles":
                self.send_json(200, {"compiles": compile_summaries(self.conn)})
                return
            if path.startswith("/api/author/compiles/") and path.endswith("/summary"):
                compile_id = path.split("/")[-2]
                row = self.conn.execute("SELECT * FROM plan_compiles WHERE compile_id = ? OR id = ?", (compile_id, compile_id)).fetchone()
                if not row:
                    self.send_json(404, {"error": "compile not found"})
                    return
                payload = row_to_dict(row)
                payload["task_instances"] = self.conn.execute("SELECT COUNT(*) FROM task_instances WHERE plan_compile_id = ?", (row["id"],)).fetchone()[0]
                payload["upload_required_materials"] = self.conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND upload_required = 1", (row["id"],)).fetchone()[0]
                payload["missing_materials"] = self.conn.execute("SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND missing = 1", (row["id"],)).fetchone()[0]
                self.send_json(200, payload)
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
                task_id = path.split("/")[-2]
                self.send_json(201, add_evidence(self.conn, task_id, payload))
                return
            if path.startswith("/api/tasks/") and path.endswith("/review-requests"):
                task_id = path.split("/")[-2]
                self.send_json(201, create_review_request(self.conn, task_id))
                return
            if path.startswith("/api/review/requests/") and path.endswith("/decision"):
                review_request_id = path.split("/")[-2]
                self.send_json(201, decide_review(self.conn, review_request_id, payload))
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
    parser.add_argument("--db", default=str(BASE / "data" / "online_platform" / "aplos_dev.sqlite3"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8776)
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT))
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
