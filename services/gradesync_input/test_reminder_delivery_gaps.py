"""Tests for the two gaps that silenced reminders for everyone but course staff.

Gap 1 — course routing: a student whose `course_code` is unset must not be
silently evaluated against a different course's catalog. Registration did not
write the field, so every self-registered student fell through to a hardcoded
CS10 fallback holding stale assignments and matched nothing, every day.

Gap 2 — the submission gate: `is_missing_submission` treated "no submission row"
as "already handled", so the caller skipped the student. On the day an assignment
is released nobody has a row yet, which silenced release-day reminders for the
whole class. Absence of a row means not submitted, so the student is notified;
only a recorded submission suppresses the reminder.
"""

from datetime import datetime

import db_fetch


TODAY = datetime(2026, 7, 20, 9, 0, 0)
RELEASED_TODAY = datetime(2026, 7, 20, 0, 0, 0)
DUE_TOMORROW = datetime(2026, 7, 21, 23, 59, 59)


class Args:
    """Stand-in for the argparse namespace `_build_reminder_for_student` reads."""

    debug = False


def make_student(**overrides):
    student = {
        "email": "student@berkeley.edu",
        "id": "stu1",
        "course_code": "CS61A",
        "days_before_deadline": 1,
        "email_pref": True,
    }
    student.update(overrides)
    return student


def make_lookup(assignment_name="Lab 7", course="CS61A", release=RELEASED_TODAY, due=DUE_TOMORROW):
    return {
        course: {
            assignment_name: {
                "assignment_name": assignment_name,
                "deadline": due,
                "release": release,
                "resources": [],
            }
        }
    }


def build(student, lookup, submissions):
    return db_fetch._build_reminder_for_student(
        student, lookup, submissions, TODAY, "___no_target___", Args
    )


# ── Gap 2: the submission gate ────────────────────────────────────────────────

def test_notifies_when_no_submission_row_exists():
    """The release-day case: the assignment just came out, so no rows exist yet."""
    reminder = build(make_student(), make_lookup(), submissions={})
    assert reminder is not None
    assert [a["assignment_name"] for a in reminder["assignments"]] == ["Lab 7"]


def test_notifies_when_status_is_missing():
    """Existing behavior: an explicit 'missing' status still notifies."""
    submissions = {("student@berkeley.edu", "Lab 7"): "missing"}
    reminder = build(make_student(), make_lookup(), submissions)
    assert reminder is not None


def test_skips_when_submission_is_recorded():
    """Existing behavior must survive: a recorded submission suppresses the reminder."""
    submissions = {("student@berkeley.edu", "Lab 7"): "2026-07-20 18:18:11 -0700"}
    assert build(make_student(), make_lookup(), submissions) is None


def test_is_missing_submission_treats_absent_row_as_not_submitted():
    assert db_fetch.is_missing_submission("student@berkeley.edu", "Lab 7", {}) is True


def test_is_missing_submission_still_false_for_recorded_submission():
    submissions = {("student@berkeley.edu", "Lab 7"): "2026-07-20 18:18:11 -0700"}
    assert db_fetch.is_missing_submission("student@berkeley.edu", "Lab 7", submissions) is False


# ── Gap 1: course routing ─────────────────────────────────────────────────────

def test_unset_course_code_does_not_borrow_another_courses_catalog():
    """An unset course_code must match nothing rather than silently reading CS10."""
    lookup = make_lookup(assignment_name="Project 1", course="CS10")
    assert db_fetch.build_assignment_payload(make_student(course_code=None), "Project 1", lookup, TODAY) is None


def test_unknown_course_code_does_not_borrow_another_courses_catalog():
    lookup = make_lookup(assignment_name="Project 1", course="CS10")
    assert db_fetch.build_assignment_payload(make_student(course_code="CS61A"), "Project 1", lookup, TODAY) is None


def test_matching_course_code_still_resolves():
    """The fix must not break the students whose course_code is set correctly."""
    payload = db_fetch.build_assignment_payload(make_student(course_code="CS61A"), "Lab 7", make_lookup(), TODAY)
    assert payload is not None
    assert payload["assignment_name"] == "Lab 7"
