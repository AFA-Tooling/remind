"""assignment_submissions doc IDs and status lookup.

Doc IDs used to be `{assignment}__{student name}`, with no course in them. A
student in two courses with the same assignment name (e.g. "Lab 1" in CS61A and
CS61C) got one doc, and whichever course synced last overwrote the other. Docs
are now keyed by course, assignment and email, and carry a `course_code` field.

Production still holds the old docs until they are cleaned up, so the lookup
reads both: a doc with a course_code wins for its course, and an old doc
without one is used only when no new doc exists for that course.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

SubmissionKey = Tuple[str, ...]


def _clean_id_part(value: Any) -> str:
    # Firestore doc IDs can't contain "/"; spaces are swapped to match the old IDs.
    return str(value or "").strip().replace("/", "_").replace(" ", "_")


def submission_doc_id(
    course_code: str,
    assignment_name: str,
    email: Optional[str],
    name: Optional[str] = None,
) -> str:
    """`{course}__{assignment}__{email}`, using the name when there is no email."""
    course = str(course_code or "").strip().upper()
    if not course:
        raise ValueError("submission_doc_id needs a course_code")
    student = str(email or "").strip().lower() or str(name or "").strip()
    if not student:
        raise ValueError("submission_doc_id needs an email or a name")
    return "__".join(_clean_id_part(p) for p in (course, assignment_name, student))


def build_submission_lookup(rows: Iterable[Dict[str, Any]]) -> Dict[SubmissionKey, str]:
    """Status by (course, email, assignment) for new docs, (email, assignment) for old ones."""
    lookup: Dict[SubmissionKey, str] = {}
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        assignment = str(row.get("assignment_name") or "").strip()
        if not email or not assignment:
            continue
        status = str(row.get("status") or "").strip()
        course = str(row.get("course_code") or "").strip().upper()
        key: SubmissionKey = (course, email, assignment) if course else (email, assignment)
        lookup[key] = status
    return lookup


def submission_status(
    lookup: Dict[SubmissionKey, str],
    course_code: Optional[str],
    email: str,
    assignment_name: str,
) -> Optional[str]:
    """The student's status for this assignment, or None if there is no row."""
    email = str(email or "").strip().lower()
    assignment = str(assignment_name or "").strip()
    course = str(course_code or "").strip().upper()
    if course:
        status = lookup.get((course, email, assignment))
        if status is not None:
            return status
    return lookup.get((email, assignment))  # old doc with no course
