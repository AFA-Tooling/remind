"""Reminder helper: read Firestore data and draft messages."""

from __future__ import annotations

import argparse
import csv
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unicodedata import lookup

import firebase_admin
from firebase_admin import credentials, firestore

# Import shared settings
import sys
from pathlib import Path
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings


DEFAULT_STUDENTS_TABLE = "students"
DEFAULT_RESOURCES_TABLE = "assignment_resources"
DEFAULT_DEADLINES_CSV = "shared_data/deadlines.csv"
DEFAULT_FREQ_FIELD = "days_before_deadline"
DEFAULT_DEADLINES_TABLE = "deadlines"


def mask_secret(secret: str) -> str:
    """Return a masked version of a secret for logging."""

    if not secret:
        return "(empty)"
    if len(secret) <= 8:
        return "***masked***"
    return f"{secret[:4]}...{secret[-4:]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch student data, compute personalized deadlines, and draft reminder "
            "messages using Supabase plus deadlines.csv"
        )
    )
    parser.add_argument(
        "--mode",
        choices=["reminders", "raw"],
        default="reminders",
        help=(
            "reminders: run the full AutoRemind pre-processing pipeline (default). "
            "raw: print rows from --table for quick inspection."
        ),
    )
    parser.add_argument(
        "--table",
        default=os.getenv("FIRESTORE_STUDENTS_COLLECTION", DEFAULT_STUDENTS_TABLE),
        help="Collection to query when --mode=raw (default: students)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for number of rows/students to inspect",
    )
    parser.add_argument(
        "--resources-table",
        default=DEFAULT_RESOURCES_TABLE,
        help="Firestore collection that stores assignment resources",
    )
    parser.add_argument(
        "--deadlines-csv",
        default=DEFAULT_DEADLINES_CSV,
        help="Path to the deadlines CSV (relative to this file)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print verbose diagnostics about fetched data and filtering decisions",
    )
    parser.add_argument(
        "--discord-csv",
        action="store_true",
        help=(
            "If set, also write a CSV of (discord_id,message) for students who "
            "have Discord enabled as a channel."
        ),
    )
    parser.add_argument(
        "--discord-output",
        default="discord_messages.csv",
        help="Output path for the Discord CSV (default: discord_messages.csv)",
    )
    parser.add_argument(
        "--gmail-csv",
        action="store_true",
        help=(
            "If set, also write CSV files for Gmail reminders. Creates one CSV per assignment "
            "in the message_requests directory with columns: name, sid, email, assignment, message_requests"
        ),
    )
    parser.add_argument(
    "--deadlines-table",
    default=DEFAULT_DEADLINES_TABLE,
    help="Firestore collection name containing deadlines (default: deadlines)",
    )
    return parser.parse_args()


