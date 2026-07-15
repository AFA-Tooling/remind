# Release-Day Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `release_reminder` preference that notifies a student on the day an assignment is released, and load CS61A's release dates into Firestore.

**Architecture:** Release dates enter as a new `release` column on `deadlines.csv`, flow through `upload_deadlines_to_db.py` into the `deadlines` Firestore docs, and are carried by `DeadlineMap` — whose value type changes from a bare `datetime` to a `{"due", "release"}` record. `build_assignment_payload()` gains a second, independent reason an assignment can fire, tagging each payload with `reason: "due" | "release"`; `compose_message()` branches on that tag to render a "Just released:" section. The preference itself mirrors the existing `project_early_reminder` end to end.

**Tech Stack:** Python 3.11 (`firebase-admin`, stdlib `csv`/`datetime`/`zoneinfo`), Node.js/Express (`firebase-admin`), vanilla JS + HTML.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-15-release-day-notification-design.md`. Read it before starting.
- **No pytest in this repo.** Test files are plain scripts with a `__main__` runner block (see `services/gradesync_input/test_project_early_reminder.py`). Run them with `.venv/bin/python3 <path>` from the repo root — Python puts the script's own directory on `sys.path`, so `import db_fetch` resolves.
- **Commits:** never add a `Co-Authored-By` trailer. Always pass `--no-gpg-sign`.
- **`release_reminder` defaults to `false`** for every student, everywhere it is defaulted.
- **A missing `reason` on a payload means `"due"`.** Canvas-sourced payloads never set it, and must keep behaving as due reminders. Always read it as `.get("reason", "due")`, never `.get("reason")`, outside of an explicit `== "release"` test.
- **Release dates are date-only strings** (`2026-06-22`), not timestamps. Only the date is ever compared.
- **`due` stays required; `release` is optional.** A deadline row with a blank `release` is still uploaded and still fires due reminders.

---

### Task 1: Release dates in the CSV and the upload script

**Files:**
- Modify: `services/gradesync_input/shared_data/deadlines.csv` (add `release` column)
- Modify: `services/gradesync_input/upload_deadlines_to_db.py:48-80` (parse), `:111-121` (change detection)
- Test: `services/gradesync_input/test_release_upload.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `deadlines.csv` with a `release` column; `load_deadlines_csv()` returns dicts with a `release` key holding an ISO date string or `None`.

The spreadsheet's names don't match the CSV's (`Lab 00: Getting Started` → `Lab 0`, `HW 01: Functions, Control, Higher-Order Functions` → `Homework 1`). That mapping is resolved here, by hand, once. The four checkpoints get a blank `release` — they ship with the parent project and have no release row.

- [ ] **Step 1: Write the failing test**

Create `services/gradesync_input/test_release_upload.py`:

```python
"""Tests for release-date parsing in the deadlines CSV upload path."""

import csv
from pathlib import Path

import upload_deadlines_to_db as upload


CSV_PATH = Path(__file__).resolve().parent / "shared_data" / "deadlines.csv"


def write_csv(tmp_path, rows):
    path = tmp_path / "deadlines.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["course_code", "assignment_code", "assignment_name", "due", "release"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_release_column_is_parsed(tmp_path):
    path = write_csv(tmp_path, [
        {"course_code": "CS61A", "assignment_code": "Lab 0", "assignment_name": "Lab 0",
         "due": "2026-06-23 23:59:59", "release": "2026-06-22"},
    ])
    rows = upload.load_deadlines_csv(path)
    assert len(rows) == 1
    assert rows[0]["release"] == "2026-06-22T00:00:00"


def test_blank_release_is_none_but_row_still_loads(tmp_path):
    path = write_csv(tmp_path, [
        {"course_code": "CS61A", "assignment_code": "Hog Checkpoint", "assignment_name": "Hog Checkpoint",
         "due": "2026-07-01 23:59:59", "release": ""},
    ])
    rows = upload.load_deadlines_csv(path)
    assert len(rows) == 1, "a row with no release date must still upload"
    assert rows[0]["release"] is None


def test_real_csv_has_release_for_30_assignments():
    rows = upload.load_deadlines_csv(CSV_PATH)
    with_release = [r for r in rows if r["release"]]
    assert len(rows) == 34, f"expected 34 deadline rows, got {len(rows)}"
    assert len(with_release) == 30, f"expected 30 rows with a release date, got {len(with_release)}"


def test_real_csv_checkpoints_have_no_release():
    rows = upload.load_deadlines_csv(CSV_PATH)
    checkpoints = [r for r in rows if "Checkpoint" in r["assignment_name"]]
    assert len(checkpoints) == 4
    for row in checkpoints:
        assert row["release"] is None, f"{row['assignment_name']} must have no release date"


def test_real_csv_release_always_precedes_due():
    rows = upload.load_deadlines_csv(CSV_PATH)
    for row in rows:
        if row["release"]:
            assert row["release"] < row["due"], (
                f"{row['assignment_name']}: release {row['release']} is not before due {row['due']}"
            )


if __name__ == "__main__":
    import sys
    import tempfile

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            if "tmp_path" in test.__code__.co_varnames[: test.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as tmp:
                    test(Path(tmp))
            else:
                test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc or 'assertion failed'}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 services/gradesync_input/test_release_upload.py`
