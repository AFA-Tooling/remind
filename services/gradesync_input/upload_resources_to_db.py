"""
Upload assignment resources to Firestore.

Uploads each row to the 'assignment_resources' collection using a stable
document ID derived from (course_code, assignment_code, resource_name) so
re-running always updates existing entries (e.g. assignment_name renames)
rather than silently skipping them.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List

import firebase_admin
from firebase_admin import credentials, firestore

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


# Fields: (course_code, assignment_code, assignment_name, resource_type, resource_name, link)
# assignment_name must exactly match the Google Sheet tab name.
# Entries with empty resource_name/link are placeholder entries that ensure
# the assignment appears in the reminder lookup even without specific resources.
RESOURCES = [
    # ── CS61A Homework ──────────────────────────────────────────────────────
    ("CS61A", "HW01", "Homework 1", "Reading", "Section 1.1", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Homework 1", "Reading", "Section 1.2", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Homework 1", "Reading", "Section 1.3", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Homework 1", "Reading", "Section 1.4", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Homework 1", "Reading", "Section 1.5", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Homework 1", "Video", "Getting Started", "https://www.youtube.com/watch?v=playlist&list=PLx38hZJ5RLZdE6Ugbn03lUj4utfzETMHA"),
    ("CS61A", "HW02", "Homework 2", "Reading", "Section 1.6", "https://www.composingprograms.com/"),
    ("CS61A", "HW02", "Homework 2", "Reading", "ok guide", "https://cs61a.org/articles/using-ok/"),
    ("CS61A", "HW03", "Homework 3", "Reading", "Section 1.7", "https://www.composingprograms.com/"),
    ("CS61A", "HW03", "Homework 3", "Reading", "ok guide", "https://cs61a.org/articles/using-ok/"),
    ("CS61A", "HW04", "Homework 4", "Reading", "Section 2.3", "https://www.composingprograms.com/"),
    ("CS61A", "HW04", "Homework 4", "Reading", "Section 2.5", "https://www.composingprograms.com/"),
    ("CS61A", "HW04", "Homework 4", "Reading", "ok guide", "https://cs61a.org/articles/using-ok/"),
    ("CS61A", "HW05", "Homework 5", "Reading", "Section 4.2", "https://www.composingprograms.com/"),
    ("CS61A", "HW06", "Homework 6", "Reading", "Scheme Specification", "https://cs61a.vercel.app/articles/scheme-spec/index.html"),
    ("CS61A", "HW06", "Homework 6", "Reading", "Scheme Built-in Procedure Reference", "https://cs61a.vercel.app/articles/scheme-builtins/index.html"),
    ("CS61A", "HW06", "Homework 6", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZfnXDXftRu5P0mn_crGWaWd"),
    ("CS61A", "HW07", "Homework 7", "Reading", "Scheme Specification", "https://cs61a.vercel.app/articles/scheme-spec/index.html"),
    ("CS61A", "HW07", "Homework 7", "Reading", "Scheme Built-in Procedure Reference", "https://cs61a.vercel.app/articles/scheme-builtins/index.html"),
    ("CS61A", "HW07", "Homework 7", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZea1rWe3s2JtuCIku_blUu_"),
    ("CS61A", "HW08", "Homework 8", "", "", ""),

    # ── CS61A Labs ──────────────────────────────────────────────────────────
    ("CS61A", "Lab O", "Lab O", "", "", ""),
    ("CS61A", "Lab 1", "Lab 1", "", "", ""),
    ("CS61A", "Lab 2", "Lab 2", "", "", ""),
    ("CS61A", "Lab 3", "Lab 3", "", "", ""),
    ("CS61A", "Lab 4", "Lab 4", "", "", ""),
    ("CS61A", "Lab 5", "Lab 5", "", "", ""),
    ("CS61A", "Lab 6", "Lab 6", "", "", ""),
    ("CS61A", "Lab 7", "Lab 7", "", "", ""),
    ("CS61A", "Lab 8", "Lab 8", "", "", ""),
    ("CS61A", "Lab 9", "Lab 9", "", "", ""),

    # ── CS61A Projects ──────────────────────────────────────────────────────
    # Note: the YouTube links for Cats and Ants were inherited from the old
    # "Project 2" and "Project 3" entries — please verify they point to the
    # correct getting-started playlists.
    ("CS61A", "Hog", "Hog", "Reading", "Sections 1.2", "https://www.composingprograms.com/"),
    ("CS61A", "Hog", "Hog", "Reading", "Sections 1.3", "https://www.composingprograms.com/"),
    ("CS61A", "Hog", "Hog", "Reading", "Sections 1.4", "https://www.composingprograms.com/"),
    ("CS61A", "Hog", "Hog", "Reading", "Sections 1.5", "https://www.composingprograms.com/"),
    ("CS61A", "Hog", "Hog", "Reading", "Sections 1.6", "https://www.composingprograms.com/"),
    ("CS61A", "Hog", "Hog", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZfpHDDcEnevQqlX4wTxuMAD"),
    ("CS61A", "Hog Checkpoint", "Hog Checkpoint", "", "", ""),
    ("CS61A", "Cats", "Cats", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZdH1AQFUuP-ixu7nAEK4OLP"),
    ("CS61A", "Cats Checkpoint", "Cats Checkpoint", "", "", ""),
    ("CS61A", "Ants", "Ants", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZez4iVyVRr52Eknxs4RF27w"),
    ("CS61A", "Ants Checkpoint 1", "Ants Checkpoint 1", "", "", ""),
    ("CS61A", "Ants Checkpoint 2", "Ants Checkpoint 2", "", "", ""),
    ("CS61A", "Scheme", "Scheme", "", "", ""),
    ("CS61A", "Scheme Checkpoint 1", "Scheme Checkpoint 1", "", "", ""),
    ("CS61A", "Scheme Checkpoint 2", "Scheme Checkpoint 2", "", "", ""),
    ("CS61A", "Scheme Contest", "Scheme Contest", "", "", ""),

    # ── CS61A Other ─────────────────────────────────────────────────────────
    ("CS61A", "Midterm", "Midterm", "", "", ""),

    # ── CS10 Projects ───────────────────────────────────────────────────────
    ("CS10", "Project 1", "Project 1: Wordle™-lite", "Reading", "Proj 1 Walkthrough Slides", "https://drive.google.com/file/d/1liTxubkrh5-Vtp5CbQETI9BurAquIVSx/view"),
    ("CS10", "Project 2", "Project 2: Spelling Bee", "Reading", "Proj 2 Walkthrough Slides", "https://drive.google.com/file/d/1eJQpY5PpUwt3vesplElChY293NFQk4Vp/view"),
    ("CS10", "Project 3", "Project 3: 2048", "Reading", "Proj 3 Walkthrough Slides", "https://drive.google.com/file/d/1koa1TbOmoDa5tiIEm6hohQjiMaWjLI1H/view"),
    ("CS10", "Project 4", "Project 4: Tech in Context", "Reading", "Proj 4 Walkthrough Slides", "https://drive.google.com/drive/folders/1Rr0uR3vTD9ch5qs6IaLWrtEILqh_mCzk"),
    ("CS10", "Project 4", "Project 4: Presentations", "Reading", "Proj 4 Walkthrough Slides", "https://drive.google.com/drive/folders/1Rr0uR3vTD9ch5qs6IaLWrtEILqh_mCzk"),
    ("CS10", "Project 4", "Project 4: Feedback + Comments", "Reading", "Proj 4 Walkthrough Slides", "https://drive.google.com/drive/folders/1Rr0uR3vTD9ch5qs6IaLWrtEILqh_mCzk"),
    ("CS10", "Project 5", "Project 5: Proposals", "Reading", "Example bug writeup", "https://docs.google.com/document/d/1A6Tzm0UZte8gMnnmE2PV1J9xO__z6SaLkDVA6j3-I5s/edit?tab=t.0"),
    ("CS10", "Project 5", "Project 5: Proposal Meetings", "Reading", "Example bug writeup", "https://docs.google.com/document/d/1A6Tzm0UZte8gMnnmE2PV1J9xO__z6SaLkDVA6j3-I5s/edit?tab=t.0"),
    ("CS10", "Project 5", "Project 5: Final Project", "Reading", "Example bug writeup", "https://docs.google.com/document/d/1A6Tzm0UZte8gMnnmE2PV1J9xO__z6SaLkDVA6j3-I5s/edit?tab=t.0"),
]


def _doc_id(course_code: str, assignment_code: str, resource_name: str) -> str:
    """Stable document ID derived from the composite key."""
    raw = f"{course_code}__{assignment_code}__{resource_name}"
    return re.sub(r"[^\w]", "_", raw)


def build_documents() -> List[Dict[str, str]]:
    """Convert raw tuples into Firestore document dicts."""
    docs = []
    for course_code, assignment_code, assignment_name, resource_type, resource_name, link in RESOURCES:
        docs.append({
            "course_code": course_code,
            "assignment_code": assignment_code,
            "assignment_name": assignment_name,
            "resource_type": resource_type,
            "resource_name": resource_name,
            "link": link,
        })
    return docs


def upload_resources(db: firestore.Client, documents: List[Dict[str, str]]) -> Dict[str, int]:
    """
    Upsert resources to Firestore using stable document IDs.

    Uses set(merge=True) so re-running updates changed fields (e.g. renamed
    assignment_name) rather than skipping existing entries.
    """
    stats = {"inserted": 0, "updated": 0, "errors": 0}
    collection_ref = db.collection("assignment_resources")

    for doc_data in documents:
        doc_id = _doc_id(
            doc_data["course_code"],
            doc_data["assignment_code"],
            doc_data.get("resource_name", ""),
        )
        doc_ref = collection_ref.document(doc_id)

        try:
            existing = doc_ref.get()
            if existing.exists:
                existing_data = existing.to_dict()
                changed = any(existing_data.get(k) != v for k, v in doc_data.items())
                if changed:
                    doc_ref.set(doc_data, merge=True)
                    stats["updated"] += 1
                    print(f"   Updated: {doc_data['course_code']} / {doc_data['assignment_code']} / {doc_data['resource_name'] or '(no resource)'}")
                else:
                    print(f"   No change: {doc_data['course_code']} / {doc_data['assignment_code']} / {doc_data['resource_name'] or '(no resource)'}")
            else:
                doc_ref.set(doc_data)
                stats["inserted"] += 1
                print(f"   Inserted: {doc_data['course_code']} / {doc_data['assignment_code']} / {doc_data['resource_name'] or '(no resource)'}")
        except Exception as e:
            stats["errors"] += 1
            print(f"   Error ({doc_data['assignment_code']}): {e}")

    return stats


def main():
    print("=" * 60)
    print("Uploading Assignment Resources to Firestore")
    print("=" * 60)

    print("\nConnecting to Firestore...")
    try:
        db = init_firestore()
        print(f"Connected to project: {settings.FIREBASE_PROJECT_ID}")
    except Exception as e:
        print(f"Error connecting to Firestore: {e}")
        return

    documents = build_documents()
    print(f"\nPrepared {len(documents)} resource entries to upload\n")

    stats = upload_resources(db, documents)

    print(f"\nDone! Inserted: {stats['inserted']}, Updated: {stats['updated']}, Errors: {stats['errors']}")
    print("=" * 60)
    if stats["errors"] == 0:
        print("\n⚠️  Note: old Firestore entries with the previous CS61A project codes")
        print("   (Project 1/2/3) still exist and should be deleted manually from the")
        print("   Firestore console to avoid duplicate assignment lookups.")


if __name__ == "__main__":
    main()