def init_firestore() -> firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client."""
    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
    return firestore.client()


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")

def fetch_collection_docs(
    db: firestore.Client,
    collection_name: str,
    limit: Optional[int] = None,
    *,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    query = db.collection(collection_name)
    if limit:
        query = query.limit(limit)

    docs = query.stream()
    rows = [doc.to_dict() for doc in docs]
    debug_print(debug, f"Fetched {len(rows)} docs from '{collection_name}'")
    return rows


def parse_deadline(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


DeadlineMap = Dict[str, Dict[str, Dict[str, datetime]]]


def base_assignment_code(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    match = re.match(r"([A-Za-z]+\d+)", code)
    if match:
        return match.group(1)
    return None
    

def load_deadlines_from_rows(
    deadline_rows: List[Dict[str, Any]], *, debug: bool = False
) -> DeadlineMap:
    deadlines: DeadlineMap = {}

    for raw_row in deadline_rows:
        # Normalize keys/values similarly to CSV version
        course_code = (raw_row.get("course_code") or "").strip()
        assignment_code = (raw_row.get("assignment_code") or "").strip()
        assignment_name = (raw_row.get("assignment_name") or raw_row.get("assignment") or "").strip()
        due_str = raw_row.get("due")

        due_date = parse_deadline(str(due_str) if due_str is not None else "")
        if not due_date:
            continue

        course_deadlines = deadlines.setdefault(course_code, {"code": {}, "name": {}})

        if assignment_code:
            course_deadlines["code"][assignment_code] = due_date
        if assignment_name:
            course_deadlines["name"][assignment_name] = due_date

        scope = course_code or "(default)"
        debug_print(
            debug,
            (
                f"Loaded deadline code='{assignment_code or 'n/a'}' "
                f"name='{assignment_name or 'n/a'}' [{scope}] → {due_date.isoformat(sep=' ')}"
            ),
        )

    return deadlines


def assignment_number_from_code(code: str) -> Optional[int]:
    match = re.search(r"\d+", code or "")
    if not match:
        return None
    return int(match.group())


def _iter_deadline_maps(
    course_code: str,
    deadlines: DeadlineMap,
) -> List[tuple[str, Dict[str, Dict[str, datetime]]]]:
    course_code = course_code or ""
    seen: set[str] = set()
    order: List[tuple[str, Dict[str, datetime]]] = []

    if course_code in deadlines:
        order.append((course_code, deadlines[course_code]))
        seen.add(course_code)

    if "" in deadlines and "" not in seen:
        order.append(("", deadlines[""]))
        seen.add("")

    return order


def find_deadline_for_entry(
    course_code: str,
    assignment_name: Optional[str],
    assignment_code: Optional[str],
    deadlines: DeadlineMap,
    *,
    debug: bool = False,
) -> Optional[datetime]:
    candidates = _iter_deadline_maps(course_code, deadlines)
    if not candidates:
        return None

    if assignment_code:
        search_codes = [assignment_code]
        base_code = base_assignment_code(assignment_code)
        if base_code and base_code not in search_codes:
            search_codes.append(base_code)

        for scope, mapping in candidates:
            by_code = mapping.get("code", {})
            for code_key in search_codes:
                if code_key in by_code:
                    debug_print(
                        debug,
                        (
                            f"Matched deadline for code {code_key} "
                            f"in scope '{scope or 'default'}'"
                        ),
                    )
                    return by_code[code_key]

    # Try exact assignment name match first
    if assignment_name:
        for scope, mapping in candidates:
            by_name = mapping.get("name", {})
            if assignment_name in by_name:
                debug_print(
                    debug,
                    f"Matched deadline for '{assignment_name}' in scope '{scope or 'default'}'",
                )
                return by_name[assignment_name]

    number = assignment_number_from_code(assignment_code or "")
    if number is None:
        return None

    target_phrase = f"Project {number}"
    for scope, mapping in candidates:
        by_name = mapping.get("name", {})
        for name, due in by_name.items():
            if target_phrase in name:
                debug_print(
                    debug,
                    (
                        f"Matched deadline for code {assignment_code} using phrase "
                        f"'{target_phrase}' in scope '{scope or 'default'}'"
                    ),
                )
                return due

    return None


def attach_deadlines_to_resources(
    resources: Dict[str, Dict[str, Dict[str, Any]]],
    deadlines: DeadlineMap,
    *,
    debug: bool = False,
) -> None:
    for course_code, assignments in resources.items():
        for entry in assignments.values():
            matched = find_deadline_for_entry(
                course_code,
                entry.get("assignment_name"),
                entry.get("assignment_code"),
                deadlines,
                debug=debug,
            )
            if matched:
                entry["deadline"] = matched


def build_assignment_lookup(
    resource_rows: List[Dict[str, Any]],
    deadlines: DeadlineMap,
    *,
    debug: bool = False,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for row in resource_rows:
        code = row.get("assignment_code")
        if not code:
            continue
        normalized_code = code.strip()
        course_code = (row.get("course_code") or "").strip()
        course_lookup = lookup.setdefault(course_code, {})
        entry = course_lookup.setdefault(
            normalized_code,
            {
                "assignment_code": normalized_code,
                "assignment_name": row.get("assignment_name") or normalized_code,
                "resources": [],
                "deadline": None,
                "course_code": course_code,
            },
        )

        if row.get("assignment_name"):
            entry["assignment_name"] = row["assignment_name"]

        entry["resources"].append(
            {
                "resource_type": row.get("resource_type"),
                "resource_name": row.get("resource_name"),
                "link": row.get("link"),
            }
        )

        alias_code = base_assignment_code(normalized_code)
        if alias_code and alias_code != normalized_code:
            alias_entry = course_lookup.setdefault(
                alias_code,
                {
                    "assignment_code": alias_code,
                    "assignment_name": entry.get("assignment_name") or alias_code,
                    "resources": [],
                    "deadline": None,
                    "course_code": course_code,
                },
            )

            if row.get("assignment_name") and (
                alias_entry.get("assignment_name") == alias_entry["assignment_code"]
            ):
                alias_entry["assignment_name"] = row["assignment_name"]

            alias_entry["resources"].append(
                {
                    "resource_type": row.get("resource_type"),
                    "resource_name": row.get("resource_name"),
                    "link": row.get("link"),
                }
            )

    attach_deadlines_to_resources(lookup, deadlines, debug=debug)
    total_codes = sum(len(assignments) for assignments in lookup.values())
    debug_print(
        debug,
        f"Built assignment lookup for {total_codes} codes across {len(lookup)} course scopes",
    )
    return lookup


def get_notification_frequency(student: Dict[str, Any], assignment_code: str) -> int:
    """Return student's notification window in days for a given assignment."""

    # Prefer a single-column layout if available (days_before_deadline).
    freq_value = student.get(DEFAULT_FREQ_FIELD)
    if freq_value is not None:
        try:
            return max(int(freq_value), 0)
        except (TypeError, ValueError):
            return 0

    # Fallback: legacy columns notif_freq_1, notif_freq_2, etc.
    freq_keys = sorted(
        (
            key
            for key in student.keys()
            if key.startswith("notif_freq_") and re.search(r"\d+", key)
        ),
        key=lambda key: int(re.search(r"\d+", key).group()),
    )
    freq_values = [int(student[key] or 0) for key in freq_keys]

    if not freq_values:
        return 0

    idx = assignment_number_from_code(assignment_code) or 1
    position = min(max(idx - 1, 0), len(freq_values) - 1)
    return max(freq_values[position], 0)


