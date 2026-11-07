"""Sync students' courses (course_codes, plus the legacy course_code) from class_roster.

Roster is authoritative for which courses a student is enrolled in. Run after
GradeSync roster sync on the daily job, and expose the same logic for on-demand
API use.

A student can be on several courses' rosters. Docs carry the full list in
`course_codes`, and still carry the legacy single `course_code` (one of the
courses in the list) for code that hasn't moved to the list yet. See
student_course_codes in shared/courses.py for how both shapes are read.
Mirrored in src/api/students/syncCourse.js.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared.courses import get_course, merge_category_prefs, student_course_codes

RosterCodes = Union[str, Sequence[str]]


def _now() -> str:
    return datetime.now().isoformat()


def _as_code_list(value: Optional[RosterCodes]) -> List[str]:
    if isinstance(value, str):
        value = [value]
    return student_course_codes({"course_codes": list(value or [])})


def _pick_legacy_code(current: Any, codes: List[str]) -> str:
    """Keep the legacy course_code if it's still one of the courses, else the first."""
    normalized = str(current or "").strip().upper()
    if normalized in codes:
        return normalized
    return codes[0] if codes else ""


# --- class_roster -----------------------------------------------------------

def decide_roster_entry(
    existing: Optional[Dict[str, Any]],
    course_code: str,
    name: str,
    email: str,
) -> Dict[str, Any]:
    """Merge fields for a roster doc whose student is on course_code's sheet."""
    codes = student_course_codes(existing or {})
    course = str(course_code).strip().upper()
    if course not in codes:
        codes.append(course)
    return {
        "name": name,
        "email": email,
        "course_codes": codes,
        "course_code": _pick_legacy_code((existing or {}).get("course_code"), codes),
        "updated_at": _now(),
    }


