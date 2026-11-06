"""Tests for assignment_submissions doc IDs and the old/new-doc status lookup."""

import pytest

from db_fetch import is_missing_submission  # also puts services/ on sys.path
from shared.submissions import build_submission_lookup, submission_doc_id, submission_status


# --- submission_doc_id ------------------------------------------------------

def test_doc_id_is_course_assignment_email():
    assert submission_doc_id("cs61a", "Lab 1", " Alice@Example.com ") == "CS61A__Lab_1__alice@example.com"


def test_doc_id_same_assignment_in_two_courses_differs():
    a = submission_doc_id("CS61A", "Lab 1", "alice@example.com")
    c = submission_doc_id("CS61C", "Lab 1", "alice@example.com")
    assert a != c


def test_doc_id_falls_back_to_name_without_email():
    assert submission_doc_id("CS61A", "Lab 1", None, "Alice Smith") == "CS61A__Lab_1__Alice_Smith"


def test_doc_id_replaces_slashes():
    assert "/" not in submission_doc_id("CS61A", "Lab 1/2", "a@example.com")


def test_doc_id_requires_course_and_student():
    with pytest.raises(ValueError):
        submission_doc_id("", "Lab 1", "a@example.com")
    with pytest.raises(ValueError):
        submission_doc_id("CS61A", "Lab 1", None, None)


# --- lookup -----------------------------------------------------------------

def _row(status, course=None, email="alice@example.com", assignment="Lab 1"):
    row = {"email": email, "assignment_name": assignment, "status": status}
    if course:
        row["course_code"] = course
    return row


def test_new_docs_are_kept_per_course():
    lookup = build_submission_lookup([_row("Graded", "CS61A"), _row("Missing", "CS61C")])
    assert submission_status(lookup, "CS61A", "alice@example.com", "Lab 1") == "Graded"
    assert submission_status(lookup, "CS61C", "alice@example.com", "Lab 1") == "Missing"


def test_new_doc_wins_over_old_doc():
    lookup = build_submission_lookup([_row("Missing"), _row("Graded", "CS61A")])
    assert submission_status(lookup, "CS61A", "alice@example.com", "Lab 1") == "Graded"


def test_old_doc_used_when_no_new_doc_for_that_course():
    lookup = build_submission_lookup([_row("Graded"), _row("Missing", "CS61C")])
    assert submission_status(lookup, "CS61A", "alice@example.com", "Lab 1") == "Graded"


def test_old_doc_used_when_course_unknown():
    lookup = build_submission_lookup([_row("Graded")])
    assert submission_status(lookup, None, "Alice@Example.com ", "Lab 1") == "Graded"


def test_no_row_is_none():
    lookup = build_submission_lookup([_row("Graded", "CS61A")])
    assert submission_status(lookup, "CS61C", "alice@example.com", "Lab 1") is None
    assert submission_status(lookup, "CS61A", "bob@example.com", "Lab 1") is None


def test_rows_without_email_are_skipped():
    assert build_submission_lookup([_row("Graded", "CS61A", email=None)]) == {}


def test_course_code_case_is_normalized():
    lookup = build_submission_lookup([_row("Graded", "cs61a")])
    assert submission_status(lookup, "CS61A", "alice@example.com", "Lab 1") == "Graded"


# --- is_missing_submission (db_fetch) ----------------------------------------

def test_missing_is_per_course():
    # The bug this fixes: Alice submitted CS61A Lab 1 but not CS61C Lab 1.
    lookup = build_submission_lookup([_row("Graded", "CS61A"), _row("Missing", "CS61C")])
    assert not is_missing_submission("alice@example.com", "Lab 1", lookup, "CS61A")
    assert is_missing_submission("alice@example.com", "Lab 1", lookup, "CS61C")


def test_missing_when_no_row_at_all():
    assert is_missing_submission("alice@example.com", "Lab 1", {}, "CS61A")


def test_missing_falls_back_to_old_doc():
    lookup = build_submission_lookup([_row("Ungraded")])
    assert not is_missing_submission("alice@example.com", "Lab 1", lookup, "CS61A")
    assert not is_missing_submission("alice@example.com", "Lab 1", lookup)
