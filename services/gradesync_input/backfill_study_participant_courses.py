"""Backfill `course_code` on study_participants docs, and seed per-course study_config.

Group 1/Group 2 study-gating used to be entirely global: one study_config/state doc,
and study_participants docs with no notion of which course a participant belongs to.
Now that gating is per course (services/gradesync_input/db_fetch.py::load_study_access,
src/api/admin/study.js), every participant needs a `course_code` so their access is
checked against the right course's study_config/{course_code} doc.

This does two things:
  1. Backfills course_code on study_participants docs missing it, from the matching
     students doc's course_code (fallback: class_roster). A participant with no
     signal from either source is left with course_code="" (unassigned) rather than
     guessed — under the old single-course app a global default made sense; guessing
     one course for a participant among several real courses would not.
  2. Seeds a study_config/{course_code} doc for every course_code this discovers,
     copying the CURRENT values from the old global study_config/state doc, but only
     where that course's config doc doesn't already exist. This preserves whatever
     access state real participants have right now (this is live human-subjects
     data) instead of resetting it when the per-course scheme takes over.

Dry run by default — prints the planned writes and changes nothing. Pass --apply to
commit them.

    python3 services/gradesync_input/backfill_study_participant_courses.py
    python3 services/gradesync_input/backfill_study_participant_courses.py --apply
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STUDY_PARTICIPANTS_COLLECTION = "study_participants"
STUDY_CONFIG_COLLECTION = "study_config"
STUDENTS_COLLECTION = "students"
ROSTER_COLLECTION = "class_roster"
LEGACY_CONFIG_DOC = "state"


def decide_participant_course_code(
    participant: Dict[str, Any],
    students_by_email: Dict[str, Dict[str, Any]],
    roster_by_email: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """Return the course_code to write for this participant, or None to leave it alone."""
    if str(participant.get("course_code") or "").strip():
        return None
    email = str(participant.get("email") or "").strip().lower()
    student = students_by_email.get(email) or {}
    from_student = str(student.get("course_code") or "").strip()
    if from_student:
        return from_student
    roster_entry = roster_by_email.get(email) or {}
    from_roster = str(roster_entry.get("course_code") or "").strip()
    return from_roster or ""


def _load(db):
    students_by_email = {
        str((d.to_dict() or {}).get("email") or d.id).strip().lower(): (d.to_dict() or {})
        for d in db.collection(STUDENTS_COLLECTION).stream()
    }
    roster_by_email = {
        str((d.to_dict() or {}).get("email") or d.id).strip().lower(): (d.to_dict() or {})
        for d in db.collection(ROSTER_COLLECTION).stream()
    }
    participants = [(d.id, d.to_dict() or {}) for d in db.collection(STUDY_PARTICIPANTS_COLLECTION).stream()]
    return students_by_email, roster_by_email, participants


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the writes (default: dry run)")
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

    students_by_email, roster_by_email, participants = _load(db)
    print(f"Loaded {len(participants)} study_participants, {len(students_by_email)} students, {len(roster_by_email)} roster entries.\n")

    planned: List[Tuple[str, str, str, str]] = []  # (doc_id, email, course_code, source)
    for doc_id, participant in participants:
        course_code = decide_participant_course_code(participant, students_by_email, roster_by_email)
        if course_code is None:
            continue
        email = str(participant.get("email") or doc_id).strip().lower()
        source = "unassigned (no signal)" if not course_code else (
            "students" if students_by_email.get(email, {}).get("course_code") else "roster"
        )
        planned.append((doc_id, email, course_code, source))

    if not planned:
        print("Nothing to backfill — every participant already has a course_code.")
    else:
        for _, email, course_code, source in sorted(planned, key=lambda p: p[1]):
            label = course_code or "(none)"
            print(f"  {email:42} -> course_code={label:10}  ({source})")
        print(f"\n{len(planned)} participant doc(s) would be updated.")

    discovered_courses = sorted({c for _, _, c, _ in planned if c} | {
        str((p.get("course_code") or "")).strip()
        for _, p in participants
        if str((p.get("course_code") or "")).strip()
    })

    legacy_config_snap = db.collection(STUDY_CONFIG_COLLECTION).document(LEGACY_CONFIG_DOC).get()
    legacy_config = legacy_config_snap.to_dict() if legacy_config_snap.exists else {}
    legacy_access_open = bool(legacy_config.get("access_open"))
    legacy_randomized = bool(legacy_config.get("randomized"))
    print(
        f"\nLegacy global study_config/state: access_open={legacy_access_open}, "
        f"randomized={legacy_randomized}"
    )

    config_to_seed: List[str] = []
    for course_code in discovered_courses:
        exists = db.collection(STUDY_CONFIG_COLLECTION).document(course_code).get().exists
        if not exists:
            config_to_seed.append(course_code)

    if config_to_seed:
        print(f"\nWill seed study_config for: {', '.join(config_to_seed)} (copying the legacy values above)")
    else:
        print("\nNo new per-course study_config docs needed — all discovered courses already have one.")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
        return

    if planned:
        batch = db.batch()
        for doc_id, _, course_code, _ in planned:
            batch.update(db.collection(STUDY_PARTICIPANTS_COLLECTION).document(doc_id), {"course_code": course_code})
        batch.commit()
        print(f"\n✅ Updated {len(planned)} study_participants doc(s).")

    if config_to_seed:
        batch = db.batch()
        for course_code in config_to_seed:
            batch.set(
                db.collection(STUDY_CONFIG_COLLECTION).document(course_code),
                {"access_open": legacy_access_open, "randomized": legacy_randomized},
            )
        batch.commit()
        print(f"✅ Seeded study_config for {len(config_to_seed)} course(s): {', '.join(config_to_seed)}.")


if __name__ == "__main__":
    main()