Expected: FAIL — `test_release_column_is_parsed` raises `KeyError: 'release'` (the loader doesn't emit the key yet).

- [ ] **Step 3: Add the `release` column to the CSV**

Replace `services/gradesync_input/shared_data/deadlines.csv` entirely with:

```csv
course_code,assignment_code,assignment_name,due,release
CS61A,Lab 0,Lab 0,2026-06-23 23:59:59,2026-06-22
CS61A,Lab 1,Lab 1,2026-06-25 23:59:59,2026-06-24
CS61A,Orientation Quiz (Optional),Orientation Quiz (Optional),2026-06-26 23:59:59,2026-06-23
CS61A,Homework 1,Homework 1,2026-06-30 23:59:59,2026-06-24
CS61A,Lab 2,Lab 2,2026-06-30 23:59:59,2026-06-29
CS61A,Quiz 1,Quiz 1,2026-06-30 23:59:59,2026-06-29
CS61A,Hog Checkpoint,Hog Checkpoint,2026-07-01 23:59:59,
CS61A,Lab 3,Lab 3,2026-07-02 23:59:59,2026-07-01
CS61A,Lab 4,Lab 4,2026-07-07 23:59:59,2026-07-06
CS61A,Quiz 2,Quiz 2,2026-07-07 23:59:59,2026-07-06
CS61A,Hog,Hog,2026-07-07 23:59:59,2026-06-24
CS61A,Homework 2,Homework 2,2026-07-08 23:59:59,2026-07-02
CS61A,Lab 5,Lab 5,2026-07-09 23:59:59,2026-07-08
CS61A,Cats Checkpoint,Cats Checkpoint,2026-07-14 23:59:59,
CS61A,Homework 3,Homework 3,2026-07-15 23:59:59,2026-07-09
CS61A,Lab 6,Lab 6,2026-07-16 23:59:59,2026-07-15
CS61A,Cats,Cats,2026-07-17 23:59:59,2026-07-07
CS61A,Lab 7,Lab 7,2026-07-21 23:59:59,2026-07-20
CS61A,Quiz 3,Quiz 3,2026-07-21 23:59:59,2026-07-20
CS61A,Homework 4,Homework 4,2026-07-22 23:59:59,2026-07-16
CS61A,Lab 8,Lab 8,2026-07-23 23:59:59,2026-07-22
CS61A,Ants Checkpoint,Ants Checkpoint,2026-07-23 23:59:59,
CS61A,Lab 9,Lab 9,2026-07-28 23:59:59,2026-07-27
CS61A,Quiz 4,Quiz 4,2026-07-28 23:59:59,2026-07-27
CS61A,Ants,Ants,2026-07-28 23:59:59,2026-07-17
CS61A,Homework 5,Homework 5,2026-07-29 23:59:59,2026-07-23
CS61A,Lab 10,Lab 10,2026-07-30 23:59:59,2026-07-29
CS61A,Lab 11,Lab 11,2026-08-04 23:59:59,2026-08-03
CS61A,Quiz 5,Quiz 5,2026-08-04 23:59:59,2026-08-03
CS61A,Homework 6,Homework 6,2026-08-05 23:59:59,2026-07-30
CS61A,Scheme Checkpoint,Scheme Checkpoint,2026-08-06 23:59:59,
CS61A,Lab 12,Lab 12,2026-08-10 23:59:59,2026-08-05
CS61A,Homework 7,Homework 7,2026-08-10 23:59:59,2026-08-06
CS61A,Scheme,Scheme,2026-08-13 23:59:59,2026-07-29
```

- [ ] **Step 4: Parse `release` in the loader**

In `services/gradesync_input/upload_deadlines_to_db.py`, inside `load_deadlines_csv()`, add the release read next to the existing `due_str` read:

```python
            due_str = row.get("due", "").strip()
            release_str = row.get("release", "").strip()
```

Then replace the appended dict (currently ending at the `"due"` key) with:

```python
            # release is optional — a blank means "no release notification for this
            # assignment" (e.g. project checkpoints, which ship with the parent project).
            release_date = parse_deadline(release_str)
            if release_str and not release_date:
                print(f"⚠️  Ignoring invalid release date '{release_str}' for {assignment_name}")

            deadlines.append({
                "course_code": course_code or "",
                "assignment_code": assignment_code,
                "assignment_name": assignment_name,
                "due": due_date.isoformat(),
                "release": release_date.isoformat() if release_date else None,
            })
```

- [ ] **Step 5: Fix change detection so a changed release date syncs**

Still in `upload_deadlines_to_db.py`, `upload_deadlines_to_firestore()` compares only `due`, so an edited release date would never be written on re-run. Replace the comparison block:

```python
            if existing.exists:
                existing_data = existing.to_dict()
                changed = any(
                    existing_data.get(field) != deadline.get(field)
                    for field in ("due", "release")
                )

                if changed:
                    doc_ref.set({**deadline, "updated_at": datetime.now().isoformat()}, merge=True)
                    stats["updated"] += 1
                    print(f"   ✅ Updated: {assignment_name} (course: {course_code}) - Due: {deadline.get('due')}, Release: {deadline.get('release')}")
                else:
                    stats["updated"] += 1
                    print(f"   ⏭️  No change: {assignment_name} (course: {course_code})")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python3 services/gradesync_input/test_release_upload.py`
Expected: `5/5 passed`

- [ ] **Step 7: Commit**

```bash
git add services/gradesync_input/shared_data/deadlines.csv services/gradesync_input/upload_deadlines_to_db.py services/gradesync_input/test_release_upload.py
git commit --no-gpg-sign -m "feat: add release dates to deadlines CSV and upload path"
```

---

### Task 2: Carry the release date through `DeadlineMap`

**Files:**
- Modify: `services/gradesync_input/db_fetch.py:238` (type), `:275-307` (`load_deadlines_from_rows`), `:336-396` (`find_deadline_for_entry`), `:399-416` (`attach_deadlines_to_resources`)
- Test: `services/gradesync_input/test_release_reminder.py` (create)

**Interfaces:**
- Consumes: `deadlines` Firestore docs with a `release` field (Task 1).
- Produces:
  - `DeadlineRecord = Dict[str, Optional[datetime]]` — `{"due": datetime, "release": datetime | None}`
  - `DeadlineMap = Dict[str, Dict[str, Dict[str, DeadlineRecord]]]`
  - `find_deadline_for_entry(course_code, assignment_name, assignment_code, deadlines, *, debug=False) -> Optional[DeadlineRecord]` — returns the record, not a datetime.
  - Assignment lookup entries gain `entry["release"]` (`datetime | None`) alongside `entry["deadline"]`.

`DeadlineMap`'s value is a bare `datetime` today, with nowhere to put a second date. This is the structural blocker; the matching cascade inside `find_deadline_for_entry` is untouched.

- [ ] **Step 1: Write the failing test**

Create `services/gradesync_input/test_release_reminder.py`:

```python
"""Tests for release-day notifications.

A student with `release_reminder = True` is notified on the day an assignment is
released, in addition to the normal due-date reminder. Release notifications
respect category_prefs. When an assignment fires for both reasons on the same
day, the due reason wins and it is listed once.
"""

from datetime import datetime

import db_fetch


DUE = datetime(2026, 6, 30, 23, 59, 59)
RELEASE = datetime(2026, 6, 22, 0, 0, 0)


def test_load_deadlines_carries_release():
    rows = [{
        "course_code": "CS61A",
        "assignment_code": "Lab 0",
        "assignment_name": "Lab 0",
        "due": "2026-06-30 23:59:59",
        "release": "2026-06-22",
    }]
    deadlines = db_fetch.load_deadlines_from_rows(rows)
    record = deadlines["CS61A"]["code"]["Lab 0"]
    assert record["due"] == DUE
    assert record["release"] == RELEASE
    assert deadlines["CS61A"]["name"]["Lab 0"]["release"] == RELEASE


def test_load_deadlines_tolerates_missing_release():
    rows = [{
        "course_code": "CS61A",
        "assignment_code": "Hog Checkpoint",
        "assignment_name": "Hog Checkpoint",
        "due": "2026-06-30 23:59:59",
        "release": None,
    }]
    deadlines = db_fetch.load_deadlines_from_rows(rows)
    record = deadlines["CS61A"]["code"]["Hog Checkpoint"]
    assert record["due"] == DUE
    assert record["release"] is None


def test_row_without_due_is_still_skipped():
    rows = [{
        "course_code": "CS61A",
        "assignment_code": "Lab 0",
        "assignment_name": "Lab 0",
        "due": "",
        "release": "2026-06-22",
    }]
    assert db_fetch.load_deadlines_from_rows(rows) == {}


def test_attach_deadlines_sets_both_dates():
    deadlines = db_fetch.load_deadlines_from_rows([{
        "course_code": "CS61A",
        "assignment_code": "Lab 0",
        "assignment_name": "Lab 0",
        "due": "2026-06-30 23:59:59",
        "release": "2026-06-22",
    }])
    resources = {"CS61A": {"Lab 0": {"assignment_name": "Lab 0", "assignment_code": "Lab 0", "resources": []}}}
    db_fetch.attach_deadlines_to_resources(resources, deadlines)
    entry = resources["CS61A"]["Lab 0"]
    assert entry["deadline"] == DUE
    assert entry["release"] == RELEASE


if __name__ == "__main__":
    import sys

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc or 'assertion failed'}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 services/gradesync_input/test_release_reminder.py`
Expected: FAIL — `test_load_deadlines_carries_release` errors with `TypeError: 'datetime.datetime' object is not subscriptable` (the map still stores a bare datetime).

- [ ] **Step 3: Change the `DeadlineMap` type**

In `db_fetch.py`, replace line 238:

```python
DeadlineMap = Dict[str, Dict[str, Dict[str, datetime]]]
```

with:

```python
# A deadline record carries both dates for one assignment. `due` is always present;
# `release` is None when the assignment has no release date of its own (e.g. project
# checkpoints, which ship with the parent project's handout).
DeadlineRecord = Dict[str, Optional[datetime]]
DeadlineMap = Dict[str, Dict[str, Dict[str, DeadlineRecord]]]
```

- [ ] **Step 4: Store the record in `load_deadlines_from_rows`**

Replace the body of the loop in `load_deadlines_from_rows()` (from `due_str = raw_row.get("due")` through the `debug_print` call) with:

```python
        due_str = raw_row.get("due")
        release_str = raw_row.get("release")

        due_date = parse_deadline(str(due_str) if due_str is not None else "")
        if not due_date:
            continue

        release_date = parse_deadline(str(release_str) if release_str is not None else "")
        record: DeadlineRecord = {"due": due_date, "release": release_date}

        course_deadlines = deadlines.setdefault(course_code, {"code": {}, "name": {}})

        if assignment_code:
            course_deadlines["code"][assignment_code] = record
        if assignment_name:
            course_deadlines["name"][assignment_name] = record

        scope = course_code or "(default)"
        release_note = release_date.date().isoformat() if release_date else "none"
        debug_print(
            debug,
            (
                f"Loaded deadline code='{assignment_code or 'n/a'}' "
                f"name='{assignment_name or 'n/a'}' [{scope}] → {due_date.isoformat(sep=' ')} "
                f"(release: {release_note})"
            ),
        )
```

- [ ] **Step 5: Return the record from `find_deadline_for_entry`**

Change its signature's return annotation from `Optional[datetime]` to `Optional[DeadlineRecord]`, and update its docstringless body only where names imply a datetime — the `"Project N"` phrase branch. Replace:

```python
    for scope, mapping in candidates:
        by_name = mapping.get("name", {})
        for name, due in by_name.items():
            if target_phrase in name:
                debug_print(
                    debug,
                    (
                        f"Matched deadline for code {assignment_code} using phrase "
                        f"'{target_phrase}' in scope '{scope or 'default'}'"
                    ),
                )
                return due
```

with:

```python
    for scope, mapping in candidates:
        by_name = mapping.get("name", {})
        for name, record in by_name.items():
            if target_phrase in name:
                debug_print(
                    debug,
                    (
                        f"Matched deadline for code {assignment_code} using phrase "
                        f"'{target_phrase}' in scope '{scope or 'default'}'"
                    ),
                )
                return record
```

The other three return paths (`by_code[code_key]`, `by_name[assignment_name]`) need no edit — they now yield records because the map does.

- [ ] **Step 6: Set both dates in `attach_deadlines_to_resources`**

Replace:

```python
            if matched:
                entry["deadline"] = matched
```

with:

```python
            if matched:
                entry["deadline"] = matched["due"]
                entry["release"] = matched.get("release")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python3 services/gradesync_input/test_release_reminder.py`
Expected: `4/4 passed`

- [ ] **Step 8: Run the existing suite to check for regressions**

Run: `.venv/bin/python3 services/gradesync_input/test_project_early_reminder.py`
Expected: `7/7 passed`

- [ ] **Step 9: Commit**

```bash
git add services/gradesync_input/db_fetch.py services/gradesync_input/test_release_reminder.py
git commit --no-gpg-sign -m "refactor: carry release date through DeadlineMap"
```

---

### Task 3: Fire a notification on release day

**Files:**
- Modify: `services/gradesync_input/db_fetch.py:672-716` (tail of `build_assignment_payload`)
- Test: `services/gradesync_input/test_release_reminder.py` (extend)

**Interfaces:**
- Consumes: `entry["release"]` from Task 2; `DeadlineRecord`.
- Produces: `build_assignment_payload()` returns a payload with a new `"reason"` key, `"due"` or `"release"`. All existing payload keys are unchanged.

`build_assignment_payload`'s tail is a chain of early `return None` guards ending in an exact-match test on the due delta. Release-day is an **or**, not another **and**, so the tail becomes two independent matches joined at the end. Note the existing `if delta_days < 0: return None` guard must fold into the due match rather than returning early — an early return there would suppress a release notification.

- [ ] **Step 1: Write the failing tests**

Append to `services/gradesync_input/test_release_reminder.py`, above the `__main__` block:

```python
def make_student(**overrides):
    student = {
        "email": "student@berkeley.edu",
        "id": "stu1",
        "course_code": "CS61A",
        "days_before_deadline": 5,
        "category_prefs": {"lab": True, "homework": True, "midterm": True, "quiz": True, "project": True},
    }
    student.update(overrides)
    return student


def make_lookup(assignment_name, release=RELEASE):
    return {
        "CS61A": {
            assignment_name: {
                "assignment_name": assignment_name,
                "deadline": DUE,
                "release": release,
                "resources": [],
            }
        }
    }


LAB = "Lab 5"
CHECKPOINT = "Hog Checkpoint"
ON_RELEASE_DAY = datetime(2026, 6, 22, 9, 0, 0)   # == RELEASE date
ON_DUE_MATCH_DAY = datetime(2026, 6, 25, 9, 0, 0)  # 5 days before DUE (June 30)


def test_fires_on_release_day_when_enabled():
    student = make_student(release_reminder=True)
    payload = db_fetch.build_assignment_payload(student, LAB, make_lookup(LAB), ON_RELEASE_DAY)
    assert payload is not None, "should fire on the release date"
    assert payload["reason"] == "release"
    assert payload["personal_deadline"] == DUE, "payload still carries the real due date"


def test_silent_on_release_day_when_disabled():
    student = make_student(release_reminder=False)
    assert db_fetch.build_assignment_payload(student, LAB, make_lookup(LAB), ON_RELEASE_DAY) is None


def test_silent_when_category_muted():
    student = make_student(release_reminder=True, category_prefs={
        "lab": False, "homework": True, "midterm": True, "quiz": True, "project": True,
    })
    assert db_fetch.build_assignment_payload(student, LAB, make_lookup(LAB), ON_RELEASE_DAY) is None


def test_no_release_date_never_fires_a_release():
    student = make_student(release_reminder=True)
    lookup = make_lookup(CHECKPOINT, release=None)
    assert db_fetch.build_assignment_payload(student, CHECKPOINT, lookup, ON_RELEASE_DAY) is None


def test_silent_on_a_day_that_is_neither():
    student = make_student(release_reminder=True)
    neither = datetime(2026, 6, 23, 9, 0, 0)  # not release, not 5-days-before-due
    assert db_fetch.build_assignment_payload(student, LAB, make_lookup(LAB), neither) is None


def test_due_reminder_still_fires_and_is_tagged_due():
    student = make_student(release_reminder=True)
    payload = db_fetch.build_assignment_payload(student, LAB, make_lookup(LAB), ON_DUE_MATCH_DAY)
    assert payload is not None
    assert payload["reason"] == "due"


def test_due_wins_when_both_match_same_day():
    # days_before_deadline=8 puts the due match on June 22 — the release date too.
    student = make_student(release_reminder=True, days_before_deadline=8)
    payload = db_fetch.build_assignment_payload(student, LAB, make_lookup(LAB), ON_RELEASE_DAY)
    assert payload is not None
    assert payload["reason"] == "due", "due must win a same-day collision"


def test_project_early_reminder_does_not_shift_release():
    # The day-early shift is about extra credit for early submission — meaningless
    # for a release date, so the release still fires on the real release day.
    student = make_student(release_reminder=True, project_early_reminder=True)
    lookup = make_lookup("Hog")
    payload = db_fetch.build_assignment_payload(student, "Hog", lookup, ON_RELEASE_DAY)
    assert payload is not None
    assert payload["reason"] == "release"
    # And it must not fire a day early.
    day_before = datetime(2026, 6, 21, 9, 0, 0)
    assert db_fetch.build_assignment_payload(student, "Hog", lookup, day_before) is None


def test_release_reminder_off_leaves_due_behavior_untouched():
    student = make_student(release_reminder=False)
    lookup = make_lookup(LAB)
    assert db_fetch.build_assignment_payload(student, LAB, lookup, ON_DUE_MATCH_DAY) is not None
    assert db_fetch.build_assignment_payload(student, LAB, lookup, ON_RELEASE_DAY) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 services/gradesync_input/test_release_reminder.py`
Expected: FAIL — `test_fires_on_release_day_when_enabled` fails with "should fire on the release date" (payload is `None`), and `test_due_reminder_still_fires_and_is_tagged_due` fails with `KeyError: 'reason'`.

- [ ] **Step 3: Restructure the tail of `build_assignment_payload`**

In `db_fetch.py`, replace everything from `if delta_days < 0:` through the closing `}` of the returned dict (currently lines 688-716) with:

```python
    # Two independent reasons an assignment can fire. The due match is the original
    # rule: an exact match on the notification frequency, against the (possibly
    # early-reminder-shifted) deadline. The release match is an OR against a
    # different date entirely, so it cannot be folded into the chain above.
    due_match = delta_days >= 0 and delta_days == freq_days

    release_dt = entry.get("release")
    release_match = bool(
        student.get("release_reminder")
        and release_dt
        and local_date(release_dt) == today_local
    )

    if not due_match and not release_match:
        if delta_days < 0:
            msg = f"Skipping {code}: past due (delta_days={delta_days})"
        else:
            msg = f"Skipping {code}: delta {delta_days} != freq {freq_days} and not release day"
        if is_target_student or debug:
            print(f"   ❌ {msg}")
        debug_print(debug, msg)
        return None

    # Same-day collision: an assignment can be released today and hit its due match
    # today. The due line is more actionable and implies the assignment is out, so
    # it wins and the assignment is listed once.
    reason = "due" if due_match else "release"

    if is_target_student or debug:
        print(f"   ✅ MATCH ({reason})! Will send reminder for {code}")

    return {
        "assignment_code": code,
        "assignment_name": entry.get("assignment_name", code),
        "base_deadline": entry.get("deadline"),
        "personal_deadline": personal_deadline,
        "offset_days": offset,
        "notification_window_days": freq_days,
        "resources": entry.get("resources", []),
        "reason": reason,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 services/gradesync_input/test_release_reminder.py`
Expected: `13/13 passed`

- [ ] **Step 5: Run the existing suite to check for regressions**

Run: `.venv/bin/python3 services/gradesync_input/test_project_early_reminder.py`
Expected: `7/7 passed`

- [ ] **Step 6: Commit**

```bash
git add services/gradesync_input/db_fetch.py services/gradesync_input/test_release_reminder.py
git commit --no-gpg-sign -m "feat: fire a reminder on assignment release day"
```

---

### Task 4: Render the "Just released" section

**Files:**
- Modify: `services/gradesync_input/db_fetch.py:719-774` (`compose_message`)
- Test: `services/gradesync_input/test_release_message.py` (create)

**Interfaces:**
- Consumes: payload `reason` from Task 3.
- Produces: `compose_message(student, assignments, today=None) -> str` — unchanged signature, now with a release section. New private helper `_render_resources(lines: List[str], assignment: Dict[str, Any]) -> None`.

`compose_message` hardcodes "Heads-up: you have upcoming assignments due soon" as its greeting and a "due in N days" label on every bullet — both read wrong for an assignment that just came out. Bullet numbering runs continuously across both sections, matching the existing "number the bullets when there's more than one" behavior.

- [ ] **Step 1: Write the failing test**

Create `services/gradesync_input/test_release_message.py`:

```python
"""Tests for the release section in composed reminder messages."""

from datetime import datetime

import db_fetch


TODAY = datetime(2026, 6, 22, 9, 0, 0)
DUE = datetime(2026, 6, 30, 23, 59, 59)


def make_assignment(name, reason, code=None):
    return {
        "assignment_code": code or name,
        "assignment_name": name,
        "base_deadline": DUE,
        "personal_deadline": DUE,
        "offset_days": 0,
        "notification_window_days": 5,
        "resources": [],
        "reason": reason,
    }


def test_release_only_message_does_not_say_due_soon():
    msg = db_fetch.compose_message({"first_name": "Ada"}, [make_assignment("Lab 5", "release")], TODAY)
    assert "Just released:" in msg
    assert "Lab 5" in msg
    assert "due soon" not in msg, "a release-only message must not claim things are due soon"
    assert "due in 5 days" not in msg, "release bullets carry no countdown label"


def test_due_only_message_is_unchanged():
    msg = db_fetch.compose_message({"first_name": "Ada"}, [make_assignment("Lab 5", "due")], TODAY)
    assert "Just released:" not in msg
    assert "due soon" in msg
    assert "due in 8 days" in msg


def test_both_sections_render_release_first():
    assignments = [make_assignment("Lab 5", "due"), make_assignment("Hog", "release")]
    msg = db_fetch.compose_message({"first_name": "Ada"}, assignments, TODAY)
    assert msg.index("Just released:") < msg.index("due soon")
    # Numbering runs continuously across both sections.
    assert "1. Hog" in msg
    assert "2. Lab 5" in msg


def test_missing_reason_is_treated_as_due():
    # Canvas-sourced payloads carry no reason and must keep rendering as due reminders.
    assignment = make_assignment("Lab 5", "due")
    del assignment["reason"]
    msg = db_fetch.compose_message({"first_name": "Ada"}, [assignment], TODAY)
    assert "Just released:" not in msg
    assert "due in 8 days" in msg


def test_release_bullet_shows_the_due_date():
    msg = db_fetch.compose_message({"first_name": "Ada"}, [make_assignment("Lab 5", "release")], TODAY)
    assert "June 30" in msg, "a release bullet should still tell the student when it's due"


def test_resources_render_in_the_release_section():
    assignment = make_assignment("Lab 5", "release")
    assignment["resources"] = [{"resource_name": "Lab 5 spec", "resource_type": "Handout", "link": "https://x.test/lab5"}]
    msg = db_fetch.compose_message({"first_name": "Ada"}, [assignment], TODAY)
    assert "Helpful resources:" in msg
    assert "https://x.test/lab5" in msg


if __name__ == "__main__":
    import sys

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc or 'assertion failed'}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 services/gradesync_input/test_release_message.py`
Expected: FAIL — `test_release_only_message_does_not_say_due_soon` fails on `"Just released:" in msg`.

- [ ] **Step 3: Rewrite `compose_message`**

Replace `compose_message` in `db_fetch.py` (lines 719-774) entirely with:

```python
def _render_resources(lines: List[str], assignment: Dict[str, Any]) -> None:
    """Append an assignment's resource links to `lines`, if it has any."""
    resources = [res for res in assignment.get("resources", []) if res.get("resource_name")]
    if not resources:
        return
    lines.append("  Helpful resources:")
    for res in resources:
        resource_line = f"    • {res.get('resource_name')}"
        if res.get("resource_type"):
            resource_line += f" [{res['resource_type']}]"
        if res.get("link"):
            resource_line += f": {res['link']}"
        lines.append(resource_line)


def compose_message(student: Dict[str, Any], assignments: List[Dict[str, Any]], today: Optional[datetime] = None) -> str:
    if today is None:
        today = datetime.now(PROJECT_TZ)
    today_local = today.date() if today.tzinfo is None else today.astimezone(PROJECT_TZ).date()
    preferred_name = (
        student.get("preferred_first_name")
        or student.get("first_name")
        or "there"
    )

    renderable = [a for a in assignments if a.get("personal_deadline")]
    # A payload with no reason is a due reminder — Canvas-sourced payloads never set one.
    released = [a for a in renderable if a.get("reason") == "release"]
    due_soon = [a for a in renderable if a.get("reason", "due") != "release"]

    number_assignments = len(renderable) > 1
    bullet_index = 0

    def next_bullet() -> str:
        nonlocal bullet_index
        bullet_index += 1
        return f"{bullet_index}." if number_assignments else "-"

    lines = [f"Hey {preferred_name},", ""]

    if released:
        lines.append("Just released — these assignments are now out:")
        for assignment in released:
            due_dt = assignment["personal_deadline"]
            due_date_str = f"{due_dt.strftime('%B')} {due_dt.day}"
            lines.append(
                f"{next_bullet()} {assignment['assignment_name']} ({assignment['assignment_code']}) → due on {due_date_str}"
            )
            if assignment.get("offset_days"):
                lines.append(
                    f"  (Class deadline +{assignment['offset_days']} day offset for you.)"
                )
            _render_resources(lines, assignment)

    if due_soon:
        if released:
            lines.append("")
        lines.append("Heads-up: you have upcoming assignments due soon:")
        for assignment in due_soon:
            due_dt = assignment["personal_deadline"]
            deadline_local = local_date(due_dt)
            days_until = (deadline_local - today_local).days
            due_date_str = f"{due_dt.strftime('%B')} {due_dt.day}"
            if days_until == 0:
                days_label = "due today"
            elif days_until == 1:
                days_label = "due in 1 day"
            else:
                days_label = f"due in {days_until} days"
            lines.append(
                f"{next_bullet()} {assignment['assignment_name']} ({assignment['assignment_code']}) → {days_label}, on {due_date_str}"
            )
            if assignment.get("offset_days"):
                lines.append(
                    f"  (Class deadline +{assignment['offset_days']} day offset for you.)"
                )
            _render_resources(lines, assignment)

    lines.append("")
    lines.append("Feel free to reach out to course staff if you need any support!")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 services/gradesync_input/test_release_message.py`
Expected: `6/6 passed`

- [ ] **Step 5: Commit**

```bash
git add services/gradesync_input/db_fetch.py services/gradesync_input/test_release_message.py
git commit --no-gpg-sign -m "feat: render a just-released section in reminder messages"
```

---

### Task 5: Due wins over release at merge time

**Files:**
- Modify: `services/gradesync_input/db_fetch.py:1316-1321` (dedupe block in `merge_reminders_by_student`)
- Test: `services/gradesync_input/test_release_message.py` (extend)

**Interfaces:**
- Consumes: payload `reason` from Task 3.
- Produces: no new interface — `merge_reminders_by_student()` keeps its signature.

`merge_reminders_by_student` dedupes across the CSV and Canvas sources on `_assignment_signature()` — `(code, name, personal_deadline)`, which carries no reason. Without an explicit precedence, a CSV release payload could win over a Canvas due payload for the same assignment purely by arrival order, silently dropping a due reminder. The signature deliberately stays reason-free so the two collapse; the precedence rule resolves which survives.

- [ ] **Step 1: Write the failing test**

Append to `services/gradesync_input/test_release_message.py`, above the `__main__` block:

```python
def make_entry(assignments):
    return {
        "student": {"email": "ada@berkeley.edu", "name": "Ada Lovelace", "preferred_first_name": "Ada"},
        "channels": [{"type": "email", "target": "ada@berkeley.edu"}],
        "assignments": assignments,
    }


def test_due_replaces_release_for_same_assignment():
    release_first = make_entry([make_assignment("Lab 5", "release")])
    due_second = make_entry([make_assignment("Lab 5", "due")])
    merged = db_fetch.merge_reminders_by_student([release_first, due_second])
    assert len(merged) == 1
    assignments = merged[0]["assignments"]
    assert len(assignments) == 1, "the same assignment must not be listed twice"
    assert assignments[0]["reason"] == "due"


def test_release_does_not_replace_due():
    due_first = make_entry([make_assignment("Lab 5", "due")])
    release_second = make_entry([make_assignment("Lab 5", "release")])
    merged = db_fetch.merge_reminders_by_student([due_first, release_second])
    assignments = merged[0]["assignments"]
    assert len(assignments) == 1
    assert assignments[0]["reason"] == "due", "a release payload must never displace a due one"


def test_canvas_payload_without_reason_beats_a_release():
    canvas = make_assignment("Lab 5", "due")
    del canvas["reason"]  # Canvas payloads carry no reason
    merged = db_fetch.merge_reminders_by_student([
        make_entry([make_assignment("Lab 5", "release")]),
        make_entry([canvas]),
    ])
    assignments = merged[0]["assignments"]
    assert len(assignments) == 1
    assert assignments[0].get("reason", "due") == "due"


def test_distinct_assignments_both_survive():
    merged = db_fetch.merge_reminders_by_student([
        make_entry([make_assignment("Lab 5", "release")]),
        make_entry([make_assignment("Hog", "due")]),
    ])
    assert len(merged[0]["assignments"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 services/gradesync_input/test_release_message.py`
Expected: FAIL — `test_due_replaces_release_for_same_assignment` fails on `assignments[0]["reason"] == "due"` (the release payload arrived first and is kept).

- [ ] **Step 3: Apply the precedence rule**

In `merge_reminders_by_student()`, replace:

```python
        seen_assignments = {_assignment_signature(a) for a in existing["assignments"]}
        for assignment in entry.get("assignments", []):
            sig = _assignment_signature(assignment)
            if sig not in seen_assignments:
                existing["assignments"].append(assignment)
                seen_assignments.add(sig)
```

with:

```python
        # Signature deliberately carries no reason, so a release and a due payload for
        # the same assignment collapse into one entry. Due wins that collision: it is
        # more actionable and already implies the assignment is out. A payload with no
        # reason (Canvas) counts as due.
        seen_assignments = {
            _assignment_signature(a): idx for idx, a in enumerate(existing["assignments"])
        }
        for assignment in entry.get("assignments", []):
            sig = _assignment_signature(assignment)
            if sig not in seen_assignments:
                seen_assignments[sig] = len(existing["assignments"])
                existing["assignments"].append(assignment)
            elif assignment.get("reason", "due") != "release":
                existing["assignments"][seen_assignments[sig]] = assignment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 services/gradesync_input/test_release_message.py`
Expected: `10/10 passed`

- [ ] **Step 5: Commit**

```bash
git add services/gradesync_input/db_fetch.py services/gradesync_input/test_release_message.py
git commit --no-gpg-sign -m "fix: prefer due over release when merging duplicate assignments"
```

---

### Task 6: Persist the preference through the API

**Files:**
- Modify: `src/api/reminders/register.js:41-52`, `src/api/reminders/settings.js:29`, `:64-74`, `src/api/reminders/get.js:34-57`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent of the Python pipeline).
- Produces: `students/{email}.release_reminder` (boolean). `GET /api/reminders/get` returns `release_reminder` in `data`; `POST /api/reminders/settings` accepts `release_reminder` in the body.

