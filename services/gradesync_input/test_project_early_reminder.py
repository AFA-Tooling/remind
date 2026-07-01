"""Tests for the project early-reminder schedule shift in build_assignment_payload.

When a student sets `project_early_reminder = True`, project-type assignments are
treated as if their deadline were one day earlier, so the whole days_before
schedule lands a day sooner. Non-project assignments are unaffected, and the real
personal deadline is still surfaced in the payload.
"""

from datetime import datetime

import db_fetch


DEADLINE = datetime(2026, 6, 30, 23, 59, 59)  # a project due June 30


def make_student(**overrides):
    student = {
        "email": "student@berkeley.edu",
        "id": "stu1",
        "course_code": "CS61A",
        "days_before_deadline": 5,
        "category_prefs": {"lab": True, "homework": True, "midterm": True, "project": True},
    }
    student.update(overrides)
    return student


def make_lookup(assignment_name):
    return {
        "CS61A": {
            assignment_name: {
                "assignment_name": assignment_name,
                "deadline": DEADLINE,
                "resources": [],
            }
        }
    }


def days_before(n):
    """A naive 'today' that is n days before the deadline date."""
    return datetime(2026, 6, 30 - n, 9, 0, 0)


# "Hog" derives to the Project category (default fallback).
PROJECT = "Hog"
HOMEWORK = "Homework 5"
# "Hog Checkpoint" also derives to Project, but must NOT get the day-early shift.
CHECKPOINT = "Hog Checkpoint"
# Quizzes are their own category (not Project), so the flag must not shift them.
QUIZ = "Quiz 1"


def test_quiz_is_its_own_category():
    assert db_fetch.derive_assignment_category("Quiz 1") == "Quiz"
    # Substring match catches the odd-named optional quiz too.
    assert db_fetch.derive_assignment_category("Orientation Quiz (Optional)") == "Quiz"


def test_quiz_unaffected_by_flag():
    student = make_student(project_early_reminder=True)
    lookup = make_lookup(QUIZ)
    # Quizzes are no longer Project category, so the flag must not shift them.
    assert db_fetch.build_assignment_payload(student, QUIZ, lookup, days_before(6)) is None
    assert db_fetch.build_assignment_payload(student, QUIZ, lookup, days_before(5)) is not None


def test_project_fires_one_day_earlier_when_flag_on():
    student = make_student(project_early_reminder=True)
    lookup = make_lookup(PROJECT)
    # days_before=5, flag on -> effective deadline June 29 -> fires at real delta 6.
    payload = db_fetch.build_assignment_payload(student, PROJECT, lookup, days_before(6))
    assert payload is not None
    # At the normal (unshifted) day, the project should NOT fire.
    assert db_fetch.build_assignment_payload(student, PROJECT, lookup, days_before(5)) is None


def test_project_fires_at_real_freq_when_flag_off():
    student = make_student(project_early_reminder=False)
    lookup = make_lookup(PROJECT)
    assert db_fetch.build_assignment_payload(student, PROJECT, lookup, days_before(6)) is None
    assert db_fetch.build_assignment_payload(student, PROJECT, lookup, days_before(5)) is not None


def test_non_project_unaffected_by_flag():
    student = make_student(project_early_reminder=True)
    lookup = make_lookup(HOMEWORK)
    # Homework must NOT shift even with the flag on.
    assert db_fetch.build_assignment_payload(student, HOMEWORK, lookup, days_before(6)) is None
    assert db_fetch.build_assignment_payload(student, HOMEWORK, lookup, days_before(5)) is not None


def test_checkpoint_unaffected_by_flag():
    student = make_student(project_early_reminder=True)
    lookup = make_lookup(CHECKPOINT)
    # Checkpoints fall under the Project category but earn no early-submission
    # extra credit, so the flag must not shift their schedule.
    assert db_fetch.build_assignment_payload(student, CHECKPOINT, lookup, days_before(6)) is None
    assert db_fetch.build_assignment_payload(student, CHECKPOINT, lookup, days_before(5)) is not None


def test_payload_still_reports_real_personal_deadline():
    student = make_student(project_early_reminder=True)
    lookup = make_lookup(PROJECT)
    payload = db_fetch.build_assignment_payload(student, PROJECT, lookup, days_before(6))
    assert payload is not None
    # The displayed deadline stays the real one (June 30), not the shifted date.
    assert payload["personal_deadline"] == DEADLINE


if __name__ == "__main__":
    # Lightweight runner so the suite runs under plain `python` (no pytest in venv).
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
