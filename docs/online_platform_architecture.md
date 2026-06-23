# AP Learning OS Online Platform Architecture

This document defines the online version of AP Learning OS. The online
product must not be a dashboard-first rewrite of the local macOS app. It is a
multi-role plan compiler and workflow runtime.

Core formula:

```text
source plan + source resources -> compiled plan -> daily task instances
-> browser workflow session -> evidence package -> reviewer decision
-> state transition + schedule adjustment + spreadsheet writeback
```

## Roles

### A: Rule Author

The rule author does not need to create the study plan inside AP Learning OS.
They can upload an existing spreadsheet and resource set.

Primary route:

```text
/author
```

Responsibilities:

- upload plan spreadsheets
- upload or link source resources
- run the sandbox compiler
- inspect generated daily tasks
- inspect generated material slices
- inspect missing or low-confidence resource matches
- approve and publish a compiled plan version

The author sandbox is a compiler preview. It must show what the system will do
before the plan is assigned to students.

### B: Plan Executor

The executor uses browser-only workflows. The online version must not launch
local macOS apps, local file paths, WPS, GoodNotes, or Finder.

Primary route:

```text
/workspace
```

Responsibilities:

- open today's assigned task instances
- read task-specific PDF slices in the browser
- open external web links such as Khan Academy or Canvas
- run a task timer
- upload screenshots, files, notes, or other evidence
- submit a task for review

The executor cannot directly create final completion. They can only submit
evidence and request review.

### C: Plan Supervisor

The supervisor reviews evidence and owns the final status decision.

Primary route:

```text
/review
```

Responsibilities:

- see the evidence queue
- inspect task requirements and source spreadsheet row mapping
- inspect screenshots/files/notes/activity logs
- choose final state
- choose failure type when relevant
- attach a message
- trigger state transition, archival, delay, and spreadsheet writeback

## Platform Layers

### 1. Document Library

Stores source PDFs, generated excerpts, screenshots, uploaded answer files, and
other artifacts.

Every derived file must preserve lineage:

```text
derived artifact -> source resource -> source version -> page range
```

### 2. Spreadsheet Library

Stores uploaded source spreadsheets and derived normalized plan rows.

Every compiled task must preserve lineage:

```text
task instance -> compiled plan step -> source sheet -> source row -> source columns
```

### 3. Plan Compiler

The plan compiler turns a source spreadsheet plus resources into a compiled
plan snapshot.

Inputs:

- source spreadsheet
- resource library subset
- calendar start date
- learner starting state
- optional resource matching rules

Outputs:

- normalized plan rows
- phase pools
- runner rules
- task templates
- material slice requests
- material slices
- warnings
- missing resource list
- publishable plan version

The compiler should be deterministic for the same inputs. If an author reruns
the compiler after adding resources, the new result is a new compile version.

### 4. Browser Workflow Runtime

The runtime creates per-learner task instances from the published plan.

Runtime behavior:

- create or resume today's task instances
- open PDF slices with a browser PDF reader
- open external task links in new browser tabs
- record task session events
- collect evidence artifacts
- submit for review

Browser limitations:

- the web app cannot reliably capture arbitrary OS-level screenshots
- cross-site activity cannot be trusted as automatic completion
- screenshots should be user-uploaded or captured only inside the app's own
  reader surface

### 5. Evidence Review Engine

The review engine converts evidence into a human final decision.

Allowed final decisions:

```text
completed
partial
not_completed
failed
blocked
```

The system can recommend a status, but it must not finalize completion
automatically.

### 6. State Transition Engine

The state engine applies deterministic transitions after supervisor review.

Task states:

```text
planned
running
candidate_complete
needs_review
completed
partial
failed
blocked
archived
```

Important transitions:

```text
planned -> running
running -> candidate_complete
running -> needs_review
candidate_complete -> needs_review
needs_review -> completed
needs_review -> partial
needs_review -> failed
needs_review -> blocked
partial -> planned continuation
failed -> planned continuation
blocked -> planned continuation after unblock
completed -> archived
```

### 7. Adaptive Schedule Engine

If a reviewed task is not completed, the learner's schedule should shift
forward from the next day.

Default policy:

```text
completed: no delay, clear delay for this task if present
partial: add one course-local delay day
not_completed: add one course-local delay day
failed: add one course-local delay day
blocked: add one course-local delay day unless marked external-only
```

Delay scope should be configurable:

```text
course-local: only this course shifts
plan-global: all courses in this enrollment shift
task-only: only this task regenerates tomorrow
```

The current local app uses course-local delay. The online platform should keep
that as the default.

## Maieutic-1 Reference Pattern

The local `maieutic-1` project has useful patterns:

- `Exercise` maps to a published task template or learning unit.
- `Session` maps to one executor's task attempt.
- `SessionEvent` maps to workflow/evidence/review event history.
- instructor live routes map to the supervisor review queue.
- Server-Sent Events can power live review updates.

AP Learning OS adds two first-class layers that `maieutic-1` does not have:

- resource library and page-slice lineage
- spreadsheet compiler and source-row writeback

Do not directly copy `maieutic-1`. Reuse the event/session pattern and add the
plan compiler and resource library around it.

## Publish Contract

A plan is assignable only after the author publishes a compile version.

Publish conditions:

- required spreadsheet rows are parsed
- all required task dates are generated
- critical resources are matched or explicitly accepted as external links
- missing resources are visible to the author
- low-confidence page slices are visible to the author
- source row lineage is present for every generated task

Published plans should be immutable. Corrections create a new version.