def decide_roster_prune(
    existing: Dict[str, Any], course_code: str
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """A roster doc's student is no longer on course_code's sheet.

    Returns ("keep", None) if they weren't in that course, ("delete", None) if it
    was their only course, or ("update", patch) to drop just that course.
    """
    course = str(course_code).strip().upper()
    codes = student_course_codes(existing)
    if course not in codes:
        return "keep", None
    remaining = [c for c in codes if c != course]
    if not remaining:
        return "delete", None
    return "update", {
        "course_codes": remaining,
        "course_code": _pick_legacy_code(existing.get("course_code"), remaining),
        "updated_at": _now(),
    }


def build_roster_map(db) -> Dict[str, List[str]]:
    """email (lower) → course codes from class_roster."""
    roster_map: Dict[str, List[str]] = {}
    for doc in db.collection("class_roster").stream():
        data = doc.to_dict() or {}
        email = (data.get("email") or doc.id or "").strip().lower()
        codes = student_course_codes(data)
        if email and codes:
            roster_map[email] = codes
    return roster_map


# --- students ---------------------------------------------------------------

def _legacy_switch_patch(student: Dict[str, Any], new_code: str) -> Dict[str, Any]:
    """course_code moved to new_code: reshape the legacy category_prefs to match."""
    patch: Dict[str, Any] = {"course_code": new_code}
    if new_code and get_course(new_code):
        patch["category_prefs"] = merge_category_prefs(new_code, student.get("category_prefs"))
    return patch


def decide_student_course_update(
    student: Dict[str, Any],
    roster_map: Mapping[str, RosterCodes],
    *,
    fallback_course: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return Firestore merge fields if the student should be updated, else None.

    - Pinned (course_code_pinned: true): never touched by roster sync. An admin
      sets the pin directly on the doc; it survives every roster sync until unset.
    - On roster: course_codes must equal the roster's courses, and course_code
      must be one of them (kept if it already is, else the first).
    - Not on roster: leave alone (staff / late adds keep their value).
    - When course_code changes, reshape category_prefs to the new course's
      categories (existing on/off preserved where keys still apply).
    """
    if student.get("course_code_pinned"):
        return None

    email = (student.get("email") or "").strip().lower()
    if not email:
        return None

    roster_codes = _as_code_list(roster_map.get(email))
    if not roster_codes:
        return None

    patch: Dict[str, Any] = {}
    if student.get("course_codes") != roster_codes:
        patch["course_codes"] = roster_codes

    new_legacy = _pick_legacy_code(student.get("course_code"), roster_codes)
    if str(student.get("course_code") or "").strip() != new_legacy:
        patch.update(_legacy_switch_patch(student, new_legacy))

    if not patch:
        return None
    patch["updated_at"] = _now()
    return patch


def decide_course_code_clear(
    student: Dict[str, Any], dropped_course_code: str
) -> Optional[Dict[str, Any]]:
    """Student was just pruned from dropped_course_code's roster.

    Removes that course from the student's courses, and only that course, so this
    never touches a student who wasn't in it (staff, or a consent-enrolled
    participant who was never on a roster to begin with). If the legacy
    course_code pointed at it, it moves to a remaining course, or "" if none.
    A pinned student is never touched either way.
    """
    if student.get("course_code_pinned"):
        return None

    dropped = str(dropped_course_code or "").strip().upper()
    codes = student_course_codes(student)
    if dropped not in codes:
        return None

    remaining = [c for c in codes if c != dropped]
    patch: Dict[str, Any] = {"course_codes": remaining}
    new_legacy = _pick_legacy_code(student.get("course_code"), remaining)
    if str(student.get("course_code") or "").strip() != new_legacy:
        patch.update(_legacy_switch_patch(student, new_legacy))
    patch["updated_at"] = _now()
    return patch


def sync_students_from_roster(db, *, dry_run: bool = False) -> Tuple[int, int, int]:
    """Apply roster courses onto students. Returns (updated, already_ok, not_on_roster)."""
    roster_map = build_roster_map(db)
    updated = 0
    already_ok = 0
    not_on_roster = 0

    batch = db.batch()
    batch_size = 0

    for doc in db.collection("students").stream():
        data = doc.to_dict() or {}
        data.setdefault("email", doc.id)
        email = (data.get("email") or doc.id or "").strip().lower()

        if email not in roster_map:
            not_on_roster += 1
            continue

        patch = decide_student_course_update(data, roster_map)
        if not patch:
            already_ok += 1
            continue

        updated += 1
        if dry_run:
            print(
                f"  [dry-run] {email}: course_codes -> {patch.get('course_codes', data.get('course_codes'))}, "
                f"course_code -> {patch.get('course_code', data.get('course_code'))}"
            )
            continue

        batch.set(doc.reference, patch, merge=True)
        batch_size += 1
        if batch_size >= 400:
            batch.commit()
            batch = db.batch()
            batch_size = 0

    if not dry_run and batch_size > 0:
        batch.commit()

    return updated, already_ok, not_on_roster


def sync_one_student_from_roster(db, email: str) -> Optional[Dict[str, Any]]:
    """Update a single student's courses from roster. Returns the patch applied, or None."""
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return None

    roster_doc = db.collection("class_roster").document(email_lower).get()
    if not roster_doc.exists:
        return None

    roster_codes = student_course_codes(roster_doc.to_dict() or {})
    if not roster_codes:
        return None

    student_ref = db.collection("students").document(email_lower)
    # Student docs are keyed by the login email; try exact then lowercase.
    student_snap = student_ref.get()
    if not student_snap.exists:
        # Some docs may be keyed with original casing from auth.
        matches = list(
            db.collection("students").where("email", "==", email_lower).limit(1).stream()
        )
        if not matches:
            return None
        student_ref = matches[0].reference
        student_snap = matches[0]

    data = student_snap.to_dict() or {}
    data.setdefault("email", email_lower)
    patch = decide_student_course_update(data, {email_lower: roster_codes})
    if not patch:
        return None

    student_ref.set(patch, merge=True)
    return patch