`release_reminder` is persisted inside the existing `category_prefs` block so it stays roster-scoped, exactly like `project_early_reminder`.

- [ ] **Step 1: Seed the default in `register.js`**

In the `studentData` object (around line 46, next to `days_before_deadline: 1`), add:

```javascript
      release_reminder: false,
```

- [ ] **Step 2: Accept it in `settings.js`**

Replace line 29:

```javascript
    const { channels = {}, days_before, preferred_first_name, category_prefs, project_early_reminder } = body;
```

with:

```javascript
    const { channels = {}, days_before, preferred_first_name, category_prefs, project_early_reminder, release_reminder } = body;
```

Then inside the `if (category_prefs && typeof category_prefs === 'object')` block, after the `project_early_reminder` line, add:

```javascript
      // Roster-only: notify on the day an assignment is released.
      studentData.release_reminder = !!release_reminder;
```

- [ ] **Step 3: Return it from `get.js`**

In the returned `data` object, after `project_early_reminder: data.project_early_reminder === true,`, add:

```javascript
                release_reminder: data.release_reminder === true,
```

- [ ] **Step 4: Verify the server still boots**

Run: `node --check src/api/reminders/settings.js && node --check src/api/reminders/get.js && node --check src/api/reminders/register.js`
Expected: no output (all three parse cleanly).

