"""Reminder helper: read Firestore data and draft messages."""

from __future__ import annotations

import argparse
import csv
import os
import re
from datetime import datetime, timedelta, date as date_type
from pathlib import Path
from typing import Any, Dict, List, Optional
from unicodedata import lookup
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore

# Import shared settings
import sys
from pathlib import Path
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings


# Berkeley-local time. Naive datetimes (manually-uploaded CSV deadlines) are
# interpreted as already being in this zone; tz-aware ones (Canvas, Z-UTC) are
# converted to it before any date comparison.
PROJECT_TZ = ZoneInfo("America/Los_Angeles")


def local_today() -> date_type:
    return datetime.now(PROJECT_TZ).date()


def local_date(dt: datetime) -> date_type:
    if dt.tzinfo is not None:
        dt = dt.astimezone(PROJECT_TZ)
    return dt.date()


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
        "--sms-csv",
        action="store_true",
        help=(
            "If set, also write a CSV of (phone_number,text_message) for students who "
            "have SMS enabled as a channel."
        ),
    )
    parser.add_argument(
        "--sms-output",
        default="sms_messages.csv",
        help="Output path for the SMS CSV (default: sms_messages.csv)",
    )
    parser.add_argument(
        "--gmail-csv",
        action="store_true",
        help=(
            "If set, also write a Gmail reminder CSV (message_requests.csv) with one "
            "row per student in the message_requests directory with columns: "
            "name, sid, email, assignment, message_requests"
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


STUDY_PARTICIPANTS_TABLE = "study_participants"
STUDY_CONFIG_TABLE = "study_config"
STUDY_CONFIG_DOC = "state"


def load_study_access(db: firestore.Client, *, debug: bool = False) -> set:
    """Return the set of lowercased emails allowed to receive notifications.

    Research-study gating: a consented student has access iff their group is 1, OR
    access has been opened to everyone (study_config/state.access_open == True).
    Group 2 (waitlisted) and unassigned students are excluded until access opens.

    Fails CLOSED — if the study collections cannot be read we raise rather than
    risk notifying students who should be gated out.
    """
    try:
        config_snap = db.collection(STUDY_CONFIG_TABLE).document(STUDY_CONFIG_DOC).get()
        access_open = bool(config_snap.to_dict().get("access_open")) if config_snap.exists else False

        access_emails = set()
        total = group1 = group2 = unassigned = 0
        for doc in db.collection(STUDY_PARTICIPANTS_TABLE).stream():
            data = doc.to_dict() or {}
            email = str(data.get("email") or doc.id).strip().lower()
            if not email:
                continue
            total += 1
            group = data.get("group")
            if group == 1:
                group1 += 1
            elif group == 2:
                group2 += 1
            else:
                unassigned += 1
            if group == 1 or access_open:
                access_emails.add(email)
    except Exception as exc:  # noqa: BLE001 — fail closed on any read error
        raise RuntimeError(
            f"Aborting reminder run: could not load study gating data ({exc!r}). "
            "Refusing to send notifications without an enforceable allowlist."
        ) from exc

    print(
        f"🔒 Study gate: {len(access_emails)} of {total} consented students have access "
        f"(group1={group1}, group2={group2}, unassigned={unassigned}, access_open={access_open})"
    )
    return access_emails


def parse_deadline(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        print(f"⚠️  parse_deadline: unparseable value {value!r}, skipping")
        return None


# A deadline record carries both dates for one assignment. `due` is always present;
# `release` is None when the assignment has no release date of its own (e.g. project
# checkpoints, which ship with the parent project's handout).
DeadlineRecord = Dict[str, Optional[datetime]]
DeadlineMap = Dict[str, Dict[str, Dict[str, DeadlineRecord]]]


def base_assignment_code(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    match = re.match(r"([A-Za-z]+\d+)", code)
    if match:
        return match.group(1)
    return None


def derive_assignment_category(*candidates: Optional[str]) -> str:
    """
    Map an assignment label to one of: Lab, Homework, Midterm, Quiz, Project.

    Tries each candidate string (assignment name first, then code) and returns
    the first match. Falls back to Project so non-matching CS61A assignments
    still get a defined category.
    """
    for raw in candidates:
        if not raw:
            continue
        name = str(raw).strip().lower()
        if name.startswith("lab"):
            return "Lab"
        if name.startswith("homework") or name.startswith("hw"):
            return "Homework"
        if name.startswith("midterm"):
            return "Midterm"
        # Substring (not prefix) so "Orientation Quiz (Optional)" is caught
        # alongside the numbered "Quiz 1".."Quiz 5".
        if "quiz" in name:
            return "Quiz"
    return "Project"
    

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
        release_str = raw_row.get("release")

        due_date = parse_deadline(str(due_str) if due_str is not None else "")
        if not due_date:
            continue

        release_date = parse_deadline(str(release_str) if release_str is not None else "")
        record: DeadlineRecord = {"due": due_date, "release": release_date}

        course_deadlines = deadlines.setdefault(course_code, {"code": {}, "name": {}})

        if assignment_code:
            course_deadlines["code"][assignment_code] = record
        if assignment_name:
            course_deadlines["name"][assignment_name] = record

        scope = course_code or "(default)"
        release_note = release_date.date().isoformat() if release_date else "none"
        debug_print(
            debug,
            (
                f"Loaded deadline code='{assignment_code or 'n/a'}' "
                f"name='{assignment_name or 'n/a'}' [{scope}] → {due_date.isoformat(sep=' ')} "
                f"(release: {release_note})"
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
) -> Optional[DeadlineRecord]:
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
        for name, record in by_name.items():
            if target_phrase in name:
                debug_print(
                    debug,
                    (
                        f"Matched deadline for code {assignment_code} using phrase "
                        f"'{target_phrase}' in scope '{scope or 'default'}'"
                    ),
                )
                return record

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
                entry["deadline"] = matched["due"]
                entry["release"] = matched.get("release")


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
                "release": None,
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
                    "release": None,
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

    # Category gate — roster-enrolled students can opt out of categories.
    # Students without category_prefs (non-roster) get legacy behavior (all on).
    category_prefs = student.get("category_prefs")
    if isinstance(category_prefs, dict):
        category = derive_assignment_category(entry.get("assignment_name"), code)
        if not category_prefs.get(category.lower(), True):
            msg = f"Skipping {code}: category '{category}' disabled in student prefs"
            if is_target_student or debug:
                print(f"   ❌ {msg}")
            debug_print(debug, msg)
            return None

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

    # Project early-reminder shift: roster students can opt to be reminded a day
    # earlier for projects, since submitting a project a day early earns extra
    # credit. We only shift the date used to decide *whether* to send; the payload
    # (and message) still surfaces the real personal deadline.
    effective_deadline = personal_deadline
    if student.get("project_early_reminder"):
        category = derive_assignment_category(entry.get("assignment_name"), code)
        # Checkpoints (e.g. "Hog Checkpoint") are graded on their own deadline and
        # earn no extra credit for early submission, so the day-early shift must not
        # apply to them even though they fall under the Project category.
        label = f"{entry.get('assignment_name') or ''} {code or ''}".lower()
        is_checkpoint = "checkpoint" in label
        if category == "Project" and not is_checkpoint:
            effective_deadline = personal_deadline - timedelta(days=1)
            if is_target_student or debug:
                print(f"   📌 Project early-reminder ON for {code}: effective deadline shifted back 1 day")

    freq_days = get_notification_frequency(student, code)
    deadline_local = local_date(effective_deadline)
    today_local = today.date() if today.tzinfo is None else today.astimezone(PROJECT_TZ).date()
    delta_days = (deadline_local - today_local).days

    if is_target_student or debug:
        print(f"   Notification frequency (days_before_deadline): {freq_days} days")
        print(f"   Days until deadline (delta_days): {delta_days} days")
        print(f"   Personal deadline date (local): {deadline_local}")
        print(f"   Today date (local): {today_local}")
    
    debug_print(
        debug,
        f"Student {student.get('id')} {code}: freq={freq_days}d, delta={delta_days}d",
    )

    # Two independent reasons an assignment can fire. The due match is the original
    # rule: an exact match on the notification frequency, against the (possibly
    # early-reminder-shifted) deadline. The release match is an OR against a
    # different date entirely, so it cannot be folded into the chain above.
    due_match = delta_days >= 0 and delta_days == freq_days

    release_dt = entry.get("release")
    release_match = bool(
        student.get("release_reminder")
        and release_dt
        and local_date(release_dt) == today_local
    )

    if not due_match and not release_match:
        if delta_days < 0:
            msg = f"Skipping {code}: past due (delta_days={delta_days})"
        else:
            msg = f"Skipping {code}: delta {delta_days} != freq {freq_days} and not release day"
        if is_target_student or debug:
            print(f"   ❌ {msg}")
        debug_print(debug, msg)
        return None

    # Same-day collision: an assignment can be released today and hit its due match
    # today. The due line is more actionable and implies the assignment is out, so
    # it wins and the assignment is listed once.
    reason = "due" if due_match else "release"

    if is_target_student or debug:
        print(f"   ✅ MATCH ({reason})! Will send reminder for {code}")

    return {
        "assignment_code": code,
        "assignment_name": entry.get("assignment_name", code),
        "base_deadline": entry.get("deadline"),
        "personal_deadline": personal_deadline,
        "offset_days": offset,
        "notification_window_days": freq_days,
        "resources": entry.get("resources", []),
        "reason": reason,
    }


def _render_resources(lines: List[str], assignment: Dict[str, Any]) -> None:
    """Append an assignment's resource links to `lines`, if it has any."""
    resources = [res for res in assignment.get("resources", []) if res.get("resource_name")]
    if not resources:
        return
    lines.append("  Helpful resources:")
    for res in resources:
        resource_line = f"    • {res.get('resource_name')}"
        if res.get("resource_type"):
            resource_line += f" [{res['resource_type']}]"
        if res.get("link"):
            resource_line += f": {res['link']}"
        lines.append(resource_line)


def _render_assignment_bullet(lines: List[str], assignment: Dict[str, Any], bullet: str, label: str) -> None:
    """Append one assignment's bullet line plus its offset-day note and resources.

    `label` is the section-specific text after the "→" (a countdown for due
    reminders, a bare due date for release reminders); everything else about
    an assignment's rendering is identical between the two sections.
    """
    lines.append(
        f"{bullet} {assignment['assignment_name']} ({assignment['assignment_code']}) → {label}"
    )
    if assignment.get("offset_days"):
        lines.append(
            f"  (Class deadline +{assignment['offset_days']} day offset for you.)"
        )
    _render_resources(lines, assignment)


def compose_message(student: Dict[str, Any], assignments: List[Dict[str, Any]], today: Optional[datetime] = None) -> str:
    if today is None:
        today = datetime.now(PROJECT_TZ)
    today_local = today.date() if today.tzinfo is None else today.astimezone(PROJECT_TZ).date()
    preferred_name = (
        student.get("preferred_first_name")
        or student.get("first_name")
        or "there"
    )

    renderable = [a for a in assignments if a.get("personal_deadline")]
    # A payload with no reason is a due reminder — Canvas-sourced payloads never set one.
    released = [a for a in renderable if a.get("reason") == "release"]
    due_soon = [a for a in renderable if a.get("reason", "due") != "release"]

    number_assignments = len(renderable) > 1
    bullet_index = 0

    def next_bullet() -> str:
        nonlocal bullet_index
        bullet_index += 1
        return f"{bullet_index}." if number_assignments else "-"

    lines = [f"Hey {preferred_name},", ""]

    if released:
        lines.append("Just released: these assignments are now out:")
        for assignment in released:
            due_dt = assignment["personal_deadline"]
            due_date_str = f"{due_dt.strftime('%B')} {due_dt.day}"
            _render_assignment_bullet(lines, assignment, next_bullet(), f"due on {due_date_str}")

    if due_soon:
        if released:
            lines.append("")
        lines.append("Heads-up: you have upcoming assignments due soon:")
        for assignment in due_soon:
            due_dt = assignment["personal_deadline"]
            deadline_local = local_date(due_dt)
            days_until = (deadline_local - today_local).days
            due_date_str = f"{due_dt.strftime('%B')} {due_dt.day}"
            if days_until == 0:
                days_label = "due today"
            elif days_until == 1:
                days_label = "due in 1 day"
            else:
                days_label = f"due in {days_until} days"
            _render_assignment_bullet(lines, assignment, next_bullet(), f"{days_label}, on {due_date_str}")

    lines.append("")
    lines.append("Feel free to reach out to course staff if you need any support!")
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


def write_sms_csv(reminders: List[Dict[str, Any]], output_path: Path) -> None:
    """Write a CSV with columns phone_number,text_message for entries with SMS channel."""
    rows: List[Dict[str, str]] = []

    for entry in reminders:
        sms_channel = next(
            (ch for ch in entry.get("channels", []) if ch.get("type") == "sms"),
            None,
        )
        if not sms_channel:
            continue

        phone_number = str(sms_channel.get("target", "")).strip()
        if not phone_number:
            continue

        rows.append({
            "phone_number": phone_number,
            "text_message": entry.get("message", ""),
        })

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["phone_number", "text_message"])
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        print(f"✅ Wrote {len(rows)} SMS messages to {output_path}")
    else:
        print(f"✅ No students with SMS reminders. Wrote empty CSV to {output_path}")


def _safe_filename_basic(name: str) -> str:
    """
    Return a filename safe across Windows/POSIX by replacing reserved characters
    (including path separators '/' and '\\') with ' - '.
    """
    cleaned = re.sub(r'[\\/:*?"<>|]+', ' - ', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().rstrip(' .')
    return cleaned


def write_gmail_csv(reminders: List[Dict[str, Any]], output_dir: Path) -> None:
    """
    Write a single Gmail-compatible CSV with one row per student.

    Every assignment due for a student is compacted into one combined message
    (the same message used for Discord/SMS), so a student with multiple
    deadlines receives a single email rather than one email per assignment.
    CSV format: name,sid,email,assignment,message_requests
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale per-assignment CSVs from the previous (one-file-per-assignment)
    # format so the email service doesn't re-send outdated messages.
    for stale in output_dir.glob("message_requests_*.csv"):
        try:
            stale.unlink()
        except OSError:
            pass

    rows: List[Dict[str, str]] = []

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

        assignments = entry.get("assignments", [])
        if not assignments:
            continue

        student_data = entry.get("student", {})
        student_name = student_data.get("name", "").strip()
        student_id = student_data.get("id")

        # Get SID from student data
        sid = student_data.get("sid", "")
        if not sid and student_id:
            sid = str(student_id)

        # Summarize assignment names for the 'assignment' column. This drives the
        # subject line / logging only; the body comes from message_requests.
        assignment_names = [
            a.get("assignment_name") or a.get("assignment_code", "")
            for a in assignments
            if a.get("assignment_name") or a.get("assignment_code")
        ]
        assignment_summary = ", ".join(assignment_names) if assignment_names else "your assignments"

        rows.append({
            "name": student_name,
            "sid": sid,
            "email": email,
            "assignment": assignment_summary,
            # Combined, already-composed message covering all due assignments.
            "message_requests": entry.get("message", ""),
        })

    output_path = output_dir / "message_requests.csv"
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["name", "sid", "email", "assignment", "message_requests"]
        )
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        print(f"✅ Wrote {len(rows)} Gmail reminders (one per student) to {output_path}")
    else:
        print(f"✅ No students with email reminders. Wrote empty CSV to {output_path}")


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
    today = datetime.now(PROJECT_TZ)

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
        try:
            reminder = _build_reminder_for_student(
                student, assignment_lookup, submission_lookup, today, target_email, args
            )
        except Exception as exc:
            print(f"⚠️  Skipping student {student.get('email', student.get('id', 'unknown'))}: {exc!r}")
            continue
        if reminder:
            reminders.append(reminder)

    return reminders


def apply_study_gate(
    db: firestore.Client,
    reminders: List[Dict[str, Any]],
    *,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """Drop any reminder for a student without research-study access.

    Single choke point for ALL reminder sources (gradesync + Canvas). Every channel
    (email/SMS/Discord) is fed from these reminders, so gating here gates them all.
    THIS IS THE CRITICAL INVARIANT: only Group 1 (or everyone once access is opened)
    may receive notifications.
    """
    access_emails = load_study_access(db, debug=debug)
    allowed: List[Dict[str, Any]] = []
    gated_out = 0
    for entry in reminders:
        email = str((entry.get("student") or {}).get("email") or "").strip().lower()
        if email in access_emails:
            allowed.append(entry)
        else:
            gated_out += 1
    if gated_out:
        print(f"🔒 Study gate: removed {gated_out} reminder(s) for students without study access.")
    return allowed


def _build_reminder_for_student(
    student: Dict[str, Any],
    assignment_lookup: Dict[str, Dict[str, Dict[str, Any]]],
    submission_lookup: Dict[Any, str],
    today: datetime,
    target_email: str,
    args: argparse.Namespace,
) -> Optional[Dict[str, Any]]:
    student_email = student.get("email", "")
    is_target = target_email.lower() in str(student_email).lower()

    if is_target or args.debug:
        print(f"\n{'='*80}")
        print(f"📋 Processing student: {student_email}")
        print(f"   email_pref: {student.get('email_pref')}")
        print(f"   days_before_deadline: {student.get('days_before_deadline')}")
        print(f"   Note: All students in table are considered opted-in")

    assignments_to_notify: List[Dict[str, Any]] = []
    assignment_codes = collect_assignment_codes(student, assignment_lookup)

    if is_target or args.debug:
        print(f"   Assignment codes found: {assignment_codes}")

    for code in assignment_codes:
        payload = build_assignment_payload(
            student,
            code,
            assignment_lookup,
            today,
            debug=args.debug or is_target,
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
        return None

    channels = determine_channels(student)
    if is_target or args.debug:
        print(f"   Channels determined: {channels}")

    if not channels:
        channels = [{"type": "none", "target": "(no opted-in channels)"}]
        if is_target or args.debug:
            print(f"   ⚠️  WARNING: No channels found! Student won't receive reminders.")

    message = compose_message(student, assignments_to_notify, today=today)

    if is_target:
        print(f"   ✅ REMINDER CREATED for {student_email}")
        print(f"   Assignments: {[a['assignment_name'] for a in assignments_to_notify]}")
        print(f"   Channels: {[c['type'] for c in channels]}")

    return {
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


def gather_canvas_reminders(
    db: firestore.Client,
    args: argparse.Namespace,
) -> List[Dict[str, Any]]:
    """Gather reminders from Canvas-sourced deadlines for connected students."""

    # Get all students with Canvas connected
    students = fetch_collection_docs(db, DEFAULT_STUDENTS_TABLE, limit=args.limit, debug=args.debug)
    canvas_students = [s for s in students if s.get("canvas_connected")]

    if not canvas_students:
        debug_print(args.debug, "No Canvas-connected students found.")
        return []

    today = datetime.now(PROJECT_TZ)
    today_local = today.date()
    reminders: List[Dict[str, Any]] = []

    for student in canvas_students:
        try:
            reminder = _build_canvas_reminder_for_student(db, student, today, today_local, args)
        except Exception as exc:
            print(f"⚠️  Canvas: skipping student {student.get('email', student.get('id', 'unknown'))}: {exc!r}")
            continue
        if reminder:
            reminders.append(reminder)

    if reminders:
        print(f"Canvas: {len(reminders)} students ready for reminders.")
    else:
        print("Canvas: No students currently fall within their notification windows.")

    return reminders


def _build_canvas_reminder_for_student(
    db: firestore.Client,
    student: Dict[str, Any],
    today: datetime,
    today_local: date_type,
    args: argparse.Namespace,
) -> Optional[Dict[str, Any]]:
    student_email = (student.get("email") or "").strip().lower()
    if not student_email:
        return None

    canvas_docs = db.collection("canvas_deadlines").where(
        "email", "==", student_email
    ).stream()
    canvas_deadlines = [doc.to_dict() for doc in canvas_docs]

    if not canvas_deadlines:
        debug_print(args.debug, f"No Canvas deadlines for {student_email}")
        return None

    freq_days = 0
    freq_value = student.get(DEFAULT_FREQ_FIELD)
    if freq_value is not None:
        try:
            freq_days = max(int(freq_value), 0)
        except (TypeError, ValueError):
            freq_days = 0

    assignments_to_notify: List[Dict[str, Any]] = []

    for dl in canvas_deadlines:
        submission_state = dl.get("submission_state", "unsubmitted")
        if submission_state in ("submitted", "graded"):
            continue

        due_str = dl.get("due")
        if not due_str:
            continue

        due_date = parse_deadline(due_str)
        if not due_date:
            continue

        delta_days = (local_date(due_date) - today_local).days

        if delta_days < 0:
            continue

        if delta_days != freq_days:
            debug_print(
                args.debug,
                f"Canvas skip {dl.get('assignment_name')}: delta {delta_days} != freq {freq_days}",
            )
            continue

        assignments_to_notify.append({
            "assignment_code": dl.get("course_code", ""),
            "assignment_name": dl.get("assignment_name", ""),
            "base_deadline": due_date,
            "personal_deadline": due_date,
            "offset_days": 0,
            "notification_window_days": freq_days,
            "resources": [],
            "html_url": dl.get("html_url", ""),
            "source": "canvas",
        })

    if not assignments_to_notify:
        return None

    channels = determine_channels(student)
    if not channels:
        return None

    message = compose_message(student, assignments_to_notify, today=today)

    return {
        "student": {
            "id": student.get("id"),
            "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
            "preferred_first_name": student.get("preferred_first_name"),
            "email": student_email,
            "sid": student.get("sid"),
        },
        "channels": channels,
        "assignments": assignments_to_notify,
        "message": message,
    }


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


def _assignment_signature(assignment: Dict[str, Any]) -> tuple:
    """Stable identity for an assignment, used to dedupe across sources."""
    deadline = assignment.get("personal_deadline")
    return (
        assignment.get("assignment_code"),
        assignment.get("assignment_name"),
        deadline.isoformat() if hasattr(deadline, "isoformat") else deadline,
    )


def merge_reminders_by_student(reminders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse multiple reminder entries for the same student into one.

    Reminders can originate from more than one source (gradesync deadlines and
    Canvas deadlines). Without merging, a student with deadlines from both
    sources receives two separate messages on every channel. This unions their
    assignments and channels (deduping each) and recomposes a single message
    covering all of the student's due assignments.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for entry in reminders:
        email = str((entry.get("student") or {}).get("email") or "").strip().lower()
        # Keep students without an email as distinct entries rather than
        # collapsing them together.
        key = email or f"__noemail__{len(order)}"

        if key not in merged:
            merged[key] = {
                "student": dict(entry.get("student", {})),
                "channels": list(entry.get("channels", [])),
                "assignments": list(entry.get("assignments", [])),
            }
            order.append(key)
            continue

        existing = merged[key]

        seen_channels = {(c.get("type"), c.get("target")) for c in existing["channels"]}
        for channel in entry.get("channels", []):
            sig = (channel.get("type"), channel.get("target"))
            if sig not in seen_channels:
                existing["channels"].append(channel)
                seen_channels.add(sig)

        seen_assignments = {_assignment_signature(a) for a in existing["assignments"]}
        for assignment in entry.get("assignments", []):
            sig = _assignment_signature(assignment)
            if sig not in seen_assignments:
                existing["assignments"].append(assignment)
                seen_assignments.add(sig)

    result: List[Dict[str, Any]] = []
    for key in order:
        entry = merged[key]
        student = entry["student"]
        # compose_message reads preferred_first_name/first_name; the trimmed
        # student dict on an entry only carries preferred_first_name and a full
        # name, so reconstruct a first_name from the latter.
        compose_student = {
            "preferred_first_name": student.get("preferred_first_name"),
            "first_name": (student.get("name") or "").split(" ")[0],
        }
        entry["message"] = compose_message(compose_student, entry["assignments"])
        result.append(entry)

    return result


def run_reminder_mode(db: firestore.Client, args: argparse.Namespace) -> None:
    reminders = gather_reminders(db, args)

    # Merge Canvas reminders
    canvas_reminders = gather_canvas_reminders(db, args)
    reminders.extend(canvas_reminders)

    # Collapse multiple entries for the same student (e.g. gradesync + Canvas)
    # into a single reminder so every channel sends one combined message.
    reminders = merge_reminders_by_student(reminders)

    # Research-study gate — apply AFTER merging all sources, BEFORE any CSV/output.
    reminders = apply_study_gate(db, reminders, debug=args.debug)

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

    # Write SMS CSV into text-service/message_requests if requested
    if args.sms_csv:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        base_dir = project_root / "text-service" / "message_requests"
        base_dir.mkdir(parents=True, exist_ok=True)

        output_path = base_dir / args.sms_output
        write_sms_csv(reminders, output_path)

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
