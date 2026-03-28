"""
Upload assignment resources to Firestore from Supabase SQL export.

Parses the SQL INSERT statement and uploads each row to the
'assignment_resources' collection. Uses auto-generated document IDs
(matching existing Firestore convention for this collection).

Re-running is safe — duplicates are skipped based on
(course_code, assignment_code, resource_name) composite key.
"""

import sys
from datetime import datetime
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


# Raw data extracted from Supabase SQL export.
# Fields: (id, course_code, assignment_code, assignment_name, resource_type, resource_name, link)
# Rows with null links are excluded.
RESOURCES = [
    ("CS61A", "HW01", "Functions, Control", "Reading", "Section 1.1", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Functions, Control", "Reading", "Section 1.2", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Functions, Control", "Reading", "Section 1.3", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Functions, Control", "Reading", "Section 1.4", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Functions, Control", "Reading", "Section 1.5", "https://www.composingprograms.com/"),
    ("CS61A", "HW01", "Functions, Control", "Video", "Getting Started", "https://www.youtube.com/watch?v=playlist&list=PLx38hZJ5RLZdE6Ugbn03lUj4utfzETMHA"),
    ("CS61A", "HW02", "Higher-Order Functions", "Reading", "Section 1.6", "https://www.composingprograms.com/"),
    ("CS61A", "HW02", "Higher-Order Functions", "Reading", "ok guide", "https://cs61a.org/articles/using-ok/"),
    ("CS61A", "HW03", "Recursion, Tree Recursion", "Reading", "Section 1.7", "https://www.composingprograms.com/"),
    ("CS61A", "HW03", "Recursion, Tree Recursion", "Reading", "ok guide", "https://cs61a.org/articles/using-ok/"),
    ("CS61A", "HW04", "Python Lists, Object-Oriented Programming", "Reading", "Section 2.3", "https://www.composingprograms.com/"),
    ("CS61A", "HW04", "Python Lists, Object-Oriented Programming", "Reading", "Section 2.5", "https://www.composingprograms.com/"),
    ("CS61A", "HW04", "Python Lists, Object-Oriented Programming", "Reading", "ok guide", "https://cs61a.org/articles/using-ok/"),
    ("CS61A", "HW05", "Trees, Linked Lists", "Reading", "Section 4.2", "https://www.composingprograms.com/"),
    ("CS61A", "HW06", "Scheme, Scheme Lists", "Reading", "Scheme Specification", "https://cs61a.vercel.app/articles/scheme-spec/index.html"),
    ("CS61A", "HW06", "Scheme, Scheme Lists", "Reading", "Scheme Built-in Procedure Reference", "https://cs61a.vercel.app/articles/scheme-builtins/index.html"),
    ("CS61A", "HW06", "Scheme, Scheme Lists", "Video", "Getting Started*", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZfnXDXftRu5P0mn_crGWaWd"),
    ("CS61A", "HW07", "Scheme Data Abstractions, Programs as Data", "Reading", "Scheme Specification", "https://cs61a.vercel.app/articles/scheme-spec/index.html"),
    ("CS61A", "HW07", "Scheme Data Abstractions, Programs as Data", "Reading", "Scheme Built-in Procedure Reference", "https://cs61a.vercel.app/articles/scheme-builtins/index.html"),
    ("CS61A", "HW07", "Scheme Data Abstractions, Programs as Data", "Video", "Getting Started*", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZea1rWe3s2JtuCIku_blUu_"),
    ("CS61A", "Project 1", "The Game of Hog", "Reading", "Sections 1.2", "https://www.composingprograms.com/"),
    ("CS61A", "Project 1", "The Game of Hog", "Reading", "Sections 1.3", "https://www.composingprograms.com/"),
    ("CS61A", "Project 1", "The Game of Hog", "Reading", "Sections 1.4", "https://www.composingprograms.com/"),
    ("CS61A", "Project 1", "The Game of Hog", "Reading", "Sections 1.5", "https://www.composingprograms.com/"),
    ("CS61A", "Project 1", "The Game of Hog", "Reading", "Sections 1.6", "https://www.composingprograms.com/"),
    ("CS61A", "Project 1", "The Game of Hog", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZfpHDDcEnevQqlX4wTxuMAD"),
    ("CS61A", "Project 2", "Ants", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZdH1AQFUuP-ixu7nAEK4OLP"),
    ("CS61A", "Project 3", "Scheme", "Video", "Getting Started", "https://www.youtube.com/playlist?list=PLx38hZJ5RLZez4iVyVRr52Eknxs4RF27w"),
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
    Upload resources to Firestore, skipping duplicates.

    Duplicate detection: checks existing docs where
    (course_code, assignment_code, resource_name) all match.
    """
    stats = {"inserted": 0, "skipped": 0, "errors": 0}
    collection_ref = db.collection("assignment_resources")

    # Pre-fetch existing resources to detect duplicates
    print("   Fetching existing resources for dedup...")
    existing = set()
    for doc in collection_ref.stream():
        d = doc.to_dict()
        key = (d.get("course_code"), d.get("assignment_code"), d.get("resource_name"))
        existing.add(key)
    print(f"   Found {len(existing)} existing resource(s)")

    for doc_data in documents:
        key = (doc_data["course_code"], doc_data["assignment_code"], doc_data["resource_name"])

        if key in existing:
            stats["skipped"] += 1
            print(f"   Skipped (exists): {doc_data['course_code']} / {doc_data['assignment_code']} / {doc_data['resource_name']}")
            continue

        try:
            collection_ref.add(doc_data)
            existing.add(key)
            stats["inserted"] += 1
            print(f"   Inserted: {doc_data['course_code']} / {doc_data['assignment_code']} / {doc_data['resource_name']}")
        except Exception as e:
            stats["errors"] += 1
            print(f"   Error: {doc_data['resource_name']}: {e}")

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
    print(f"\nPrepared {len(documents)} resource(s) to upload")

    # Note: 1 row from Supabase had a null link (id=21, "Slides", "Lectures 1-4") and was excluded.
    print("(1 row with null link excluded from migration)\n")

    print("Uploading...\n")
    stats = upload_resources(db, documents)

    print(f"\nDone! Inserted: {stats['inserted']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
