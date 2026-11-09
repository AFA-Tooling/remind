"""Reminders for a student enrolled in more than one course.

Each course is checked against its own catalog and its own submissions, all
with the student's one set of reminder settings, and everything goes out as one
combined message. Course names appear only when a message mixes courses.
"""

from datetime import datetime

import db_fetch
from shared.submissions import build_submission_lookup

TODAY = datetime(2026, 7, 20, 9, 0, 0)
DUE_IN_3 = datetime(2026, 7, 23, 23, 59, 59)
DUE_IN_5 = datetime(2026, 7, 25, 23, 59, 59)
EMAIL = "alice@berkeley.edu"


class Args:
    debug = False


def make_student(**overrides):
    student = {
        "email": EMAIL,
        "id": "stu1",
        "course_code": "CS61A",
        "course_codes": ["CS61A", "CS61C"],
        "days_before_deadline": 3,
        "email_pref": True,
    }
    student.update(overrides)
    return student


def entry(name, due=DUE_IN_3, course=None):
    return {"assignment_name": name, "deadline": due, "release": None, "resources": [],
            "course_code": course}


LOOKUP = {
    "CS61A": {"Lab 1": entry("Lab 1", course="CS61A"), "Hog": entry("Hog", course="CS61A")},
    "CS61C": {"Lab 1": entry("Lab 1", course="CS61C"), "Project 1": entry("Project 1", course="CS61C")},
    "CS10": {"Project 2": entry("Project 2", course="CS10")},
}


def build(student, submissions=(), lookup=LOOKUP):
    return db_fetch._build_reminder_for_student(
        student, lookup, build_submission_lookup(list(submissions)), TODAY, "___no_target___", Args
    )


def names(reminder):
    return [(a["course_code"], a["assignment_name"]) for a in reminder["assignments"]]


def sub(course, name, status):
    return {"course_code": course, "email": EMAIL, "assignment_name": name, "status": status}


def test_reminds_for_every_course_in_one_message():
    reminder = build(make_student())
    assert names(reminder) == [
        ("CS61A", "Hog"), ("CS61A", "Lab 1"), ("CS61C", "Lab 1"), ("CS61C", "Project 1"),
    ]
    # Not CS10: the student isn't in it.
    assert "Project 2" not in reminder["message"]


def test_submission_in_one_course_does_not_hide_the_other():
    reminder = build(make_student(), [sub("CS61A", "Lab 1", "Graded"), sub("CS61C", "Lab 1", "Missing")])
    assert ("CS61A", "Lab 1") not in names(reminder)
    assert ("CS61C", "Lab 1") in names(reminder)


def test_one_set_of_settings_applies_to_every_course():
    reminder = build(make_student(category_prefs={"lab": False}))
    assert names(reminder) == [("CS61A", "Hog"), ("CS61C", "Project 1")]


def test_days_before_applies_to_every_course():
    lookup = {
        "CS61A": {"Lab 1": entry("Lab 1", due=DUE_IN_5, course="CS61A")},
        "CS61C": {"Lab 1": entry("Lab 1", due=DUE_IN_5, course="CS61C")},
    }
    assert build(make_student(), lookup=lookup) is None
    reminder = build(make_student(days_before_deadline=5), lookup=lookup)
    assert names(reminder) == [("CS61A", "Lab 1"), ("CS61C", "Lab 1")]


def test_mixed_course_message_names_the_course():
    message = build(make_student())["message"]
    assert "[CS 61A] Lab 1" in message
    assert "[CS 61C] Lab 1" in message


def test_single_course_message_is_unchanged():
    reminder = build(make_student(course_codes=["CS61A"]))
    assert names(reminder) == [("CS61A", "Hog"), ("CS61A", "Lab 1")]
    assert "[CS 61A]" not in reminder["message"]
    assert "1. Hog (Hog): due in 3 days" in reminder["message"]


def test_multi_course_student_with_one_course_due_today_has_no_labels():
    reminder = build(make_student(), [
        sub("CS61A", "Lab 1", "Graded"), sub("CS61A", "Hog", "Graded"),
    ])
    assert names(reminder) == [("CS61C", "Lab 1"), ("CS61C", "Project 1")]
    assert "[CS 61C]" not in reminder["message"]


def test_old_shape_student_still_gets_their_one_course():
    student = make_student()
    del student["course_codes"]
    assert names(build(student)) == [("CS61A", "Hog"), ("CS61A", "Lab 1")]


def test_unknown_course_is_skipped_but_others_still_send():
    reminder = build(make_student(course_codes=["CS99", "CS61C"]))
    assert names(reminder) == [("CS61C", "Lab 1"), ("CS61C", "Project 1")]


def test_merge_keeps_same_named_assignments_from_two_courses():
    reminder = build(make_student())
    merged = db_fetch.merge_reminders_by_student([reminder])
    assert len(merged[0]["assignments"]) == 4
    assert "[CS 61C] Lab 1" in merged[0]["message"]


def test_gmail_subject_summary_names_courses_when_mixed(tmp_path):
    db_fetch.write_gmail_csv([build(make_student())], tmp_path)
    text = (tmp_path / "message_requests.csv").read_text(encoding="utf-8")
    assert "[CS 61A] Hog" in text and "[CS 61C] Project 1" in text
