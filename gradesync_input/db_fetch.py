"""Reminder helper: read Supabase data + deadlines CSV and draft messages."""

from __future__ import annotations

import argparse
import csv
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from supabase import Client, create_client


DEFAULT_STUDENTS_TABLE = "students"
DEFAULT_RESOURCES_TABLE = "assignment_resources"
DEFAULT_DEADLINES_CSV = "shared_data/deadlines.csv"
DEFAULT_FREQ_FIELD = "notif_freq_days"


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
        default=os.getenv("SUPABASE_TABLE", DEFAULT_STUDENTS_TABLE),
        help="Table to query when --mode=raw (default: students)",
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
        help="Supabase table that stores assignment resources",
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
    return parser.parse_args()


def load_supabase_env() -> Dict[str, str]:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    required_vars = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return {
        "url": os.environ["SUPABASE_URL"],
        "service_role_key": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    }


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def fetch_table_rows(
    supabase: Client,
    table_name: str,
    limit: Optional[int] = None,
    *,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    query = supabase.table(table_name).select("*")
    if limit:
        query = query.limit(limit)

    response = query.execute()

    if getattr(response, "error", None):
        raise RuntimeError(f"Supabase error: {response.error}")

    rows = response.data or []
    debug_print(debug, f"Fetched {len(rows)} rows from '{table_name}'")
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


def load_deadlines(
    csv_path: Path, *, debug: bool = False
) -> DeadlineMap:
    deadlines: DeadlineMap = {}
    if not csv_path.exists():
        raise FileNotFoundError(f"Deadlines CSV not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            row = {(key or "").strip(): (value or "") for key, value in raw_row.items()}
            assignment = (row.get("assignment_name") or row.get("assignment") or "").strip()
            assignment_code = row.get("assignment_code", "").strip()
            due_str = row.get("due")
            course_code = row.get("course_code", "").strip()
            due_date = parse_deadline(due_str)
            if not due_date:
                continue

            course_deadlines = deadlines.setdefault(
                course_code,
                {"code": {}, "name": {}},
            )
            if assignment_code:
                course_deadlines["code"][assignment_code] = due_date
            if assignment:
                course_deadlines["name"][assignment] = due_date
            scope = course_code or "(default)"
            debug_print(
                debug,
                (
                    f"Loaded deadline code='{assignment_code or 'n/a'}' "
                    f"name='{assignment or 'n/a'}' [{scope}] → {due_date.isoformat(sep=' ')}"
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

    # Prefer a single-column layout if available (notif_freq_days).
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


def collect_assignment_codes(student: Dict[str, Any]) -> List[str]:
    return [key for key in student.keys() if key.upper().startswith("PROJ")]


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
    course_code = (student.get("course_code") or "").strip()
    course_lookup = lookup.get(course_code)
    if course_lookup is None and course_code:
        course_lookup = lookup.get("")

    entry = course_lookup.get(code) if course_lookup else None
    if not entry and course_lookup:
        alias_code = base_assignment_code(code)
        if alias_code:
            entry = course_lookup.get(alias_code)

    if not entry:
        debug_print(
            debug,
            f"No assignment data found for {code} in course '{course_code or 'default'}'",
        )
        return None

    offset_raw = student.get(code, 0) or 0
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        offset = 0

    base_deadline = entry.get("deadline")
    personal_deadline = compute_personal_deadline(base_deadline, offset)
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
        debug_print(debug, f"Skipping {code}: no deadline available")
        return None

    freq_days = get_notification_frequency(student, code)
    delta_days = (personal_deadline.date() - today.date()).days
    debug_print(
        debug,
        f"Student {student.get('id')} {code}: freq={freq_days}d, delta={delta_days}d",
    )

    if delta_days < 0:
        debug_print(debug, f"Skipping {code}: past due")
        return None

    # New rule: only send when the diff exactly matches the notification frequency.
    if delta_days != freq_days:
        debug_print(debug, f"Skipping {code}: delta {delta_days} != freq {freq_days}")
        return None

    return {
        "assignment_code": code,
        "assignment_name": entry.get("assignment_name", code),
        "base_deadline": entry.get("deadline"),
        "personal_deadline": personal_deadline,
        "offset_days": offset,
        "notification_window_days": freq_days,
        "resources": entry.get("resources", []),
    }


def compose_message(student: Dict[str, Any], assignments: List[Dict[str, Any]]) -> str:
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
        due_text = format_due_datetime(assignment["personal_deadline"])
        lines.append(
            f"- {assignment['assignment_name']} ({assignment['assignment_code']}) → due {due_text}"
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


def gather_reminders(
    supabase: Client,
    args: argparse.Namespace,
    csv_path: Path,
) -> List[Dict[str, Any]]:
    deadlines = load_deadlines(csv_path, debug=args.debug)
    resource_rows = fetch_table_rows(
        supabase,
        args.resources_table,
        debug=args.debug,
    )
    assignment_lookup = build_assignment_lookup(
        resource_rows,
        deadlines,
        debug=args.debug,
    )

    students = fetch_table_rows(
        supabase,
        DEFAULT_STUDENTS_TABLE,
        limit=args.limit,
        debug=args.debug,
    )
    today = datetime.now()

    reminders: List[Dict[str, Any]] = []
    for student in students:
        if not student.get("opt_in"):
            continue

        assignments_to_notify: List[Dict[str, Any]] = []
        for code in collect_assignment_codes(student):
            payload = build_assignment_payload(
                student,
                code,
                assignment_lookup,
                today,
                debug=args.debug,
            )
            if payload:
                assignments_to_notify.append(payload)

        if not assignments_to_notify:
            continue

        channels = determine_channels(student)
        if not channels:
            channels = [{"type": "none", "target": "(no opted-in channels)"}]

        message = compose_message(student, assignments_to_notify)

        reminders.append(
            {
                "student": {
                    "id": student.get("id"),
                    "name": f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
                },
                "channels": channels,
                "assignments": assignments_to_notify,
                "message": message,
            }
        )

    return reminders


def run_raw_mode(supabase: Client, args: argparse.Namespace) -> None:
    print(f"Fetching data from table '{args.table}'")
    rows = fetch_table_rows(
        supabase,
        args.table,
        args.limit,
        debug=args.debug,
    )
    print(f"Retrieved {len(rows)} rows.")
    for idx, row in enumerate(rows, start=1):
        print(f"Row {idx}: {row}")


def run_reminder_mode(supabase: Client, args: argparse.Namespace) -> None:
    csv_path = Path(__file__).resolve().parent / args.deadlines_csv
    reminders = gather_reminders(supabase, args, csv_path)

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

    #write Discord CSV into remind/discord_service if requested
    if args.discord_csv:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        base_dir = project_root / "discord_service" / "message_requests"
        base_dir.mkdir(parents=True, exist_ok=True)

        output_path = base_dir / args.discord_output
        write_discord_csv(reminders, output_path)


def main() -> None:
    args = parse_args()
    config = load_supabase_env()

    print("Connecting to Supabase...")
    print(f"Project URL: {config['url']}")
    print(f"Service role key: {mask_secret(config['service_role_key'])}")

    supabase: Client = create_client(config["url"], config["service_role_key"])

    if args.mode == "raw":
        run_raw_mode(supabase, args)
    else:
        run_reminder_mode(supabase, args)


if __name__ == "__main__":
    main()
