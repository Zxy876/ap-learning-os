# AP Learning OS

This is a local macOS workflow engine for AP study sessions. It is intentionally not a dashboard.

Core rule: the system never marks a task completed by itself. Detectors can only produce `Candidate Complete` evidence. uone makes the final status decision.

## Layers

1. Planner Layer
   - Reads Harrison BC Plan and Harrison CSA Plan.
   - Uses current date and saved state.
   - Emits observable tasks into `blackboard/today.md`.

2. Workflow Layer
   - Opens URLs/files/apps.
   - Starts a session timer.
   - Records expected completion criteria.

3. Detection Layer
   - Samples frontmost app/window titles.
   - Takes start/mid/end screenshots.
   - Records elapsed focus time.
   - Leaves OCR/Khan mastery/browser extension detection as pluggable detectors.

4. Human Validation Layer
   - Builds a review packet for uone.
   - uone chooses `completed`, `partially_completed`, `not_completed`, `failed`, or `blocked`.

5. State Transition Layer
   - Applies deterministic task transitions.
   - Updates adaptive time after uone review.

## Online Platform Direction

The local macOS app is the executor-facing prototype. The online version is
specified as a multi-role plan compiler and browser workflow runtime:

- A / Rule Author: uploads spreadsheets/resources, runs a sandbox compiler, and
  publishes a compiled plan version.
- B / Plan Executor: uses browser-only task workflows, opens generated material
  slices, uploads evidence, and requests review.
- C / Plan Supervisor: reviews evidence, makes the final task decision, triggers
  schedule changes, and writes results back to the plan record.

Design docs:

- `docs/online_platform_architecture.md`
- `docs/online_platform_api.md`
- `docs/online_platform_infra_checklist.md`
- `docs/compile_snapshot_contract.md`
- `docs/local_online_api_smoke.md`
- `docs/material_publication_contract.md`
- `docs/service_capabilities.md`

First online data-layer harness:

- `online_platform/schema.sql`
- `online_platform/import_compile_snapshot.py`
- `online_platform/api_server.py`
- `online_platform/publish_materials.py`
- `online_platform/process_writebacks.py`
- `online_platform/google_sheets_writeback.py`
- `online_platform/cloud_config_probe.py`
- `online_platform/schema_postgres.sql`
- `online_platform/static/`

## State Machine

Allowed task states:

- `Planned`
- `Running`
- `Candidate Complete`
- `Needs Review`
- `Completed`
- `Partially Completed`
- `Failed`
- `Blocked`

Transitions:

- `Planned -> Running`: workflow starts.
- `Running -> Candidate Complete`: signals meet threshold.
- `Running -> Needs Review`: timer ends but signals are weak.
- `Candidate Complete -> Needs Review`: review packet generated.
- `Needs Review -> Completed`: uone confirms completion.
- `Needs Review -> Partially Completed`: uone confirms partial completion.
- `Needs Review -> Failed`: uone rejects evidence.
- `Needs Review -> Blocked`: uone marks external blocker.
- `Partially Completed -> Planned`: planner regenerates continuation task.
- `Failed -> Planned`: planner regenerates with more time.
- `Blocked -> Planned`: only after blocker is cleared manually.

## Detection Methods

Khan Academy:

- Browser DOM / extension: Automatic, high reliability if authenticated page structure is stable, high implementation complexity.
- Browser automation screenshot + OCR: Semi-automatic, medium reliability, medium complexity.
- Manual mastery entry after session: Manual, high reliability, low complexity.
- Current default: open Khan URL, verify browser/window time, screenshot evidence, uone review.

CSA practice:

- Coding editor window open: Automatic, medium reliability, low complexity.
- File modification time: Automatic, high reliability for local code files, medium complexity.
- Git commit: Semi-automatic, high reliability, medium complexity.
- Question count completed: Manual unless practice platform exposes data.
- Current default: resource opened + editor/window evidence + screenshots + uone review.

PDF / FRQ practice:

- PDF app/window open: Automatic, medium reliability, low complexity.
- Screenshot OCR for question/page labels: Semi-automatic, medium reliability, medium complexity.
- Written answer file or GoodNotes page changed: Semi-automatic, medium reliability.
- Current default: resource opened + timed evidence + screenshots.

