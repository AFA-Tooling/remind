"""
Upload deadlines from CSV file to Firestore database.

This script reads deadlines.csv and uploads it to the 'deadlines' collection
in Firestore. Uses document IDs derived from (course_code, assignment_name)
so re-running the script is always idempotent (set with merge=True).
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import firebase_admin
from firebase_admin import credentials, firestore

import sys
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings


def init_firestore() -> firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client."""
    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
    return firestore.client()


def parse_deadline(value: str) -> Optional[datetime]:
    """Parse a deadline string into a datetime object."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_deadlines_csv(csv_path: Path) -> List[Dict[str, any]]:
    """Load deadlines from CSV file and return as list of dictionaries."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Deadlines CSV not found: {csv_path}")

    deadlines = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            row = {(key or "").strip(): (value or "") for key, value in raw_row.items()}

            course_code = row.get("course_code", "").strip()
            assignment_code = row.get("assignment_code", "").strip() or None
            assignment_name = row.get("assignment_name", "").strip()
            due_str = row.get("due", "").strip()

            if not assignment_name:
                print(f"⚠️  Skipping row with missing assignment_name: {row}")
                continue

            due_date = parse_deadline(due_str)
            if not due_date:
                print(f"⚠️  Skipping row with invalid due date '{due_str}': {row}")
                continue

            deadlines.append({
                "course_code": course_code or "",
                "assignment_code": assignment_code,
                "assignment_name": assignment_name,
                "due": due_date.isoformat(),
            })

    return deadlines


def upload_deadlines_to_firestore(
    db: firestore.Client, deadlines: List[Dict[str, any]]
) -> Dict[str, int]:
    """
    Upload deadlines to Firestore using batched set(merge=True).

    Document ID is '{course_code}__{assignment_name}' (url-safe).
    Re-running is safe — existing docs are updated only if the due date changed.

    Returns:
        Dictionary with counts of inserted, updated (no-op), and error records.
    """
    stats = {"inserted": 0, "updated": 0, "errors": 0}
    collection_ref = db.collection("deadlines")

    for deadline in deadlines:
        assignment_name = deadline.get("assignment_name", "")
        course_code = deadline.get("course_code", "")

        # Build a stable, URL-safe document ID
        raw_id = f"{course_code}__{assignment_name}"
        doc_id = raw_id.replace("/", "_").replace(" ", "_")

        doc_ref = collection_ref.document(doc_id)

        try:
            existing = doc_ref.get()

            if existing.exists:
                existing_due = existing.to_dict().get("due")
                new_due = deadline.get("due")

                if existing_due != new_due:
                    doc_ref.set({**deadline, "updated_at": datetime.now().isoformat()}, merge=True)
                    stats["updated"] += 1
                    print(f"   ✅ Updated: {assignment_name} (course: {course_code}) - Due: {new_due}")
                else:
                    stats["updated"] += 1
                    print(f"   ⏭️  No change: {assignment_name} (course: {course_code})")
            else:
                doc_ref.set({**deadline, "updated_at": datetime.now().isoformat()})
                stats["inserted"] += 1
                print(f"   ➕ Inserted: {assignment_name} (course: {course_code}) - Due: {deadline.get('due')}")

        except Exception as e:
            print(f"❌ Error uploading deadline '{assignment_name}': {e}")
            stats["errors"] += 1

    return stats


def main():
    """Main function to upload deadlines from CSV to Firestore."""
    print("=" * 60)
    print("Uploading Deadlines to Firestore")
    print("=" * 60)

    # 1. Setup paths
    current_dir = Path(__file__).resolve().parent
    csv_path = current_dir / "shared_data" / "deadlines.csv"

    # 2. Connect to Firestore
    print("\n🔌 Step 1: Connecting to Firestore...")
    try:
        db = init_firestore()
        print(f"✅ Connected to Firestore project: {settings.FIREBASE_PROJECT_ID}")
    except Exception as e:
        print(f"❌ Error connecting to Firestore: {e}")
        return

    # 3. Load deadlines from CSV
    print(f"\n📂 Step 2: Loading deadlines from {csv_path}...")
    try:
        deadlines = load_deadlines_csv(csv_path)
        print(f"✅ Loaded {len(deadlines)} deadline(s) from CSV")

        # Show preview
        if deadlines:
            print("\n📋 Preview of deadlines to upload:")
            for i, deadline in enumerate(deadlines[:5], 1):
                print(f"   {i}. {deadline['assignment_name']} ({deadline['course_code']}) - Due: {deadline['due']}")
            if len(deadlines) > 5:
                print(f"   ... and {len(deadlines) - 5} more")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        return
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")
        return

    # 4. Upload to Firestore
    print("\n⬆️  Step 3: Uploading deadlines to Firestore...")
    try:
        stats = upload_deadlines_to_firestore(db, deadlines)

        print("\n✅ Upload complete!")
        print(f"   Inserted: {stats['inserted']}")
        print(f"   Updated/no-op: {stats['updated']}")
        print(f"   Errors: {stats['errors']}")

        if stats["errors"] > 0:
            print("\n⚠️  Some deadlines failed to upload. Check the errors above.")
    except Exception as e:
        print(f"❌ Error uploading to Firestore: {e}")
        return

    print("\n" + "=" * 60)
    print("✅ Process complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
