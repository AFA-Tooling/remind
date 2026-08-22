"""Sync students.course_code (and category_prefs shape) from class_roster.

Roster is authoritative for which course a student is enrolled in. Run after
GradeSync roster sync on the daily job, and expose the same logic for on-demand
API use.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared.courses import default_category_prefs, get_course


def build_roster_map(db) -> Dict[str, str]:
    """email (lower) → course_code from class_roster."""
    roster_map: Dict[str, str] = {}
    for doc in db.collection("class_roster").stream():
        data = doc.to_dict() or {}
        email = (data.get("email") or doc.id or "").strip().lower()
        course_code = (data.get("course_code") or "").strip()
        if email and course_code:
            roster_map[email] = course_code
    return roster_map


def decide_student_course_update(
    student: Dict[str, Any],
    roster_map: Dict[str, str],
    *,
    fallback_course: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return Firestore merge fields if the student should be updated, else None.

    - On roster: course_code must match the roster entry.
    - Not on roster: leave course_code alone (staff / late adds keep their value).
    - When course_code changes, reshape category_prefs to the new course's
      categories (existing on/off preserved where keys still apply).
    """
    email = (student.get("email") or "").strip().lower()
    if not email:
        return None

    roster_course = roster_map.get(email)
    if not roster_course:
        return None

    current = (student.get("course_code") or "").strip()
    if current == roster_course:
        return None

    patch: Dict[str, Any] = {
        "course_code": roster_course,
        "updated_at": datetime.now().isoformat(),
    }

    # Only reshape prefs when we know the target course, or when prefs are missing.
    if get_course(roster_course):
        defaults = default_category_prefs(roster_course)
        existing = student.get("category_prefs")
        if isinstance(existing, dict):
            patch["category_prefs"] = {
                cat_id: existing.get(cat_id, True) is not False for cat_id in defaults
            }
        else:
            patch["category_prefs"] = defaults

    return patch


def decide_course_code_clear(
    student: Dict[str, Any], dropped_course_code: str
) -> Optional[Dict[str, Any]]:
    """Student was just pruned from dropped_course_code's roster.

    Clears course_code only if it still points at that course, so this never
    touches a student whose course_code was set by other means (staff, or a
    consent-enrolled participant who was never on a roster to begin with).
    """
    current = (student.get("course_code") or "").strip()
    if current != dropped_course_code:
        return None
    return {"course_code": "", "updated_at": datetime.now().isoformat()}


def sync_students_from_roster(db, *, dry_run: bool = False) -> Tuple[int, int, int]:
    """Apply roster course_codes onto students. Returns (updated, already_ok, not_on_roster)."""
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
            print(f"  [dry-run] {email}: course_code → {patch['course_code']}")
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
    """Update a single student's course from roster. Returns the patch applied, or None."""
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return None

    roster_doc = db.collection("class_roster").document(email_lower).get()
    if not roster_doc.exists:
        return None

    roster_course = (roster_doc.to_dict() or {}).get("course_code") or ""
    roster_course = str(roster_course).strip()
    if not roster_course:
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
            # Also try the raw email as doc id (auth emails are usually lowercased already).
            return None
        student_ref = matches[0].reference
        student_snap = matches[0]

    data = student_snap.to_dict() or {}
    data.setdefault("email", email_lower)
    patch = decide_student_course_update(data, {email_lower: roster_course})
    if not patch:
        return None

    student_ref.set(patch, merge=True)
    return patch
