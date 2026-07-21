"""Tests for the course_code backfill decision logic.

Existing student docs predate registration writing course_code, so they route to no
catalog and receive nothing. The backfill fills the field from the class roster,
falling back to the deployment's course for students who registered but are not on
the roster. Students that already have a course_code are left alone.
"""

import backfill_course_code as backfill


ROSTER = {
    "onroster@berkeley.edu": {"course_code": "CS61A"},
    "othercourse@berkeley.edu": {"course_code": "CS10"},
}


def test_fills_from_roster():
    student = {"email": "onroster@berkeley.edu"}
    assert backfill.decide_course_code(student, ROSTER, "CS61A") == "CS61A"


def test_uses_roster_course_even_when_it_differs_from_the_default():
    student = {"email": "othercourse@berkeley.edu"}
    assert backfill.decide_course_code(student, ROSTER, "CS61A") == "CS10"


def test_falls_back_to_default_when_not_on_roster():
    student = {"email": "staff@berkeley.edu"}
    assert backfill.decide_course_code(student, ROSTER, "CS61A") == "CS61A"


def test_leaves_existing_course_code_alone():
    student = {"email": "onroster@berkeley.edu", "course_code": "CS10"}
    assert backfill.decide_course_code(student, ROSTER, "CS61A") is None


def test_treats_blank_course_code_as_missing():
    student = {"email": "onroster@berkeley.edu", "course_code": "   "}
    assert backfill.decide_course_code(student, ROSTER, "CS61A") == "CS61A"


def test_matches_roster_case_insensitively():
    student = {"email": "OnRoster@Berkeley.EDU"}
    assert backfill.decide_course_code(student, ROSTER, "CS61A") == "CS61A"
