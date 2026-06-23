#!/usr/bin/env python3
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def stable_id(prefix, *parts):
    raw = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_snapshot(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != "aplos.compile_snapshot.v1":
        raise SystemExit(f"Unsupported schema_version: {data.get('schema_version')}")
    for key in ["compile_id", "phase_pools", "plan_steps", "task_instances"]:
        if key not in data:
            raise SystemExit(f"Snapshot missing required key: {key}")
    return data


def connect(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    migrate(conn)
    return conn


def migrate(conn):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(material_records)").fetchall()}
    if "storage_key" not in columns:
        conn.execute("ALTER TABLE material_records ADD COLUMN storage_key TEXT NOT NULL DEFAULT ''")
    if "browser_url" not in columns:
        conn.execute("ALTER TABLE material_records ADD COLUMN browser_url TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_material_storage_key ON material_records(storage_key)")


def upsert(conn, table, values):
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "id")
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {assignments}"
    )
    conn.execute(sql, [values[column] for column in columns])


def one(conn, query, params=()):
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def material_role(material):
    label = material.get("label") or ""
    if "answer" in label or "key" in label:
        return "answer_key"
    if "checklist" in label:
        return "checklist"
    if "practice" in label or "canvas" in label:
        return "external_practice" if material.get("target_type") == "url" else "practice"
    if label.startswith("task_excerpt"):
        return "primary"
    if label.startswith("resource_index_courseware") or label == "primary_resource":
        return "primary"
    return "supplemental"


def import_snapshot(conn, snapshot, organization_id, organization_name):
    upsert(conn, "organizations", {
        "id": organization_id,
        "name": organization_name,
    })

    for course, path_hint in snapshot.get("source_plans", {}).items():
        upsert(conn, "plan_sources", {
            "id": stable_id("plansource", organization_id, course, path_hint),
            "organization_id": organization_id,
            "title": Path(path_hint).name if path_hint else course,
            "local_path_hint": path_hint or "",
            "course": course,
        })

    plan_compile_id = stable_id("compile", organization_id, snapshot["compile_id"])
    upsert(conn, "plan_compiles", {
        "id": plan_compile_id,
        "organization_id": organization_id,
        "compile_id": snapshot["compile_id"],
        "status": "compiled",
        "schema_version": snapshot["schema_version"],
        "start_date": snapshot["start_date"],
        "days": int(snapshot["days"]),
        "courses_json": dumps(snapshot.get("courses", [])),
        "rules_json": dumps(snapshot.get("rules", {})),
        "source_snapshot_json": dumps({
            "source_plans": snapshot.get("source_plans", {}),
            "import_notes": snapshot.get("import_notes", []),
        }),
        "generated_at": snapshot.get("generated_at") or "",
    })

    phase_ids = {}
    for pool in snapshot.get("phase_pools", []):
        phase_id = stable_id("phase", plan_compile_id, pool.get("course"), pool.get("phase"))
        phase_ids[(pool.get("course"), pool.get("phase"))] = phase_id
        upsert(conn, "phase_pools", {
            "id": phase_id,
            "plan_compile_id": plan_compile_id,
            "course": pool.get("course") or "",
            "phase": pool.get("phase") or "",
            "phase_name": pool.get("phase_name") or "",
            "unit": pool.get("unit") or "",
            "runners_json": dumps(pool.get("runners", {})),
            "resources_json": dumps(pool.get("resources", [])),
        })

    plan_row_ids = {}
    plan_step_ids = {}
    for step in snapshot.get("plan_steps", []):
        source_key = (
            step.get("source_workbook") or "",
            step.get("source_sheet") or "",
            step.get("source_row_number"),
        )
        plan_row_id = stable_id("planrow", plan_compile_id, *source_key)
        plan_row_ids[source_key] = plan_row_id
        upsert(conn, "plan_rows", {
            "id": plan_row_id,
            "plan_compile_id": plan_compile_id,
            "source_workbook": source_key[0],
            "source_sheet": source_key[1],
            "source_row_number": source_key[2],
            "source_row_json": dumps(step.get("source_row", {})),
            "course": step.get("course") or "",
            "unit": step.get("unit") or "",
            "phase": step.get("phase") or "",
            "day_label": step.get("day_label") or "",
            "actual_date": step.get("actual_date"),
            "topic": step.get("title") or "",
            "runner_hint": step.get("runner") or "",
            "resource_hints_json": dumps(step.get("resource_hints", {})),
        })

        global_range = step.get("global_day_range") or [None, None]
        step_id = stable_id("planstep", plan_compile_id, step.get("course"), source_key[1], source_key[2])
        plan_step_ids[(step.get("course"), source_key[1], source_key[2])] = step_id
        upsert(conn, "plan_steps", {
            "id": step_id,
            "plan_compile_id": plan_compile_id,
            "phase_pool_id": phase_ids.get((step.get("course"), step.get("phase"))),
            "plan_row_id": plan_row_id,
            "course": step.get("course") or "",
            "phase": step.get("phase") or "",
            "unit": step.get("unit") or "",
            "day_label": step.get("day_label") or "",
            "global_day_start": global_range[0],
            "global_day_end": global_range[1],
            "actual_date": step.get("actual_date"),
            "title": step.get("title") or "",
            "runner": step.get("runner") or "",
            "duration_days": int(step.get("duration_days") or 1),
        })

    material_ids = {}
    for task in snapshot.get("task_instances", []):
        lineage = task.get("source_lineage", {})
        source_key = (
            task.get("course"),
            lineage.get("sheet"),
            lineage.get("row_number"),
        )
        plan_step_id = plan_step_ids.get(source_key)
        task_id = stable_id("task", plan_compile_id, task.get("id"))
        upsert(conn, "task_instances", {
            "id": task_id,
            "plan_compile_id": plan_compile_id,
            "plan_step_id": plan_step_id,
            "scheduled_date": task.get("scheduled_date") or "",
            "course": task.get("course") or "",
            "unit": task.get("unit") or "",
            "phase": task.get("phase") or "",
            "title": task.get("title") or "",
            "runner": task.get("runner") or "",
            "kind": task.get("kind") or "",
            "status": "planned",
            "target_minutes": int(task.get("target_minutes") or 0),
            "observable_goal": task.get("observable_goal") or "",
            "completion_criteria_json": dumps(task.get("completion_criteria", [])),
            "source_lineage_json": dumps(lineage),
            "browser_workflow_json": dumps(task.get("browser_workflow", [])),
        })
        for order, material in enumerate(task.get("materials", []), start=1):
            page_range = material.get("page_range") or [None, None]
            material_key = (
                material.get("label"),
                material.get("target_type"),
                material.get("local_target"),
                material.get("external_url"),
                page_range[0],
                page_range[1],
            )
            material_id = material_ids.get(material_key)
            if not material_id:
                material_id = stable_id("material", plan_compile_id, *material_key)
                material_ids[material_key] = material_id
                upsert(conn, "material_records", {
                    "id": material_id,
                    "plan_compile_id": plan_compile_id,
                    "label": material.get("label") or "",
                    "target_type": material.get("target_type") or "unknown",
                    "local_target": material.get("local_target") or "",
                    "external_url": material.get("external_url") or "",
                    "source_local_path": material.get("source_local_path") or "",
                    "storage_key": "",
                    "browser_url": material.get("external_url") or "",
                    "page_start": page_range[0],
                    "page_end": page_range[1],
                    "match_method": material.get("match") or "",
                    "index_json": dumps(material.get("index", {})),
                    "upload_required": 1 if material.get("upload_required") else 0,
                    "browser_openable": 1 if material.get("browser_openable") else 0,
                    "missing": 1 if material.get("missing") else 0,
                })
            upsert(conn, "task_materials", {
                "id": stable_id("taskmaterial", task_id, material_id, order),
                "task_instance_id": task_id,
                "material_record_id": material_id,
                "role": material_role(material),
                "open_order": order,
            })

    conn.commit()
    return plan_compile_id


