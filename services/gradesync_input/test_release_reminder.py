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
