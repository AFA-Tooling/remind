"""Tests for the message_kind column write_gmail_csv adds for the email subject."""

import csv
from pathlib import Path

import db_fetch


def make_entry(email, assignments, message="body text"):
    return {
        "student": {"name": "Ada Lovelace", "sid": "123", "id": "123"},
        "channels": [{"type": "email", "target": email}],
        "assignments": assignments,
        "message": message,
    }


def read_rows(tmp_path):
    output_path = tmp_path / "message_requests.csv"
    with output_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_all_release_assignments_yield_release_kind(tmp_path):
    entry = make_entry(
        "ada@example.com",
        [
            {"assignment_name": "Lab 5", "reason": "release"},
            {"assignment_name": "Hog", "reason": "release"},
        ],
    )
    db_fetch.write_gmail_csv([entry], tmp_path)
    rows = read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["message_kind"] == "release"


def test_mixed_release_and_due_yields_due_kind(tmp_path):
    entry = make_entry(
        "ada@example.com",
        [
            {"assignment_name": "Lab 5", "reason": "release"},
            {"assignment_name": "Hog", "reason": "due"},
        ],
    )
    db_fetch.write_gmail_csv([entry], tmp_path)
    rows = read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["message_kind"] == "due"


def test_only_due_assignments_yield_due_kind(tmp_path):
    entry = make_entry(
        "ada@example.com",
        [
            {"assignment_name": "Lab 5", "reason": "due"},
        ],
    )
    db_fetch.write_gmail_csv([entry], tmp_path)
    rows = read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["message_kind"] == "due"


def test_missing_reason_key_defaults_to_due_kind(tmp_path):
    # Canvas-sourced payloads never set a "reason" key at all. Getting this
    # wrong would mislabel every Canvas reminder as a release notification.
    entry = make_entry(
        "ada@example.com",
        [
            {"assignment_name": "Lab 5"},
        ],
    )
    db_fetch.write_gmail_csv([entry], tmp_path)
    rows = read_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["message_kind"] == "due"


if __name__ == "__main__":
    import sys
    import tempfile

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            if "tmp_path" in test.__code__.co_varnames[: test.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as tmp:
                    test(Path(tmp))
            else:
                test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc or 'assertion failed'}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