def summary(conn, plan_compile_id):
    tables = [
        "phase_pools",
        "plan_rows",
        "plan_steps",
        "material_records",
        "task_instances",
        "task_materials",
    ]
    out = {"plan_compile_id": plan_compile_id}
    for table in tables:
        if table == "task_materials":
            out[table] = one(
                conn,
                """
                SELECT COUNT(*)
                FROM task_materials tm
                JOIN task_instances ti ON ti.id = tm.task_instance_id
                WHERE ti.plan_compile_id = ?
                """,
                (plan_compile_id,),
            )
        else:
            out[table] = one(conn, f"SELECT COUNT(*) FROM {table} WHERE plan_compile_id = ?", (plan_compile_id,))
    out["upload_required_materials"] = one(
        conn,
        "SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND upload_required = 1",
        (plan_compile_id,),
    )
    out["external_url_materials"] = one(
        conn,
        "SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND target_type = 'url'",
        (plan_compile_id,),
    )
    out["missing_materials"] = one(
        conn,
        "SELECT COUNT(*) FROM material_records WHERE plan_compile_id = ? AND missing = 1",
        (plan_compile_id,),
    )
    return out


def main():
    parser = argparse.ArgumentParser(description="Import AP Learning OS compile snapshot into SQLite.")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--db", default=str(BASE / "data" / "online_platform" / "aplos_dev.sqlite3"))
    parser.add_argument("--organization-id", default="org_local_ap_learning_os")
    parser.add_argument("--organization-name", default="Local AP Learning OS")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    conn = connect(args.db)
    if args.summary_only:
        plan_compile_id = stable_id("compile", args.organization_id, snapshot["compile_id"])
    else:
        plan_compile_id = import_snapshot(conn, snapshot, args.organization_id, args.organization_name)
    print(json.dumps(summary(conn, plan_compile_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