- [ ] **Step 5: Commit**

```bash
git add src/api/reminders/register.js src/api/reminders/settings.js src/api/reminders/get.js
git commit --no-gpg-sign -m "feat: persist release_reminder preference through the API"
```

---

### Task 7: The preference toggle in the UI

**Files:**
- Modify: `public/index.html:229-237` (markup), `:505-516` (`collectSettingsPayload`), `:1009-1022` (`populateForm`)

**Interfaces:**
- Consumes: `release_reminder` from `GET /api/reminders/get` (Task 6); sends it to `POST /api/reminders/settings`.
- Produces: no interface for later tasks.

The toggle lives in `#cs61a-section`, which renders only for roster students. Release dates exist only for CS61A, so showing it elsewhere would promise a notification that could never fire.

- [ ] **Step 1: Add the checkbox**

In `public/index.html`, inside the `<ul class="channels" style="margin-top: 12px;">` that holds `#project-early`, add a second `<li>` after the existing one:

```html
              <li>
                <label for="release-reminder">
                  <input id="release-reminder" type="checkbox" name="release_reminder" />
                  <span class="dot" aria-hidden="true"></span>
                  <span>Notify me when a new assignment is released</span>
                </label>
              </li>
```

- [ ] **Step 2: Send it on save**

In `collectSettingsPayload()`, inside the `if (cs61aSection && cs61aSection.style.display !== 'none')` block, after the `payload.project_early_reminder` line, add:

