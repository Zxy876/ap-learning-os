# AP Learning OS Online API Draft

This is a contract draft for the online platform. It is intentionally framework
neutral, but it maps cleanly to a Next.js API plus Postgres plus object storage.

## Core Data Model

### Identity

```text
User
- id
- email
- display_name
- created_at

Organization
- id
- name
- created_at

RoleAssignment
- id
- user_id
- organization_id
- role: author | executor | reviewer | admin
- created_at
```

### Resource Library

```text
Resource
- id
- organization_id
- title
- resource_type: pdf | spreadsheet | image | link | archive
- canonical_subject: AP_Calculus_BC | AP_CSA | other
- storage_key
- source_url
- created_by
- created_at

ResourceVersion
- id
- resource_id
- version_no
- file_sha256
- page_count
- metadata_json
- created_at

DocumentPageIndex
- id
- resource_version_id
- page_number
- text_excerpt
- heading_json
- ocr_status
- embedding_id
- created_at

MaterialSlice
- id
- resource_version_id
- title
- page_start
- page_end
- storage_key
- match_confidence
- match_reason_json
- created_at
```

### Spreadsheet Library

```text
PlanSource
- id
- organization_id
- title
- source_resource_id
- created_by
- created_at

PlanSheet
- id
- plan_source_id
- sheet_name
- header_row
- row_count
- detected_schema_json

PlanRow
- id
- plan_sheet_id
- row_index
- source_row_json
- normalized_json
- course
- unit
- phase
- day_label
- planned_date
- topic
- runner_hint
- resource_hints_json
```

### Compiler

```text
PlanCompile
- id
- plan_source_id
- organization_id
- status: draft | compiling | compiled | failed | published | superseded
- calendar_start_date
- learner_anchor_json
- warnings_json
- created_by
- created_at
- published_at

PhasePool
- id
- plan_compile_id
- course
- phase
- unit
- rule_json

PlanStep
- id
- plan_compile_id
- phase_pool_id
- plan_row_id
- global_day_start
- global_day_end
- actual_date
- title
- runner: concept_runner | practice_runner | review_runner | exam_runner
- target_minutes
- completion_criteria_json

PlanStepMaterial
- id
- plan_step_id
- material_slice_id
- external_url
- role: primary | supplemental | answer_key | checklist | external_practice
- open_order
```

### Runtime

```text
Enrollment
- id
- plan_compile_id
- executor_user_id
- reviewer_user_id
- status: active | paused | completed | archived
- start_date
- delay_days_json
- created_at

TaskInstance
- id
- enrollment_id
- plan_step_id
- scheduled_date
- status
- target_minutes
- created_at
- archived_at

TaskSession
- id
- task_instance_id
- started_at
- ended_at
- elapsed_seconds
- status

TaskSessionEvent
- id
- task_session_id
- kind
- payload_json
- created_at
```

### Evidence and Review

```text
EvidenceArtifact
- id
- task_instance_id
- task_session_id
- uploaded_by
- artifact_type: screenshot | file | note | activity_log | link
- storage_key
- text_note
- metadata_json
- created_at

ReviewRequest
- id
- task_instance_id
- requested_by
- reviewer_user_id
- status: open | decided | cancelled
- created_at

ReviewDecision
- id
- review_request_id
- reviewer_user_id
- final_state: completed | partial | not_completed | failed | blocked
- failure_type
- message
- created_at

ScheduleDelayEvent
- id
- enrollment_id
- task_instance_id
- course
- effective_date
- days
- scope: course_local | plan_global | task_only
- reason
- created_at

SpreadsheetWriteback
- id
- review_decision_id
- plan_row_id
- writeback_target
- target_sheet
- target_row
- target_column
- status: pending | written | failed
- payload_json
- created_at
```

## API Routes

### Author APIs

Upload source spreadsheet:

```http
POST /api/author/plan-sources
```

Create compile sandbox:

```http
POST /api/author/plan-sources/{planSourceId}/compiles
```

Inspect compile:

```http
GET /api/author/compiles/{compileId}
GET /api/author/compiles/{compileId}/steps
GET /api/author/compiles/{compileId}/warnings
GET /api/author/compiles/{compileId}/materials
```

Publish compile:

```http
POST /api/author/compiles/{compileId}/publish
```

### Resource APIs

Upload resource:

```http
POST /api/resources
```

Index resource:

```http
POST /api/resources/{resourceId}/index
```

Create or refresh slice:

```http
POST /api/resources/{resourceId}/slices
```

Read slice in browser:

```http
GET /api/material-slices/{sliceId}/file
```

### Executor APIs

Get today's tasks:

```http
GET /api/workspace/today?date=YYYY-MM-DD
```

Start session:

```http
POST /api/tasks/{taskInstanceId}/sessions
```

Append event:

```http
POST /api/task-sessions/{sessionId}/events
```

Upload evidence:

```http
POST /api/tasks/{taskInstanceId}/evidence
```

Submit for review:

```http
POST /api/tasks/{taskInstanceId}/review-requests
```

### Reviewer APIs

List review queue:

```http
GET /api/review/queue
```

Inspect review packet:

```http
GET /api/review/requests/{reviewRequestId}
```

Decide:

```http
POST /api/review/requests/{reviewRequestId}/decision
```

Decision payload:

```json
{
  "final_state": "not_completed",
  "failure_type": "insufficient_evidence",
  "message": "Evidence does not show work on the assigned task.",
  "delay_scope": "course_local",
  "delay_days": 1
}
```

### Spreadsheet Writeback APIs

Preview writeback:

```http
GET /api/writeback/{reviewDecisionId}/preview
```

Run writeback:

```http
POST /api/writeback/{reviewDecisionId}
```

## Failure Type Taxonomy

```text
insufficient_evidence
wrong_resource
insufficient_time
incomplete_work
low_quality_work
misunderstood_task
access_blocked
technical_blocked
external_blocked
other
```

## Event Kinds

Task session event kinds:

```text
session_started
resource_opened
timer_started
timer_paused
timer_completed
evidence_uploaded
review_requested
review_decided
schedule_delayed
task_archived
```

These events should be append-only. Current state can be stored on the task for
fast reads, but the event log is the audit source.

