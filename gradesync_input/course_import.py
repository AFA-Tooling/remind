#!/usr/bin/env python3
"""Fetch a Gradescope course's assignments for the AutoRemind web app."""

import json
import os
import re
import sys
from html import unescape

from simple_sync import GRADESCOPE_BASE, find_due_value, gs_login, parse_assignments


def progress(message: str) -> None:
    """A step the instructor sees while the course syncs (the server relays these)."""
    print(f"[progress] {message}", file=sys.stderr, flush=True)


def extract_detail_due(html: str):
    for match in re.finditer(r'data-react-props="([^"]+)"', html):
        try:
            data = json.loads(unescape(match.group(1)))
        except json.JSONDecodeError:
            continue
        due = find_due_value(data)
        if due:
            return due

    match = re.search(
        r'"(?:due_at|due_date|dueDate|dueAt|deadline)"\s*:\s*"([^"]+)"',
        unescape(html),
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def fetch_course(course_id: str) -> dict:
    if not re.fullmatch(r"\d{1,20}", course_id):
        raise RuntimeError("Enter a numeric Gradescope Course ID")

    email = os.environ.get("GRADESCOPE_EMAIL")
    password = os.environ.get("GRADESCOPE_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "GRADESCOPE_CONFIG_ERROR: Configure GRADESCOPE_EMAIL and "
            "GRADESCOPE_PASSWORD for this server."
        )

    progress("Signing in to Gradescope")
    session = gs_login(email, password)

    progress("Loading the course's assignment list")
    response = session.get(f"{GRADESCOPE_BASE}/courses/{course_id}/assignments")
    response.raise_for_status()

    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
    title = unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else ""
    title = re.sub(r"\s*[-|]\s*Gradescope\s*$", "", title, flags=re.IGNORECASE).strip()

    assignments = parse_assignments(response.text)
    progress(f"Found {len(assignments)} assignment{'' if len(assignments) == 1 else 's'}")
    undated = sum(1 for assignment in assignments if not assignment["due"])
    checked = 0
    for assignment in assignments:
        assignment["html_url"] = (
            f"{GRADESCOPE_BASE}/courses/{course_id}/assignments/{assignment['id']}"
        )
        if not assignment["due"]:
            checked += 1
            progress(f"Checking the due date for {assignment.get('title') or 'an assignment'} ({checked} of {undated})")
            detail = session.get(assignment["html_url"])
            detail.raise_for_status()
            assignment["due"] = extract_detail_due(detail.text)

    return {
        "course_id": course_id,
        "course_name": title or f"Gradescope course {course_id}",
        "course_url": f"{GRADESCOPE_BASE}/courses/{course_id}",
        "assignments": assignments,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(fetch_course(sys.argv[1])))
    except Exception as error:
        print(str(error) or "Gradescope import failed", file=sys.stderr)
        sys.exit(1)