def determine_channels(student: Dict[str, Any]) -> List[Dict[str, str]]:
    channels: List[Dict[str, str]] = []
    if student.get("phone_pref") and student.get("phone_number"):
        channels.append({"type": "sms", "target": str(student["phone_number"])})
    if student.get("email_pref") and student.get("email"):
        channels.append({"type": "email", "target": str(student["email"])})
    if student.get("discord_pref") and student.get("discord_id"):
        channels.append({"type": "discord", "target": str(student["discord_id"])})
    return channels


# def collect_assignment_codes(student: Dict[str, Any]) -> List[str]:
#     return [key for key in student.keys() if key.upper().startswith("PROJ")]

def collect_assignment_codes(student: Dict[str, Any], assignment_lookup: Dict) -> List[str]:
    all_codes = []
    for course_code in assignment_lookup:
        all_codes.extend(assignment_lookup[course_code].keys())
    return list(set(all_codes))


def compute_personal_deadline(
    base_deadline: Optional[datetime], offset_days: int
) -> Optional[datetime]:
    if not base_deadline:
        return None
    return base_deadline + timedelta(days=offset_days)


def format_due_datetime(dt_value: datetime) -> str:
    return dt_value.strftime("%Y-%m-%d %H:%M")


def build_assignment_payload(
    student: Dict[str, Any],
    code: str,
    lookup: Dict[str, Dict[str, Dict[str, Any]]],
    today: datetime,
    *,
    debug: bool = False,
) -> Optional[Dict[str, Any]]:
    student_email = student.get("email", "unknown")
    student_id = student.get("id", "unknown")
    
    # Enhanced debugging for specific email
    is_target_student = "autoremindberkeley" in str(student_email).lower()
    
    if is_target_student or debug:
        print(f"\n{'='*80}")
        print(f"🔍 DEBUG: Evaluating assignment {code} for student:")
        print(f"   Email: {student_email}")
        print(f"   ID: {student_id}")
        print(f"   Today: {today.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
    
    course_code = (student.get("course_code") or "").strip()
    # course_lookup = lookup.get(course_code)
    # if course_lookup is None and course_code:
    #     course_lookup = lookup.get("")
    # This forces the script to look into the CS10 assignments folder
    course_lookup = lookup.get(course_code) or lookup.get("CS10")

    
    if is_target_student or debug:
        print(f"   Course code: '{course_code}' (empty='{not course_code}')")
        print(f"   Course lookup found: {course_lookup is not None}")
        if course_lookup:
            print(f"   Available assignment codes in lookup: {list(course_lookup.keys())}")

    entry = course_lookup.get(code) if course_lookup else None
    if not entry and course_lookup:
        alias_code = base_assignment_code(code)
        if is_target_student or debug:
            print(f"   Direct lookup for '{code}' failed, trying alias: '{alias_code}'")
        if alias_code:
            entry = course_lookup.get(alias_code)

    if not entry:
        msg = f"No assignment data found for {code} in course '{course_code or 'default'}'"
        if is_target_student or debug:
            print(f"   ❌ {msg}")
        debug_print(debug, msg)
        return None

    if is_target_student or debug:
        print(f"   ✅ Found assignment entry: {entry.get('assignment_name', code)}")
        print(f"   Base deadline from entry: {entry.get('deadline')}")

    offset_raw = student.get(code, 0) or 0
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        offset = 0
    
    if is_target_student or debug:
        print(f"   Student offset for {code}: {offset} days")

    base_deadline = entry.get("deadline")
    personal_deadline = compute_personal_deadline(base_deadline, offset)
    
    if is_target_student or debug:
        print(f"   Base deadline: {base_deadline}")
        print(f"   Personal deadline (base + {offset}): {personal_deadline}")
    
    debug_print(
        debug,
        " | ".join(
            [
                f"Evaluating {code} for student {student.get('id')}",
                f"base={base_deadline}",
                f"offset={offset}",
                f"personal={personal_deadline}",
            ]
        ),
    )
    
    if not personal_deadline:
        msg = f"Skipping {code}: no deadline available"
        if is_target_student or debug:
            print(f"   ❌ {msg}")
        debug_print(debug, msg)
        return None

    freq_days = get_notification_frequency(student, code)
    delta_days = (personal_deadline.date() - today.date()).days
    
    if is_target_student or debug:
        print(f"   Notification frequency (days_before_deadline): {freq_days} days")
        print(f"   Days until deadline (delta_days): {delta_days} days")
        print(f"   Personal deadline date: {personal_deadline.date()}")
        print(f"   Today date: {today.date()}")
    
    debug_print(
        debug,
        f"Student {student.get('id')} {code}: freq={freq_days}d, delta={delta_days}d",
    )

    if delta_days < 0:
        msg = f"Skipping {code}: past due (delta_days={delta_days})"
        if is_target_student or debug:
            print(f"   ❌ {msg}")
        debug_print(debug, msg)
        return None

    # New rule: only send when the diff exactly matches the notification frequency.
    if delta_days != freq_days:
        msg = f"Skipping {code}: delta {delta_days} != freq {freq_days} (EXACT MATCH REQUIRED)"
        if is_target_student or debug:
            print(f"   ❌ {msg}")
            print(f"   💡 To send email, delta_days ({delta_days}) must exactly equal freq_days ({freq_days})")
        debug_print(debug, msg)
        return None

    if is_target_student or debug:
        print(f"   ✅ MATCH! delta_days ({delta_days}) == freq_days ({freq_days})")
        print(f"   ✅ Will send reminder for {code}")

    return {
        "assignment_code": code,
        "assignment_name": entry.get("assignment_name", code),
        "base_deadline": entry.get("deadline"),
        "personal_deadline": personal_deadline,
        "offset_days": offset,
        "notification_window_days": freq_days,
        "resources": entry.get("resources", []),
    }


def compose_message(student: Dict[str, Any], assignments: List[Dict[str, Any]], today: Optional[datetime] = None) -> str:
    if today is None:
        today = datetime.now()
    preferred_name = (
        student.get("preferred_first_name")
        or student.get("first_name")
        or "there"
    )
    lines = [
        f"Hey {preferred_name},",
        "",
        "Heads-up: you have upcoming assignments due soon:",
    ]

    for assignment in assignments:
        due_dt = assignment["personal_deadline"]
        days_until = (due_dt.date() - today.date()).days
        due_date_str = due_dt.strftime("%B %-d")
        if days_until == 0:
            days_label = "due today"
        elif days_until == 1:
            days_label = "due in 1 day"
        else:
            days_label = f"due in {days_until} days"
        lines.append(
            f"- {assignment['assignment_name']} ({assignment['assignment_code']}) → {days_label}, on {due_date_str}"
        )
        if assignment["offset_days"]:
            lines.append(
                f"  (Class deadline +{assignment['offset_days']} day offset for you.)"
            )

        resources = [res for res in assignment.get("resources", []) if res.get("resource_name")]
        if resources:
            lines.append("  Helpful resources:")
            for res in resources:
                resource_line = f"    • {res.get('resource_name')}"
                if res.get("resource_type"):
                    resource_line += f" [{res['resource_type']}]"
                if res.get("link"):
                    resource_line += f": {res['link']}"
                lines.append(resource_line)

    lines.append("")
    lines.append("Let us know if you need any support!")
    return "\n".join(lines)


def write_discord_csv(reminders: List[Dict[str, Any]], output_path: Path) -> None:
    """Write a CSV with columns discord_id,message for entries with Discord channel."""
    rows: List[Dict[str, str]] = []

    for entry in reminders:
        # Find the Discord channel for this student, if any
        discord_channel = next(
            (ch for ch in entry.get("channels", []) if ch.get("type") == "discord"),
            None,
        )
        if not discord_channel:
            continue

        discord_id = str(discord_channel.get("target", "")).strip()
        if not discord_id:
            continue

        rows.append(
            {
                "discord_id": discord_id,
                "message": entry.get("message", ""),
            }
        )

    # Always overwrite the file, even if there are no rows
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["discord_id", "message"])
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        print(f"✅ Wrote {len(rows)} Discord messages to {output_path}")
    else:
        print(f"✅ No students with Discord reminders. Wrote empty CSV to {output_path}")