GoodNotes:

- GoodNotes window open: Automatic, medium reliability, low complexity.
- iCloud/GoodNotes file modification time: Semi-automatic, low to medium reliability because app sync internals vary.
- OCR/page image diff: Semi-automatic, medium reliability, high complexity.
- User confirmation: Manual, high reliability.
- Current default: GoodNotes launch + screenshot packet + uone review.

Screen activity:

- Frontmost app/window sampling: Automatic, medium reliability.
- Full screenshot capture: Automatic evidence, not final truth.
- OCR: Semi-automatic, optional.

## Daily Use

Use one user-facing entrypoint: the interactive blackboard.

```text
Double click /Users/zxydediannao/Desktop/AP Learning OS.app
choose: 打开黑板
```

The desktop app intentionally exposes only:

- `打开黑板`: starts/keeps the always-on local blackboard service and opens it.
- `打开证据包目录`: opens saved session screenshots and review packets.

All normal workflow actions happen inside the blackboard:

- regenerate the selected date's tasks
- open Khan, task PDF, and unit page links
- start a workflow session
- mark a task `Completed`, `Partially Completed`, or `Blocked`
- play macOS system sounds when actions are applied

The blackboard runs in the background through:

```text
~/Library/LaunchAgents/com.aplearningos.blackboard.plist
```

Blackboard URL:

```text
http://127.0.0.1:8765
```

## Maintainer Commands

These commands are for debugging or repair, not daily use. The blackboard is the preferred control surface.

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Generate tasks manually:

```bash
python3 learning_os.py today --date 2026-06-22
```

Reset a test or accidental task start:

```bash
python3 learning_os.py reset-task --task TASK_ID
```

Check task resource mappings:

```bash
python3 learning_os.py materials --date 2026-06-22 --core-only
```

Audit future workflow material mappings without changing saved task state:

```bash
python3 learning_os.py audit-materials --start 2026-06-22 --days 120
```

The audit treats obviously wrong auto-open candidates, such as practice exams, answer keys, scoring guides, and FRQ packets on concept-learning tasks, as failures. If no reliable `Print Packet` can be found, the workflow falls back to safer local resources such as the course workbook, Unit page, or textbook excerpt instead of opening a dubious match.

Check whether the always-on service is running:

```bash
launchctl print gui/$(id -u)/com.aplearningos.blackboard
```

Restart the blackboard service:

```bash
launchctl kickstart -k gui/$(id -u)/com.aplearningos.blackboard
```

