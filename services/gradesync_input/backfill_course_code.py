"""Backfill `course_code` on student docs that predate registration setting it.

The daily pipeline routes each student to an assignment catalog by `course_code`.
Student docs created before registration wrote that field match no catalog, so those
students silently receive nothing. This fills the field from the class roster, and
falls back to the deployment's course for students who registered but are not on the
roster (staff, late adds).

Dry run by default — prints the planned writes and changes nothing. Pass --apply to
commit them.

    python3 services/gradesync_input/backfill_course_code.py
    python3 services/gradesync_input/backfill_course_code.py --apply
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_COURSE_CODE = "CS61A"
STUDENTS_COLLECTION = "students"
ROSTER_COLLECTION = "class_roster"


def decide_course_code(
    student: Dict[str, Any],
    roster: Dict[str, Dict[str, Any]],
    default_course_code: str,
) -> Optional[str]:
    """Return the course_code to write, or None to leave the doc untouched."""
    if str(student.get("course_code") or "").strip():
        return None
    email = str(student.get("email") or "").strip().lower()
    entry = roster.get(email) or {}
    return str(entry.get("course_code") or "").strip() or default_course_code


def _load(db):
    roster = {
        str((d.to_dict() or {}).get("email") or d.id).strip().lower(): (d.to_dict() or {})
        for d in db.collection(ROSTER_COLLECTION).stream()
    }
    students = [(d.id, d.to_dict() or {}) for d in db.collection(STUDENTS_COLLECTION).stream()]
    return roster, students


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the writes (default: dry run)")
    parser.add_argument("--course-code", default=DEFAULT_COURSE_CODE, help="Fallback course for students not on the roster")
    args = parser.parse_args()

    import firebase_admin
    from firebase_admin import credentials, firestore
    from shared import settings

    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            credentials.Certificate(str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)),
            {"projectId": settings.FIREBASE_PROJECT_ID},
        )
    db = firestore.client()

    roster, students = _load(db)
    print(f"Loaded {len(students)} students and {len(roster)} roster entries.\n")

    planned = []
    for doc_id, student in students:
        course_code = decide_course_code(student, roster, args.course_code)
        if course_code:
            email = str(student.get("email") or doc_id).strip().lower()
            planned.append((doc_id, email, course_code, email in roster))

    if not planned:
        print("Nothing to backfill — every student already has a course_code.")
        return

    for _, email, course_code, on_roster in sorted(planned, key=lambda p: p[1]):
        source = "roster" if on_roster else "default"
        print(f"  {email:42} -> course_code={course_code}  ({source})")

    print(f"\n{len(planned)} student(s) would be updated.")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
        return

    batch = db.batch()
    for doc_id, _, course_code, _ in planned:
        batch.update(db.collection(STUDENTS_COLLECTION).document(doc_id), {"course_code": course_code})
    batch.commit()
    print(f"\n✅ Updated {len(planned)} student doc(s).")


if __name__ == "__main__":
    main()
