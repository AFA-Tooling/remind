#!/usr/bin/env python3
"""
Pull every assignment's grade CSV from a Gradescope course and write each one
as a tab in a Google Sheet. Re-runs overwrite cleanly.
"""

import argparse
import csv
import io
import json
import re
import time
from pathlib import Path

import os

import gspread
import requests
import google.auth
from google.oauth2.service_account import Credentials
from html import unescape

GRADESCOPE_BASE = "https://www.gradescope.com"
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def gs_login(email: str, password: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    r = session.get(f"{GRADESCOPE_BASE}/login")
    r.raise_for_status()

    match = re.search(r'<input[^>]+name="authenticity_token"[^>]+value="([^"]+)"', r.text)
    if not match:
        raise RuntimeError("Could not find CSRF token on Gradescope login page")
    csrf = match.group(1)

    r = session.post(
        f"{GRADESCOPE_BASE}/login",
        data={
            "utf8": "✓",
            "authenticity_token": csrf,
            "session[email]": email,
            "session[password]": password,
            "session[remember_me]": "0",
            "commit": "Log In",
        },
        allow_redirects=True,
    )
    r.raise_for_status()

    if "/logout" not in r.text and "Log Out" not in r.text:
        raise RuntimeError("Gradescope login failed — check credentials")

    return session


def get_assignments(session: requests.Session, course_id: str) -> list[dict]:
    r = session.get(f"{GRADESCOPE_BASE}/courses/{course_id}/assignments")
    r.raise_for_status()

    m = re.search(r'data-react-props="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("Could not find assignment data on Gradescope page")

    data = json.loads(unescape(m.group(1)))
    assignments = []
    for row in data.get("table_data", []):
        if row.get("type") != "assignment":
            continue
        raw_id = row.get("id", "")
        id_match = re.search(r"(\d+)$", raw_id)
        if not id_match or not row.get("title"):
            continue
        assignments.append({"id": id_match.group(1), "title": row["title"]})

    return assignments


def fetch_csv(
    session: requests.Session, course_id: str, assignment_id: str
) -> list[list[str]] | None:
    url = f"{GRADESCOPE_BASE}/courses/{course_id}/assignments/{assignment_id}/scores.csv"
    r = session.get(url)
    if r.status_code in (403, 404):
        return None
    r.raise_for_status()
    return list(csv.reader(io.StringIO(r.text)))


def sync_roster_from_assignments(spreadsheet: gspread.Spreadsheet, first_assignment_rows: list[list[str]]):
    """Add any students missing from the Roster tab using names from an assignment CSV."""
    if not first_assignment_rows or len(first_assignment_rows) < 2:
        return

    headers = [h.strip().lower() for h in first_assignment_rows[0]]
    try:
        name_idx = headers.index("name")
        email_idx = headers.index("email")
        sid_idx = headers.index("sid") if "sid" in headers else None
    except ValueError:
        print("  → assignment tab missing Name/Email column, skipping roster sync")
        return

    # Build email→row map from assignment data
    assignment_students = {}
    for row in first_assignment_rows[1:]:
        if len(row) <= max(name_idx, email_idx):
            continue
        email = row[email_idx].strip().lower()
        name = row[name_idx].strip()
        sid = row[sid_idx].strip() if sid_idx is not None and len(row) > sid_idx else ""
        if email:
            assignment_students[email] = {"name": name, "sid": sid}

    # Read existing Roster tab
    try:
        roster_ws = spreadsheet.worksheet("Roster")
        roster_rows = roster_ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        print("  → no Roster tab found, skipping roster sync")
        return

    roster_emails = set()
    if len(roster_rows) > 1:
        try:
            r_headers = [h.strip().lower() for h in roster_rows[0]]
            r_email_idx = r_headers.index("email")
            roster_emails = {row[r_email_idx].strip().lower() for row in roster_rows[1:] if len(row) > r_email_idx}
        except ValueError:
            pass

    # Append missing students
    missing = [v | {"email": e} for e, v in assignment_students.items() if e not in roster_emails]
    if not missing:
        print("  → Roster up to date")
        return

    new_rows = [[m["name"], m["sid"], m["email"], "Student"] for m in missing]
    roster_ws.append_rows(new_rows, value_input_option="RAW")
    print(f"  → added {len(new_rows)} missing student(s) to Roster: {[m['email'] for m in missing]}")


def safe_tab_name(name: str) -> str:
    name = re.sub(r"[\[\]*?:/\\']", "-", name)
    return name[:100]


def get_or_create_worksheet(spreadsheet: gspread.Spreadsheet, title: str):
    for attempt in range(5):
        try:
            return spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            return spreadsheet.add_worksheet(title=title, rows=2000, cols=50)
        except gspread.exceptions.APIError as e:
            if hasattr(e, "response") and e.response.status_code >= 500:
                wait = (2 ** attempt) * 5
                print(f"    server error, retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Could not get/create worksheet '{title}' after 5 retries")


def write_tab(ws, rows: list[list[str]], sleep: float):
    for attempt in range(6):
        try:
            ws.clear()
            break
        except gspread.exceptions.APIError as e:
            if hasattr(e, "response") and e.response.status_code >= 500:
                wait = (2 ** attempt) * 5
                print(f"    server error on clear, retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise
    if not rows:
        return
    for attempt in range(6):
        try:
            ws.update(rows, value_input_option="RAW")
            return
        except gspread.exceptions.APIError as e:
            if hasattr(e, "response") and e.response.status_code in (429, 500, 503):
                wait = (2 ** attempt) * 10
                print(f"    API error ({e.response.status_code}), retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Sheets write failed after 6 retries")


def main():
    parser = argparse.ArgumentParser(description="Sync Gradescope grades to Google Sheets")
    parser.add_argument("--config", default="config/sync_config.json")
    parser.add_argument("--credentials", default="config/credentials.json")
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.2,
        help="Seconds between Sheets writes (~50/min at default)",
    )
    args = parser.parse_args()

    base = Path(__file__).parent
    config_path = base / args.config
    creds_path = base / args.credentials

    if os.getenv("K_SERVICE") or os.getenv("K_JOB"):
        # Running on Cloud Run (Service or Job) — read from env vars / mounted secrets
        course_id = os.environ["GRADESCOPE_COURSE_ID"]
        spreadsheet_id = os.environ["SPREADSHEET_ID"]
        gs_email = os.environ["GRADESCOPE_EMAIL"]
        gs_password = os.environ["GRADESCOPE_PASSWORD"]
    else:
        with open(config_path) as f:
            config = json.load(f)
        course_id = config["GRADESCOPE_COURSE_ID"]
        spreadsheet_id = config["SPREADSHEET_ID"]
        gs_email = config["GRADESCOPE_EMAIL"]
        gs_password = config["GRADESCOPE_PASSWORD"]

    print("Authenticating with Google Sheets…")
    if os.getenv("K_SERVICE") or os.getenv("K_JOB"):
        # Running on Cloud Run — use ADC
        creds, _ = google.auth.default(scopes=SHEETS_SCOPES)
    else:
        creds = Credentials.from_service_account_file(str(creds_path), scopes=SHEETS_SCOPES)
    gc = gspread.authorize(creds)
    for attempt in range(5):
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
            break
        except gspread.exceptions.APIError as e:
            if hasattr(e, "response") and e.response.status_code >= 500:
                wait = (2 ** attempt) * 5
                print(f"  Sheets API error, retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise
    else:
        raise RuntimeError("Could not open spreadsheet after 5 retries")

    print("Logging into Gradescope…")
    session = gs_login(gs_email, gs_password)
    print("  logged in")

    print("Fetching assignment list…")
    assignments = get_assignments(session, course_id)
    print(f"  found {len(assignments)} assignments")

    first_assignment_rows = None
    for i, asn in enumerate(assignments, 1):
        aid, title = asn["id"], asn["title"]
        tab = safe_tab_name(title)
        print(f"[{i}/{len(assignments)}] {title}")

        rows = fetch_csv(session, course_id, aid)
        if rows is None:
            print("  → no scores CSV, skipping")
            continue

        if first_assignment_rows is None:
            first_assignment_rows = rows

        ws = get_or_create_worksheet(spreadsheet, tab)
        write_tab(ws, rows, args.sleep)
        print(f"  → wrote {len(rows)} rows to tab '{tab}'")
        time.sleep(args.sleep)

    print("\nSyncing Roster tab…")
    if first_assignment_rows:
        sync_roster_from_assignments(spreadsheet, first_assignment_rows)

    print("\nDone!")


if __name__ == "__main__":
    main()
