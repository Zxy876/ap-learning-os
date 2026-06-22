# AP Learning OS Progression Model

This document defines how the OS should move from a date to a concrete task before any file or page is opened.

Core formula:

```text
date -> plan_step -> runner -> material_slice -> workflow_session
```

File names are not the source of truth for scheduling. The two Excel plans are the source of truth for progression. File names and page ranges are resolved only after a plan step has been selected.

## Source Workbooks

- BC: `AP_Calculus_BC_学习计划.xlsx`
  - schedule sheet: `每日计划`
  - phase overview: `总览`
  - resource truth source: `资源索引`
- CSA: `AP_CSA_学习计划.xlsx`
  - schedule sheet: `每日刷题计划`
  - phase overview: `总览`
  - resource truth source: `资源索引`

## Terms

- `phase`: high-level plan segment, usually `阶段 + Unit`.
- `plan_step`: one row in the daily plan.
- `runner`: execution mode for the step.
- `material_slice`: the exact local file/page excerpt opened for the step.
- `anchor`: the real-world current position used to align a plan without explicit dates.

## BC Progression Rule

BC daily rows do not have calendar dates. They have `Day n` or `Day n-m` ranges.

The OS converts each row into a canonical global day range:

```text
duration_days = end_day - start_day + 1
global_start = previous_global_end + 1
global_end = global_start + duration_days - 1
```

Current BC start is not Unit 1 Day 1. It is anchored from actual Khan progress:

```text
2026-06-22 -> BC Unit 2 Day 5-6
```

Evidence from 2026-06-22 screenshots:

```text
Khan Unit 1 mastery: 60%
Khan Unit 2 mastery: 50%
Active Khan skill: Differentiate quotients
```

Runtime formula:

```text
anchor_global_day = global_start(Unit 2, Day 5-6)
current_global_day = anchor_global_day + days_between(current_date, 2026-06-22)
selected_step = first step where global_start <= current_global_day <= global_end
```

Example:

```text
2026-06-22 -> Unit 2 Day 5-6 -> concept_runner
2026-06-23 -> Unit 2 Day 5-6 -> concept_runner
2026-06-24 -> Unit 2 Day 7-8 -> concept_runner
2026-06-26 -> Unit 2 Day 9-10 -> concept_runner
```

## CSA Progression Rule

CSA rows have explicit dates in `每日刷题计划`.

The spreadsheet starts at `2026-06-21`, but actual learning starts at `2026-06-22`, so the OS applies a uniform offset:

```text
offset = actual_start_date - plan_start_date
actual_date = row_plan_date + offset
selected_step = first row where actual_date == current_date
```

Example:

```text
06/21 row + 1 day -> 2026-06-22 -> Unit 1 Day 1
06/22 row + 1 day -> 2026-06-23 -> Unit 1 Day 2
```

## Runner Rules

Runner selection is based on observable row fields, not vague learning goals.

### `concept_runner`

Use when the row is a normal content-learning row.

Observable workflow:

```text
open courseware/topic material
open notes
start timer
capture start/mid/end screenshots
candidate complete after target time
wait for uone review
```

### `practice_runner`

Use when the row contains practice/question IDs, `单元练习题`, or `闭卷限时`.

Observable workflow:

```text
open question file or Canvas assignment
open answer/checklist only when needed
track elapsed focus time
capture screenshots
candidate complete after target time and evidence package exists
wait for uone review
```

### `review_runner`

Use when the row contains `复习`, `回顾`, `错题`, `复盘`, `总结`, `自批`, or formula/vocabulary review.

Observable workflow:

```text
open previous materials/error log
open notes
capture evidence
candidate complete after target time
wait for uone review
```

## Material Slice Rule

Material selection must happen after the step is chosen:

```text
plan_step -> resource_index entries for same course/unit/category -> local file -> topic/page slice
```

For courseware:

- If the task title contains numbered sections like `1.1-1.3`, use section-heading boundaries.
- If the courseware exposes AP topic numbers, use topic-heading boundaries.
- If there is no reliable boundary, use weighted keyword search as fallback.
- Textbook excerpts are secondary references. They should not override the courseware slice for the active workflow.

## Current Risk

The old behavior mixed two responsibilities:

```text
date offset chooses task
file name and keyword search choose content
```

That can open the correct file but the wrong page. The fix is to make the selected `plan_step` explicit first, then let the runner decide which content boundaries are valid for that step.

## Inspection Command

Use this command to verify the planner before opening any files:

```bash
python3 learning_os.py plan-progression --date 2026-06-22
```

JSON form:

```bash
python3 learning_os.py plan-progression --date 2026-06-22 --format json
```

## Phase Pool Command

Use this command to inspect the generated phase pools:

```bash
python3 learning_os.py plan-phases
```

Course-specific:

```bash
python3 learning_os.py plan-phases --course AP_Calculus_BC
python3 learning_os.py plan-phases --course AP_CSA --format json
```

The phase pool is grouped by:

```text
course + phase + unit
```

Each pool contains:

- canonical plan steps from the workbook
- runner distribution
- all resource-index materials for that unit/phase

## Implemented Runtime Flow

The active task builders now use this order:

```text
build_*_tasks(date)
  -> step_for_date(course, date)
  -> canonical_*_steps(workbook)
  -> progression_runner(course, row)
  -> task_kind_for_runner(course, runner)
  -> resource resolution and material slicing
```

This means the date allocator no longer scans files first. It selects the plan step first, then the runner and material resolver act on that selected row.
