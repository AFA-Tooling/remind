"""Tests for extra reminder days (dashboard "Advanced options").

The slider (`days_before_deadline`) stays the main reminder. Under Advanced options
a student can add extra days per assignment type, stored as
`extra_reminder_days: {"project": [1], "other": [0]}`. A reminder fires when the
days remaining match the slider day OR any extra day for that assignment's type.
bCourses-synced assignments have no course category and use the "other" row.
"""

from datetime import datetime, timedelta

import db_fetch


DEADLINE = datetime(2026, 6, 30, 23, 59, 59)


def make_student(**overrides):
    student = {
        "email": "student@berkeley.edu",
        "id": "stu1",
        "course_code": "CS61A",
        "days_before_deadline": 3,
        "email_pref": True,
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
    """A naive 'today' that is n days before the deadline date (negative = after)."""
    return datetime(2026, 6, 30, 9, 0, 0) - timedelta(days=n)


def fires(student, name, n):
    payload = db_fetch.build_assignment_payload(student, name, make_lookup(name), days_before(n))
    return payload is not None


PROJECT = "Hog"
HOMEWORK = "Homework 5"


# --- get_reminder_days -------------------------------------------------------

def test_reminder_days_is_just_main_day_without_extras():
    assert db_fetch.get_reminder_days(make_student(), 3, "project") == {3}


def test_reminder_days_adds_extras_for_category():
    student = make_student(extra_reminder_days={"project": [1, 0]})
    assert db_fetch.get_reminder_days(student, 3, "project") == {3, 1, 0}
    # Other categories don't pick up project's extras.
    assert db_fetch.get_reminder_days(student, 3, "homework") == {3}


def test_reminder_days_ignores_malformed_extras():
    student = make_student(extra_reminder_days={"project": [1, "2", 9, -1, True, None, 2.5]})
    assert db_fetch.get_reminder_days(student, 3, "project") == {3, 1}
    # Wrong shapes fall back to just the main day rather than crashing.
    assert db_fetch.get_reminder_days(make_student(extra_reminder_days=[1]), 3, "project") == {3}
    assert db_fetch.get_reminder_days(make_student(extra_reminder_days={"project": 1}), 3, "project") == {3}


def test_extra_equal_to_main_day_does_not_duplicate():
    student = make_student(extra_reminder_days={"project": [3]})
    assert db_fetch.get_reminder_days(student, 3, "project") == {3}


# --- course deadlines (build_assignment_payload) -----------------------------

def test_no_extras_keeps_todays_behavior():
    student = make_student()
    assert fires(student, PROJECT, 3)
    for n in (0, 1, 2, 4, 5):
        assert not fires(student, PROJECT, n), n


def test_project_extras_fire_on_each_day():
    # Jessie's ask: 3 days (slider) and 1 day before, for projects.
    student = make_student(extra_reminder_days={"project": [1]})
    assert fires(student, PROJECT, 3)
    assert fires(student, PROJECT, 1)
    assert not fires(student, PROJECT, 2)
    assert not fires(student, PROJECT, 0)


def test_project_extras_do_not_affect_homework():
    student = make_student(extra_reminder_days={"project": [1]})
    assert fires(student, HOMEWORK, 3)
    assert not fires(student, HOMEWORK, 1)


def test_every_day_from_slider_down():
    # Arav's ask: every day from 3 days out through the due date.
    student = make_student(extra_reminder_days={"homework": [2, 1, 0]})
    for n in (3, 2, 1, 0):
        assert fires(student, HOMEWORK, n), n
    assert not fires(student, HOMEWORK, 4)


def test_disabled_category_ignores_extras():
    student = make_student(
        category_prefs={"lab": True, "homework": True, "midterm": True, "project": False},
        extra_reminder_days={"project": [1]},
    )
    assert not fires(student, PROJECT, 3)
    assert not fires(student, PROJECT, 1)


def test_extras_follow_project_early_shift():
    # With project-early on, the deadline is treated as one day earlier, so every
    # reminder day (slider and extras) lands one real day sooner.
    student = make_student(project_early_reminder=True, extra_reminder_days={"project": [1]})
    assert fires(student, PROJECT, 4)
    assert fires(student, PROJECT, 2)
    assert not fires(student, PROJECT, 3)
    assert not fires(student, PROJECT, 1)


def test_extra_day_does_not_fire_past_due():
    student = make_student(extra_reminder_days={"project": [0]})
    assert fires(student, PROJECT, 0)
    assert not fires(student, PROJECT, -1)


# --- bCourses deadlines (_build_canvas_reminder_for_student) ------------------

class _FakeDoc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class _FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def where(self, *_args, **_kwargs):
        return self

    def stream(self):
        return [_FakeDoc(d) for d in self._docs]


class _FakeDb:
    def __init__(self, canvas_docs):
        self._canvas_docs = canvas_docs

    def collection(self, _name):
        return _FakeQuery(self._canvas_docs)


class Args:
    debug = False


CANVAS_DUE = "2026-06-30T23:59:59"


def canvas_fires(student, n):
    db = _FakeDb([{
        "email": student["email"],
        "assignment_name": "Reading Response",
        "course_code": "ENG101",
        "due": CANVAS_DUE,
        "submission_state": "unsubmitted",
    }])
    today = days_before(n)
    result = db_fetch._build_canvas_reminder_for_student(db, student, today, today.date(), Args)
    return result is not None


def test_canvas_without_extras_keeps_todays_behavior():
    student = make_student()
    assert canvas_fires(student, 3)
    assert not canvas_fires(student, 1)


def test_canvas_uses_other_row():
    student = make_student(extra_reminder_days={"other": [1]})
    assert canvas_fires(student, 3)
    assert canvas_fires(student, 1)
    assert not canvas_fires(student, 2)


def test_canvas_ignores_course_category_extras():
    student = make_student(extra_reminder_days={"project": [1]})
    assert not canvas_fires(student, 1)
