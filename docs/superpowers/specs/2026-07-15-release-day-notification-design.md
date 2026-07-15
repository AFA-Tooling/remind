# Design: "Notify me when an assignment is released"

**Date:** 2026-07-15
**Status:** Approved

## Problem

Every AutoRemind notification today is keyed off a **due date**: an assignment fires
when `days_before_deadline` exactly matches the days remaining. Students learn an
assignment exists only as its deadline approaches, which is too late to start early.
We want an opt-in notification on the day an assignment is **released**.

This is a genuinely new axis, not a tweak to `days_before_deadline`. Release dates do
not exist anywhere in the current schema — a grep of `services/`, `src/`, and `public/`
for `release|unlock_at|available_from|start_at|posted_at` returns nothing. The field
must be introduced end to end: CSV → upload script → `DeadlineMap` → payload → message.

## Behavior

A per-student boolean preference, `release_reminder`, **off by default** for everyone
including existing students — nobody receives mail they didn't ask for.

When **on**, an assignment fires a notification on its release date, in addition to its
normal due-date reminder. Release notifications pass through the same `category_prefs`
gate as due reminders: a student who muted Labs hears nothing about lab releases.

This is an *additional* reminder, not a schedule shift. It does not interact with
`days_before_deadline` or `project_early_reminder`.

### Same-day collision

Release and due dates can collide. Lab 5 releases Jul 8 and is due Jul 9, so a student
with `days_before_deadline: 1` matches both reasons for Lab 5 on Jul 8.

**Rule: due wins.** The assignment appears once, in the due section. The due line is
strictly more actionable and already implies the assignment is out.

This rule also resolves a subtler case deterministically. `merge_reminders_by_student()`
dedupes across the CSV and Canvas sources on `_assignment_signature()` — currently
`(code, name, personal_deadline)`, which does not carry the reason. Without an explicit
precedence, a CSV release payload could win over a Canvas due payload for the same
assignment purely by arrival order, silently dropping a due reminder. "Due wins" makes
the outcome order-independent.

### `project_early_reminder` interaction

The project early-reminder day-shift stays scoped to the due branch. It exists because
submitting a project a day early earns extra credit; that has no meaning for a release
date. A release notification fires on the real release date regardless of the setting.

## Scope

- **Audience:** Roster students only. The toggle renders inside `#cs61a-section`,
  alongside the existing category checkboxes and `project_early_reminder`. Release dates
  currently exist only for CS61A; showing the toggle to non-roster students would promise
  a notification that could never fire.
- **Assignments covered:** The 30 existing `deadlines` records with a release date in the
  source spreadsheet — Labs 0–12, Homework 1–7, Quizzes 1–5, Orientation Quiz, and the
  four projects (Hog, Cats, Ants, Scheme).
- **Explicitly out of scope:** The spreadsheet's 13 discussions, Midterm, Final, and two
  surveys are **not** imported. AutoRemind has never tracked them; they have no deadline
  record and no `assignment_resources` row, and adding them is a separate decision about
  what the product covers.
- **Checkpoints:** The four project checkpoints (`Hog Checkpoint`, `Cats Checkpoint`,
  `Ants Checkpoint`, `Scheme Checkpoint`) get **no** release date. They ship with the
  parent project's handout and have no release row of their own; giving them the parent's
  date would announce Hog and Hog Checkpoint on the same day as two bullets. They continue
  to fire due-date reminders normally.

## Data model

### `deadlines/{course}__{name}` Firestore document

New field:

| Field     | Type            | Meaning                                              |
|-----------|-----------------|------------------------------------------------------|
| `release` | ISO string/null | Date the assignment is released. Null = no release notification. |

Sourced from a new `release` column in `services/gradesync_input/shared_data/deadlines.csv`.
30 rows populated, 4 checkpoint rows blank.

The source spreadsheet's assignment names do not match the deadline records — it says
`Lab 00: Getting Started` where AutoRemind says `Lab 0`, and `HW 01: Functions, Control,
Higher-Order Functions` where AutoRemind says `Homework 1`. This mismatch is resolved
**once, at authoring time**, by writing each release date into the correct existing CSV
row. Nothing downstream ever sees the spreadsheet's names, so no name-normalization layer
enters the codebase.