```javascript
        payload.release_reminder = document.getElementById('release-reminder').checked;
```

- [ ] **Step 3: Load it into the form**

In `populateForm()`, inside the `if (data.on_roster)` branch, after the `project-early` line, add:

```javascript
          document.getElementById('release-reminder').checked = data.release_reminder === true;
```

- [ ] **Step 4: Verify in the browser**

Run: `npm run dev`, open `http://localhost:3000`, sign in as a roster student.
Expected: the "Notify me when a new assignment is released" checkbox renders under the CS61A section, unchecked. Check it, save, reload the page — it stays checked. A non-roster account never sees it.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit --no-gpg-sign -m "feat: add release notification toggle to preferences UI"
```

---

### Task 8: Sync release dates to Firestore and verify end to end

**Files:**
- Run: `services/gradesync_input/upload_deadlines_to_db.py`
- Run: `services/gradesync_input/db_fetch.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `release` populated on 30 `deadlines` documents in Firestore.

- [ ] **Step 1: Upload the release dates**

Run: `.venv/bin/python3 services/gradesync_input/upload_deadlines_to_db.py`
Expected: `Inserted: 0`, `Updated/no-op: 34`, `Errors: 0` — the rows already exist, so all 34 take the update path; the 30 with a new release date print `✅ Updated`, the 4 checkpoints print `⏭️  No change`.

