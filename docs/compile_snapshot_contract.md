# Compile Snapshot Contract

`compile-export` converts the local AP Learning OS plan compiler into a JSON
snapshot that the online platform can import.

Command:

```bash
python3 learning_os.py compile-export --start 2026-06-22 --days 30
```

Default output:

```text
data/exports/compile_snapshot_YYYY-MM-DD_Nd.json
```

The file is ignored by git because it includes local paths and material
lineage.

## Top-Level Shape

```json
{
  "schema_version": "aplos.compile_snapshot.v1",
  "compile_id": "deterministic id",
  "generated_at": "timestamp",
  "start_date": "2026-06-22",
  "days": 30,
  "courses": ["AP_Calculus_BC", "AP_CSA"],
  "source_plans": {},
  "rules": {},
  "phase_pools": [],
  "plan_steps": [],
  "task_instances": [],
  "import_notes": []
}
```

## Import Mapping

### `source_plans`

Maps to:

```text
PlanSource
```

The local path must not be used directly online. It is an import hint. The
uploaded spreadsheet file becomes the real online `PlanSource`.

### `phase_pools`

Maps to:

```text
PhasePool
```

Use these records to show the author which phases and units were detected.

### `plan_steps`

Maps to:

```text
PlanStep
PlanRow
```

Important fields:

- `source_workbook`
- `source_sheet`
- `source_row_number`
- `phase`
- `unit`
- `day_label`
- `global_day_range`
- `actual_date`
- `runner`
- `source_row`

`source_row_number` is the anchor for spreadsheet writeback.

### `task_instances`

Maps to:

```text
TaskInstance
PlanStepMaterial
MaterialSlice
```

Important fields:

- `scheduled_date`
- `title`
- `runner`
- `target_minutes`
- `source_lineage`
- `browser_workflow`
- `materials`

### `materials`

Each material has:

```text
target_type: file | url | missing | unknown
local_target: local path that must be uploaded
external_url: browser-openable URL
page_range: excerpt pages when available
source_local_path: original source PDF when available
upload_required: true when online import must upload the file
```

The online importer should:

1. upload every `upload_required` file to object storage
2. create a `Resource` or `MaterialSlice`
3. replace local paths with storage keys or signed URLs
4. preserve `source_lineage` for review/writeback

## Browser Runtime Rule

`browser_workflow` can contain local-app-only entries from the macOS prototype.
The online runtime must ignore them.

Example:

```json
{
  "type": "app",
  "target": "GoodNotes",
  "local_app_only": true
}
```

Online tasks should open only:

- uploaded material slices
- uploaded source resources
- external URLs

## Stability Rules

- `schema_version` must change when incompatible fields change.
- `compile_id` is deterministic except for `generated_at`.
- published online plans should store the imported compile snapshot.
- never use local paths as online access URLs.