### `students/{email}` Firestore document

New field:

| Field              | Type    | Default | Meaning                                  |
|--------------------|---------|---------|------------------------------------------|
| `release_reminder` | boolean | `false` | Notify on assignment release day.        |

## Implementation

### `upload_deadlines_to_db.py`

Parse the `release` column and include it in the document (null when blank). Rows with a
blank `release` are still uploaded — only `due` is required.

**Required fix:** the change-detection at L115 compares only `due`, so a changed release
date would never sync on re-run. It must compare `release` as well.

### `db_fetch.py`

`DeadlineMap` is currently `Dict[str, Dict[str, Dict[str, datetime]]]` — a bare due date
with nowhere to put a second date. This type is the structural obstacle.

1. **`DeadlineMap`** value becomes a record: `{"due": datetime, "release": datetime | None}`.
2. **`load_deadlines_from_rows()`** parses `release` alongside `due` and stores the record.
   `due` remains required; a row without a parseable `due` is still skipped.
3. **`find_deadline_for_entry()`** returns the record instead of a datetime. Its matching
   cascade (code → base code → exact name → "Project N" phrase) is unchanged.
4. **`attach_deadlines_to_resources()`** sets both `entry["deadline"]` and `entry["release"]`.
5. **`build_assignment_payload()`** restructures its tail. Today it is a chain of early
   `return None` guards ending in an exact-match test on the due delta. Release-day is an
   *or*, not another *and*. After the category gate (which both reasons pass through):
   - Evaluate the **due match** exactly as today: `delta_days >= 0 and delta_days == freq_days`,
     against the `project_early_reminder`-shifted effective deadline.
   - Evaluate the **release match**: `student.get("release_reminder")` is true, `entry["release"]`
     exists, and its local date equals today.
   - Neither → `return None`. Both → due (per the collision rule).
   - The returned payload gains `"reason": "due" | "release"`.
6. **`compose_message()`** partitions on `reason`, rendering a "Just released:" section
   above the existing due list. The greeting adapts to which sections exist — it currently
   hardcodes "Heads-up: you have upcoming assignments due soon", which reads wrong on a
   release-only day. Release bullets show the assignment name, code, and resources, but no
   "due in N days" label.
7. **`merge_reminders_by_student()`** applies the collision rule when two payloads share a
   signature: a `reason == "due"` payload replaces a `reason == "release"` one. Canvas-sourced
   payloads default to `reason: "due"`.

### API

- `register.js` — seed `release_reminder: false`.
- `settings.js` — destructure `release_reminder` from the body; persist
  `studentData.release_reminder = !!release_reminder` inside the existing `category_prefs`
  block, so it stays roster-scoped exactly like `project_early_reminder`.
- `get.js` — return `release_reminder: data.release_reminder ?? false`.

### UI (`public/index.html`)

A `#release-reminder` checkbox inside `#cs61a-section`, next to `#project-early`.
`collectSettingsPayload()` includes it in the roster-gated block; `populateForm()` sets it
from the API response. Mirrors `project_early_reminder` end to end.

## Testing

`test_project_early_reminder.py` is the precedent — a fixture student plus direct
`build_assignment_payload()` assertions. New tests cover:

- Release day fires when `release_reminder` is on and today is the release date.
- No release notification when the preference is off.
- No release notification when the assignment's category is muted in `category_prefs`.
- A checkpoint (null `release`) never fires a release notification.
- Collision: an assignment matching both reasons yields exactly one payload, `reason == "due"`.
- `project_early_reminder` does not shift the release date.
- Regression: existing due-date behavior is unchanged when `release_reminder` is off.

## Rollout

1. Update `deadlines.csv`, run `upload_deadlines_to_db.py` to sync the `release` field.
2. Deploy. The preference is off for every student, so pipeline behavior is unchanged
   until someone opts in.