def _safe_filename_basic(name: str) -> str:
    """
    Return a Windows-safe filename by replacing ':' and runs of '*' with ' - ', etc
    """
    cleaned = name.replace(":", " - ")
    cleaned = re.sub(r'\*+', ' - ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().rstrip(' .')
    return cleaned


def write_gmail_csv(reminders: List[Dict[str, Any]], output_dir: Path) -> None:
    """
    Write Gmail-compatible CSV files grouped by assignment.
    Creates one CSV file per assignment in the output directory.
    CSV format: name,sid,email,assignment,message_requests
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    assignment_rows: Dict[str, List[Dict[str, str]]] = {}
    total_rows = 0

    for entry in reminders:
        # Find the email channel for this student, if any
        email_channel = next(
            (ch for ch in entry.get("channels", []) if ch.get("type") == "email"),
            None,
        )
        if not email_channel:
            continue

        email = str(email_channel.get("target", "")).strip()
        if not email:
            continue

        student_data = entry.get("student", {})
        student_name = student_data.get("name", "").strip()
        student_id = student_data.get("id")
        
        # Get SID from student data
        sid = student_data.get("sid", "")
        if not sid and student_id:
            sid = str(student_id)

        # Create a row for each assignment
        assignments = entry.get("assignments", [])
        for assignment in assignments:
            assignment_name = assignment.get("assignment_name", "Assignment")
            assignment_code = assignment.get("assignment_code", "")
            
            # Use assignment_name as the key, fallback to assignment_code
            assignment_key = assignment_name or assignment_code
            
            # Create a per-assignment message
            # Use preferred_first_name if available, otherwise use first name from student_name
            preferred_first_name = student_data.get("preferred_first_name")
            if preferred_first_name and str(preferred_first_name).strip():
                preferred_name = str(preferred_first_name).strip()
            elif student_name:
                preferred_name = student_name.split()[0] if student_name else "there"
            else:
                preferred_name = "there"
            
            due_text = format_due_datetime(assignment["personal_deadline"]) if assignment.get("personal_deadline") else "soon"
            
            message = f"Dear {preferred_name}, your {assignment_name} assignment is missing and it is due in {due_text}. Please submit it as soon as possible."
            
            if assignment_key not in assignment_rows:
                assignment_rows[assignment_key] = []
            
            assignment_rows[assignment_key].append({
                "name": student_name,
                "sid": sid,
                "email": email,
                "assignment": assignment_name,
                "message_requests": message,
            })

    for assignment_key, rows in assignment_rows.items():
        safe_assignment_title = _safe_filename_basic(assignment_key)
        csv_file_name = f"message_requests_{safe_assignment_title}.csv"
        output_path = output_dir / csv_file_name

        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["name", "sid", "email", "assignment", "message_requests"]
            )
            writer.writeheader()
            writer.writerows(rows)

        total_rows += len(rows)
        print(f"✅ Wrote {len(rows)} Gmail reminders for '{assignment_key}' to {output_path}")

    if total_rows == 0:
        print(f"✅ No students with email reminders. No Gmail CSV files created.")
    else:
        print(f"✅ Total: Wrote {total_rows} Gmail reminder rows across {len(assignment_rows)} assignment file(s)")


def build_submission_lookup(submission_rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build a lookup of (email, assignment_name) -> status from assignment_submissions."""
    lookup: Dict[str, str] = {}
    for row in submission_rows:
        email = (row.get("email") or "").strip().lower()
        assignment_name = (row.get("assignment_name") or "").strip()
        status = (row.get("status") or "").strip()
        if email and assignment_name:
            lookup[(email, assignment_name)] = status
    return lookup


def is_missing_submission(
    student_email: str,
    assignment_name: str,
    submission_lookup: Dict[str, str],
) -> bool:
    """Return True if the student has not submitted the assignment."""
    key = (student_email.strip().lower(), assignment_name.strip())
    status = submission_lookup.get(key)
    # Not in spreadsheet at all — not a student in the class, don't notify
    if status is None:
        return False
    # A timestamp means submitted; "missing" means not submitted
    return status.strip().lower() == "missing"


def gather_reminders(
    db: firestore.Client,
    args: argparse.Namespace,
) -> List[Dict[str, Any]]:
    deadline_rows = fetch_collection_docs(db, args.deadlines_table, debug=args.debug)
    deadlines = load_deadlines_from_rows(deadline_rows, debug=args.debug)
    resource_rows = fetch_collection_docs(
        db,
        args.resources_table,
        debug=args.debug,
    )
    assignment_lookup = build_assignment_lookup(
        resource_rows,
        deadlines,
        debug=args.debug,
    )

    submission_rows = fetch_collection_docs(db, "assignment_submissions", debug=args.debug)
    submission_lookup = build_submission_lookup(submission_rows)

    students = fetch_collection_docs(
        db,
        DEFAULT_STUDENTS_TABLE,
        limit=args.limit,
        debug=args.debug,
    )
    today = datetime.now()

    # Debug: Check if target student is in the list
    target_email = "autoremindberkeley@gmail.com"
    target_found = False
    for student in students:
        if target_email.lower() in str(student.get("email", "")).lower():
            target_found = True
            print(f"\n{'='*80}")
            print(f"🎯 FOUND TARGET STUDENT: {student.get('email')}")
            print(f"   Student ID: {student.get('id')}")
            print(f"   Name: {student.get('first_name')} {student.get('last_name')}")
            print(f"   email_pref: {student.get('email_pref')}")
            print(f"   days_before_deadline: {student.get('days_before_deadline')}")
            print(f"   course_code: {student.get('course_code')}")
            print(f"   Assignment codes in student record: {[k for k in student.keys() if k.upper().startswith('PROJ')]}")
            print(f"   Note: All students in table are considered opted-in")
            print(f"{'='*80}\n")
            break
    
    if not target_found:
        print(f"\n⚠️  WARNING: Target student '{target_email}' NOT FOUND in {DEFAULT_STUDENTS_TABLE} table!")
        print(f"   Total students loaded: {len(students)}")
        if students:
            print(f"   Sample emails: {[s.get('email') for s in students[:5]]}")

    reminders: List[Dict[str, Any]] = []
    for student in students:
        student_email = student.get("email", "")
        is_target = target_email.lower() in str(student_email).lower()
        
        if is_target or args.debug:
            print(f"\n{'='*80}")
            print(f"📋 Processing student: {student_email}")
            print(f"   email_pref: {student.get('email_pref')}")
            print(f"   days_before_deadline: {student.get('days_before_deadline')}")
            print(f"   Note: All students in table are considered opted-in")

        assignments_to_notify: List[Dict[str, Any]] = []
        #assignment_codes = collect_assignment_codes(student)
        assignment_codes = collect_assignment_codes(student, assignment_lookup)
        
        if is_target or args.debug:
            print(f"   Assignment codes found: {assignment_codes}")
        
        for code in assignment_codes:
            payload = build_assignment_payload(
                student,
                code,
                assignment_lookup,
                today,
                debug=args.debug or is_target,  # Always debug for target student
            )
            if payload:
                assignment_name = payload["assignment_name"]
                if not is_missing_submission(student_email, assignment_name, submission_lookup):
                    if is_target or args.debug:
                        print(f"   ⏭️  Skipping {code}: already submitted")
                    continue
                assignments_to_notify.append(payload)
                if is_target or args.debug:
                    print(f"   ✅ Added assignment to notify: {code}")

        if not assignments_to_notify:
            if is_target or args.debug:
                print(f"   ❌ No assignments matched notification window criteria")
            continue

        channels = determine_channels(student)
        if is_target or args.debug:
            print(f"   Channels determined: {channels}")
        
        if not channels:
            channels = [{"type": "none", "target": "(no opted-in channels)"}]
            if is_target or args.debug:
                print(f"   ⚠️  WARNING: No channels found! Student won't receive reminders.")

        message = compose_message(student, assignments_to_notify, today=today)

        reminders.append(
            {
                "student": {
                    "id": student.get("id"),
                    "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
                    "preferred_first_name": student.get("preferred_first_name"),
                    "email": student.get("email"),
                    "sid": student.get("sid"),
                },
                "channels": channels,
                "assignments": assignments_to_notify,
                "message": message,
            }
        )
        
        if is_target:
            print(f"   ✅ REMINDER CREATED for {student_email}")
            print(f"   Assignments: {[a['assignment_name'] for a in assignments_to_notify]}")
            print(f"   Channels: {[c['type'] for c in channels]}")

    return reminders


def run_raw_mode(db: firestore.Client, args: argparse.Namespace) -> None:
    print(f"Fetching data from collection '{args.table}'")
    rows = fetch_collection_docs(
        db,
        args.table,
        args.limit,
        debug=args.debug,
    )
    print(f"Retrieved {len(rows)} docs.")
    for idx, row in enumerate(rows, start=1):
        print(f"Doc {idx}: {row}")


def run_reminder_mode(db: firestore.Client, args: argparse.Namespace) -> None:
    reminders = gather_reminders(db, args)

    if not reminders:
        print("✅ No students currently fall within their notification windows.")
    else: 
        for entry in reminders:
            student_name = entry["student"]["name"] or f"Student #{entry['student']['id']}"
            print("\n" + "=" * 60)
            print(f"Reminder for: {student_name}")
            print("Channels:")
            for channel in entry["channels"]:
                print(f"  - {channel['type']}: {channel['target']}")
            print("Assignments:")
            for assignment in entry["assignments"]:
                due_text = format_due_datetime(assignment["personal_deadline"])
                offset_note = (
                    f" (offset +{assignment['offset_days']}d)" if assignment["offset_days"] else ""
                )
                print(
                    f"  • {assignment['assignment_name']} [{assignment['assignment_code']}] → {due_text}{offset_note}"
                )
            print("\nDraft message:\n")
            print(entry["message"])
        print(f"\nSummary: {len(reminders)} students ready for reminders.")

    # Write Discord CSV into discord_service/message_requests if requested
    if args.discord_csv:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        base_dir = project_root / "discord_service" / "message_requests"
        base_dir.mkdir(parents=True, exist_ok=True)

        output_path = base_dir / args.discord_output
        write_discord_csv(reminders, output_path)

    # Write Gmail CSV into gradesync_input/message_requests if requested
    if args.gmail_csv:
        script_dir = Path(__file__).resolve().parent
        output_dir = script_dir / "message_requests"
        write_gmail_csv(reminders, output_dir)


def main() -> None:
    args = parse_args()

    print("Connecting to Firestore...")
    print(f"Firebase Project ID: {settings.FIREBASE_PROJECT_ID}")
    print(f"Service account: {settings.FIREBASE_SERVICE_ACCOUNT_PATH}")

    db = init_firestore()

    if args.mode == "raw":
        run_raw_mode(db, args)
    else:
        run_reminder_mode(db, args)


if __name__ == "__main__":
    main()
