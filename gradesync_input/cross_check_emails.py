#!/usr/bin/env python3
"""
Cross-check emails between two CSVs and return matched email + name pairs.

Use case: you have a list of emails with no names (e.g. survey responses that
forgot to ask), and a second CSV that has both emails and names (e.g. a class
Roster export). This finds the name for each email that appears in both.

Usage:
    python3 cross_check_emails.py <emails_only.csv> <roster_with_names.csv>
    python3 cross_check_emails.py <emails_only.csv> <roster_with_names.csv> --output matched.csv

Column detection is automatic and case-insensitive:
  - Both files need an "Email" (or "Email Address") column.
  - The roster file needs a "Name" column, OR separate "First Name" /
    "Last Name" columns (they'll be combined).

Nothing here talks to Firestore, Google Sheets, or anything online — it's a
plain local CSV-to-CSV tool. Export both files as CSV first (e.g. from Google
Sheets: File > Download > .csv), then run this on them directly.
"""
import argparse
import csv
import sys


def find_column(header, *candidates):
    """Return the index of the first header cell matching any candidate name (case-insensitive)."""
    lowered = [h.strip().lower() for h in header]
    for cand in candidates:
        if cand in lowered:
            return lowered.index(cand)
    return None


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        sys.exit(f"{path} is empty")
    return rows[0], rows[1:]


def extract_name(row, name_idx, first_idx, last_idx):
    if name_idx is not None and name_idx < len(row):
        return row[name_idx].strip()
    if first_idx is not None and last_idx is not None:
        first = row[first_idx].strip() if first_idx < len(row) else ""
        last = row[last_idx].strip() if last_idx < len(row) else ""
        return f"{first} {last}".strip()
    return ""


def main():
    parser = argparse.ArgumentParser(description="Cross-check emails between two CSVs and return matched names.")
    parser.add_argument("emails_csv", help="CSV with emails but no names (e.g. survey responses)")
    parser.add_argument("roster_csv", help="CSV with both emails and names (e.g. a Roster export)")
    parser.add_argument("--output", default=None, help="Optional path to write matched results as a CSV")
    args = parser.parse_args()

    emails_header, emails_rows = load_csv(args.emails_csv)
    roster_header, roster_rows = load_csv(args.roster_csv)

    emails_email_idx = find_column(emails_header, "email", "email address")
    if emails_email_idx is None:
        sys.exit(f"Could not find an email column in {args.emails_csv}. Headers found: {emails_header}")

    roster_email_idx = find_column(roster_header, "email", "email address")
    if roster_email_idx is None:
        sys.exit(f"Could not find an email column in {args.roster_csv}. Headers found: {roster_header}")

    roster_name_idx = find_column(roster_header, "name")
    roster_first_idx = find_column(roster_header, "first name")
    roster_last_idx = find_column(roster_header, "last name")
    if roster_name_idx is None and (roster_first_idx is None or roster_last_idx is None):
        sys.exit(
            f"Could not find a Name column (or First/Last Name pair) in {args.roster_csv}. "
            f"Headers found: {roster_header}"
        )

    # Build email -> name lookup from the roster file
    roster_lookup = {}
    for row in roster_rows:
        if roster_email_idx >= len(row):
            continue
        email = row[roster_email_idx].strip().lower()
        if not email:
            continue
        name = extract_name(row, roster_name_idx, roster_first_idx, roster_last_idx)
        if name:
            roster_lookup[email] = name

    matched = []
    unmatched = []
    seen = set()
    for row in emails_rows:
        if emails_email_idx >= len(row):
            continue
        email = row[emails_email_idx].strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        name = roster_lookup.get(email)
        if name:
            matched.append((email, name))
        else:
            unmatched.append(email)

    print(f"Matched {len(matched)} of {len(seen)} unique email(s):\n")
    for email, name in matched:
        print(f"  {email:40} {name}")

    if unmatched:
        print(f"\nNo match found for {len(unmatched)} email(s) (not on the roster, or a typo):")
        for email in unmatched:
            print(f"  {email}")

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["email", "name"])
            writer.writerows(matched)
        print(f"\nWrote {len(matched)} matched row(s) to {args.output}")


if __name__ == "__main__":
    main()
