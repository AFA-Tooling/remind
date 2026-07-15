"""Tests for release-date parsing in the deadlines CSV upload path."""

import csv
from pathlib import Path

import upload_deadlines_to_db as upload


CSV_PATH = Path(__file__).resolve().parent / "shared_data" / "deadlines.csv"


def write_csv(tmp_path, rows):
    path = tmp_path / "deadlines.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["course_code", "assignment_code", "assignment_name", "due", "release"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_csv_without_release_column(tmp_path, rows):
    """Write a deadlines CSV whose header omits the `release` column entirely."""
    path = tmp_path / "deadlines.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["course_code", "assignment_code", "assignment_name", "due"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_release_column_is_parsed(tmp_path):
    path = write_csv(tmp_path, [
        {"course_code": "CS61A", "assignment_code": "Lab 0", "assignment_name": "Lab 0",
         "due": "2026-06-23 23:59:59", "release": "2026-06-22"},
    ])
    rows = upload.load_deadlines_csv(path)
    assert len(rows) == 1
    assert rows[0]["release"] == "2026-06-22T00:00:00"


def test_blank_release_is_none_but_row_still_loads(tmp_path):
    path = write_csv(tmp_path, [
        {"course_code": "CS61A", "assignment_code": "Hog Checkpoint", "assignment_name": "Hog Checkpoint",
         "due": "2026-07-01 23:59:59", "release": ""},
    ])
    rows = upload.load_deadlines_csv(path)
    assert len(rows) == 1, "a row with no release date must still upload"
    assert rows[0]["release"] is None


def test_real_csv_has_release_for_30_assignments():
    rows = upload.load_deadlines_csv(CSV_PATH)
    with_release = [r for r in rows if r["release"]]
    assert len(rows) == 34, f"expected 34 deadline rows, got {len(rows)}"
    assert len(with_release) == 30, f"expected 30 rows with a release date, got {len(with_release)}"


def test_real_csv_checkpoints_have_no_release():
    rows = upload.load_deadlines_csv(CSV_PATH)
    checkpoints = [r for r in rows if "Checkpoint" in r["assignment_name"]]
    assert len(checkpoints) == 4
    for row in checkpoints:
        assert row["release"] is None, f"{row['assignment_name']} must have no release date"


def test_real_csv_release_always_precedes_due():
    rows = upload.load_deadlines_csv(CSV_PATH)
    for row in rows:
        if row["release"]:
            assert row["release"] < row["due"], (
                f"{row['assignment_name']}: release {row['release']} is not before due {row['due']}"
            )


def test_missing_release_column_raises_instead_of_wiping_silently(tmp_path):
    # If the CSV header doesn't even have a `release` column (as opposed to a row
    # with a blank value), silently treating every row as release=None would wipe
    # every release date in Firestore on the next merge=True upload, with no
    # warning. This must raise instead.
    path = write_csv_without_release_column(tmp_path, [
        {"course_code": "CS61A", "assignment_code": "Lab 0", "assignment_name": "Lab 0",
         "due": "2026-06-23 23:59:59"},
    ])
    raised = None
    try:
        upload.load_deadlines_csv(path)
    except Exception as exc:
        raised = exc
    assert raised is not None, "expected load_deadlines_csv to raise when the release column is missing"
    assert "release" in str(raised).lower(), f"error should mention the missing release column: {raised}"
    assert str(path) in str(raised), "error should name the offending file"


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