- [ ] **Step 2: Verify the field landed in Firestore**

Run:

```bash
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'services/gradesync_input')
from upload_deadlines_to_db import init_firestore
db = init_firestore()
docs = [d.to_dict() for d in db.collection('deadlines').stream()]
with_release = [d for d in docs if d.get('release')]
print(f'{len(docs)} deadline docs, {len(with_release)} with a release date')
for d in sorted(with_release, key=lambda x: x['release'])[:3]:
    print(' ', d['assignment_name'], '->', d['release'])
"
```

Expected: `34 deadline docs, 30 with a release date`, and the earliest three are Lab 0 (2026-06-22), Orientation Quiz (2026-06-23), then one of Lab 1 / Homework 1 / Hog (2026-06-24).

- [ ] **Step 3: Run the whole Python suite**

Run:

```bash
.venv/bin/python3 services/gradesync_input/test_release_upload.py && \
.venv/bin/python3 services/gradesync_input/test_release_reminder.py && \
.venv/bin/python3 services/gradesync_input/test_release_message.py && \
.venv/bin/python3 services/gradesync_input/test_project_early_reminder.py
```

Expected: `5/5`, `13/13`, `10/10`, `7/7` — all passing.

- [ ] **Step 4: Dry-run the pipeline**

Run: `.venv/bin/python3 services/gradesync_input/db_fetch.py --mode reminders --gmail-csv --discord-csv --debug`
Expected: completes without error and writes its CSVs. Because no student has `release_reminder` enabled yet, the output must be identical in shape to a pre-change run — no release bullets anywhere. This is the regression check that the feature is genuinely dormant until opted into.

