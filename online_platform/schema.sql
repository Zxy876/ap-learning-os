PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_sources (
  id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL REFERENCES organizations(id),
  title TEXT NOT NULL,
  local_path_hint TEXT NOT NULL DEFAULT '',
  course TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_compiles (
  id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL REFERENCES organizations(id),
  compile_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  start_date TEXT NOT NULL,
  days INTEGER NOT NULL,
  courses_json TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  source_snapshot_json TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS phase_pools (
  id TEXT PRIMARY KEY,
  plan_compile_id TEXT NOT NULL REFERENCES plan_compiles(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  phase TEXT NOT NULL,
  phase_name TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  runners_json TEXT NOT NULL,
  resources_json TEXT NOT NULL,
  UNIQUE(plan_compile_id, course, phase)
);

CREATE TABLE IF NOT EXISTS plan_rows (
  id TEXT PRIMARY KEY,
  plan_compile_id TEXT NOT NULL REFERENCES plan_compiles(id) ON DELETE CASCADE,
  source_workbook TEXT NOT NULL DEFAULT '',
  source_sheet TEXT NOT NULL DEFAULT '',
  source_row_number INTEGER,
  source_row_json TEXT NOT NULL,
  course TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT '',
  day_label TEXT NOT NULL DEFAULT '',
  actual_date TEXT,
  topic TEXT NOT NULL DEFAULT '',
  runner_hint TEXT NOT NULL DEFAULT '',
  resource_hints_json TEXT NOT NULL,
  UNIQUE(plan_compile_id, source_workbook, source_sheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS plan_steps (
  id TEXT PRIMARY KEY,
  plan_compile_id TEXT NOT NULL REFERENCES plan_compiles(id) ON DELETE CASCADE,
  phase_pool_id TEXT REFERENCES phase_pools(id),
  plan_row_id TEXT REFERENCES plan_rows(id),
  course TEXT NOT NULL,
  phase TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  day_label TEXT NOT NULL DEFAULT '',
  global_day_start INTEGER,
  global_day_end INTEGER,
  actual_date TEXT,
  title TEXT NOT NULL,
  runner TEXT NOT NULL,
  duration_days INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS material_records (
  id TEXT PRIMARY KEY,
  plan_compile_id TEXT NOT NULL REFERENCES plan_compiles(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  target_type TEXT NOT NULL,
  local_target TEXT NOT NULL DEFAULT '',
  external_url TEXT NOT NULL DEFAULT '',
  source_local_path TEXT NOT NULL DEFAULT '',
  page_start INTEGER,
  page_end INTEGER,
  match_method TEXT NOT NULL DEFAULT '',
  index_json TEXT NOT NULL,
  upload_required INTEGER NOT NULL DEFAULT 0,
  browser_openable INTEGER NOT NULL DEFAULT 0,
  missing INTEGER NOT NULL DEFAULT 0,
  UNIQUE(plan_compile_id, label, local_target, external_url, page_start, page_end)
);

CREATE TABLE IF NOT EXISTS task_instances (
  id TEXT PRIMARY KEY,
  plan_compile_id TEXT NOT NULL REFERENCES plan_compiles(id) ON DELETE CASCADE,
  plan_step_id TEXT REFERENCES plan_steps(id),
  scheduled_date TEXT NOT NULL,
  course TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  runner TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned',
  target_minutes INTEGER NOT NULL,
  observable_goal TEXT NOT NULL DEFAULT '',
  completion_criteria_json TEXT NOT NULL,
  source_lineage_json TEXT NOT NULL,
  browser_workflow_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_materials (
  id TEXT PRIMARY KEY,
  task_instance_id TEXT NOT NULL REFERENCES task_instances(id) ON DELETE CASCADE,
  material_record_id TEXT NOT NULL REFERENCES material_records(id),
  role TEXT NOT NULL DEFAULT 'supplemental',
  open_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(task_instance_id, material_record_id, role, open_order)
);

CREATE TABLE IF NOT EXISTS evidence_artifacts (
  id TEXT PRIMARY KEY,
  task_instance_id TEXT NOT NULL REFERENCES task_instances(id) ON DELETE CASCADE,
  artifact_type TEXT NOT NULL,
  storage_key TEXT NOT NULL DEFAULT '',
  text_note TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_requests (
  id TEXT PRIMARY KEY,
  task_instance_id TEXT NOT NULL REFERENCES task_instances(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_decisions (
  id TEXT PRIMARY KEY,
  review_request_id TEXT NOT NULL REFERENCES review_requests(id) ON DELETE CASCADE,
  final_state TEXT NOT NULL,
  failure_type TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schedule_delay_events (
  id TEXT PRIMARY KEY,
  task_instance_id TEXT NOT NULL REFERENCES task_instances(id) ON DELETE CASCADE,
  course TEXT NOT NULL,
  effective_date TEXT NOT NULL,
  days INTEGER NOT NULL DEFAULT 1,
  scope TEXT NOT NULL DEFAULT 'course_local',
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spreadsheet_writebacks (
  id TEXT PRIMARY KEY,
  review_decision_id TEXT NOT NULL REFERENCES review_decisions(id) ON DELETE CASCADE,
  plan_row_id TEXT REFERENCES plan_rows(id),
  target_sheet TEXT NOT NULL DEFAULT '',
  target_row INTEGER,
  target_column TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_instances_date ON task_instances(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_task_instances_status ON task_instances(status);
CREATE INDEX IF NOT EXISTS idx_plan_rows_source ON plan_rows(source_sheet, source_row_number);
CREATE INDEX IF NOT EXISTS idx_material_upload_required ON material_records(upload_required);
