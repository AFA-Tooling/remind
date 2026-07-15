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


def test_build_assignment_lookup_seeds_release_for_unmatched_assignment():
    # No deadlines at all, so the resource row's deadline will never match.
    deadlines = db_fetch.load_deadlines_from_rows([])
    rows = [{
        "course_code": "CS61A",
        "assignment_code": "Lab 99",
        "assignment_name": "Lab 99",
        "resource_type": "doc",
        "resource_name": "Spec",
        "link": "https://example.com",
    }]
    lookup = db_fetch.build_assignment_lookup(rows, deadlines)
    entry = lookup["CS61A"]["Lab 99"]
    assert "release" in entry
    assert entry["release"] is None


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