- [ ] **Step 5: Verify a real release notification**

Enable the toggle for a test account in the UI, then re-run the pipeline with a forced date. On 2026-07-20 both Lab 7 and Quiz 3 are released, so:

```bash
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'services/gradesync_input')
from datetime import datetime
import db_fetch
student = {
    'email': 'test@berkeley.edu', 'id': 't1', 'course_code': 'CS61A',
    'days_before_deadline': 5, 'release_reminder': True,
    'category_prefs': {'lab': True, 'homework': True, 'midterm': True, 'quiz': True, 'project': True},
}
lookup = {'CS61A': {'Lab 7': {
    'assignment_name': 'Lab 7', 'deadline': datetime(2026, 7, 21, 23, 59, 59),
    'release': datetime(2026, 7, 20), 'resources': [],
}}}
p = db_fetch.build_assignment_payload(student, 'Lab 7', lookup, datetime(2026, 7, 20, 9, 0))
print('reason:', p['reason'])
print(db_fetch.compose_message({'first_name': 'Ada'}, [p], datetime(2026, 7, 20, 9, 0)))
"
```

Expected: `reason: release`, and a message reading "Just released — these assignments are now out:" / "- Lab 7 (Lab 7) → due on July 21", with no "due in N days" countdown.

- [ ] **Step 6: Commit any fixes**

If Steps 1-5 surfaced no changes, there is nothing to commit — the release dates live in Firestore, not in git. If a fix was needed:

```bash
git add -A
git commit --no-gpg-sign -m "fix: <what the end-to-end run surfaced>"
```

---

## Verification

The feature is complete when:

1. All four Python test files pass (`5/5`, `13/13`, `10/10`, `7/7`).
2. 30 of 34 `deadlines` documents in Firestore carry a `release` date; the 4 checkpoints carry none.
3. With `release_reminder` off (every student, by default), the pipeline's output is unchanged from before this work.
4. With `release_reminder` on, an assignment produces a "Just released" bullet on its release date, respects `category_prefs`, and is listed once — under "due soon" — when both reasons match the same day.