Stop it:

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.aplearningos.blackboard.plist"
```

Export a web-importable compile snapshot:

```bash
python3 learning_os.py compile-export --start 2026-06-22 --days 30
```

The export includes:

- normalized plan steps with source workbook/sheet/row lineage
- phase pools
- generated task instances for the requested date window
- browser workflow entries
- material bindings with local file/upload requirements

Generated compile exports are local runtime artifacts under `data/exports/` and
are intentionally not committed because they include local file paths and may
reference private or copyrighted materials.

## Local Resource Redirects

The original BC plan contains Windows paths. The workflow redirects missing Windows paths to local macOS resources already found in this workspace:

- BC GoodNotes workbook and unit pages under `AP_Interactive_GoodNotes_System/AP_Calculus_BC/`
- CSA GoodNotes workbook and unit pages under `AP_Interactive_GoodNotes_System/AP_CSA/`
- CSA unit practice PDFs under `AP打印资料大包/04_AP_CSA_练习/`
- BC/CSA summary PDFs under `AP打印资料大包/01_知识点总结/`

Canonical source files:

- Stewart Calculus textbook: `/Users/zxydediannao/Library/Mobile Documents/com~apple~CloudDocs/javabook/James Stewart - Calculus_ Early transcendentals 8th edition(2016, Brooks Cole).pdf`
- Java Illuminated textbook: `/Users/zxydediannao/Library/Mobile Documents/com~apple~CloudDocs/javabook/Java Illuminated_ An Active Learning Approach, 6th Edition -- Julie A_ Anderson, Hervé J_ Franceschi -- 6th, 2023 -- Jones & Bartlett Learning, LLC -- 9781284250480 -- a38c2729310f379bc8c2795860.pdf`
- AP master packet: `/Users/zxydediannao/Library/Mobile Documents/iCloud~QReader~MarginStudy~easy/Documents/00_AP全部资料_带完成日期_学习顺序 2.pdf`

When today's tasks are generated, the engine creates task-specific PDF excerpts in:

```text
/Users/zxydediannao/Downloads/ AP Master Library/AP_Learning_OS/task_materials/
```

Examples:

- BC `Stewart §2.1-2.3` becomes a small PDF excerpt from Stewart pages 110-135.
- CSA concept days use the dated print packet as the primary launch material because it follows AP Unit topic language more closely.
- Java Illuminated excerpts are generated as supporting references when a reliable topic window can be found, but they are not opened automatically.
- The dated print packet is searched by course, Unit scope, and task topic every time `today` runs, then copied into a small task-specific `Print Packet` PDF.

Workflow launch opens only task-specific jump resources by default:

- `task_excerpt_stewart`
- `supplemental_print_packet_bc`
- `supplemental_print_packet_csa`
- `question_file`
- `local_practice_pdf`
- `local_unit_page`

Canonical full textbooks and the AP master packet remain visible in the blackboard as source references, but they are not opened automatically unless a task-specific excerpt cannot be generated or a future page map points into them.

The dated print packet is also integrated as supplemental material:

```text
/Users/zxydediannao/Downloads/ AP Master Library/AP打印资料大包_带日期/00_按日期学习顺序打印版/00_AP全部资料_带完成日期_学习顺序.pdf
```

Its old schedule file is kept only as reference. The engine uses the packet as a source library: each daily task first scopes the search to the matching course and Unit when possible, then extracts the pages that match the task topic. The result is exposed as a `Print Packet` link on the blackboard and opened during `Start Workflow`.

When a session starts, the engine launches:

- Khan course URL
- GoodNotes app
- task-specific resources that exist locally
- screenshots/window sampling for evidence

Reset a test or accidental task start:

```bash
python3 learning_os.py reset-task --task TASK_ID
```

Check task resource mappings:

```bash
python3 learning_os.py materials --date 2026-06-22 --core-only
```

## BC Current Progress Anchor

BC no longer assumes `2026-06-22` is Unit 1 Day 1. Based on the Khan screenshots, the current anchor is:

```text
2026-06-22 -> BC Unit 2 Day 5-6
```

Observed start:

- Unit 1 mastery: 60%
- Unit 2 mastery: 50%
- Active skill: Differentiate quotients

This is configured in `config.json`:

```json
"bc_anchor": {
  "date": "2026-06-22",
  "unit": "Unit 2",
  "day": "Day 5-6"
}
```

From that anchor, future dates advance through the BC plan by cumulative task durations.

CSA also starts on `2026-06-22`. The CSA spreadsheet's first row is dated `2026-06-21`, so the planner applies a one-day offset:

```json
"csa_plan_start_date": "2026-06-21",
"csa_actual_start_date": "2026-06-22"
```

This makes `2026-06-22` generate CSA Day 1, then shifts later CSA rows forward by the same offset.

BC Khan launches now use unit-specific URLs when available:

- Unit 1: Limits and continuity
- Unit 2: Differentiation: definition and basic derivative rules
- Unit 3: Differentiation: composite, implicit, and inverse functions
- Unit 4: Contextual applications of differentiation
- Unit 6: Integration and accumulation
- Unit 7: Differential equations
- Unit 8: Applications of integration
- Unit 9: Parametric, polar, and vector-valued functions
- Unit 10: Infinite sequences and series

Launcher source:

```text
/Users/zxydediannao/Downloads/ AP Master Library/AP_Learning_OS/launchers/AP_Learning_OS_Launcher.applescript
```

Recompile after editing the source:

```bash
osacompile -o "$HOME/Desktop/AP Learning OS.app" "launchers/AP_Learning_OS_Launcher.applescript"
```
