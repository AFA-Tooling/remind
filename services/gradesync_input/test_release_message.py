"""Tests for the release section in composed reminder messages."""

from datetime import datetime

import db_fetch


TODAY = datetime(2026, 6, 22, 9, 0, 0)
DUE = datetime(2026, 6, 30, 23, 59, 59)


def make_assignment(name, reason, code=None):
    return {
        "assignment_code": code or name,
        "assignment_name": name,
        "base_deadline": DUE,
        "personal_deadline": DUE,
        "offset_days": 0,
        "notification_window_days": 5,
        "resources": [],
        "reason": reason,
    }


def test_release_only_message_does_not_say_due_soon():
    msg = db_fetch.compose_message({"first_name": "Ada"}, [make_assignment("Lab 5", "release")], TODAY)
    assert "Just released:" in msg
    assert "Lab 5" in msg
    assert "due soon" not in msg, "a release-only message must not claim things are due soon"
    assert "due in 5 days" not in msg, "release bullets carry no countdown label"


def test_due_only_message_is_unchanged():
    msg = db_fetch.compose_message({"first_name": "Ada"}, [make_assignment("Lab 5", "due")], TODAY)
    assert "Just released:" not in msg
    assert "due soon" in msg
    assert "due in 8 days" in msg


def test_both_sections_render_release_first():
    assignments = [make_assignment("Lab 5", "due"), make_assignment("Hog", "release")]
    msg = db_fetch.compose_message({"first_name": "Ada"}, assignments, TODAY)
    assert msg.index("Just released:") < msg.index("due soon")
    # Numbering runs continuously across both sections.
    assert "1. Hog" in msg
    assert "2. Lab 5" in msg


def test_missing_reason_is_treated_as_due():
    # Canvas-sourced payloads carry no reason and must keep rendering as due reminders.
    assignment = make_assignment("Lab 5", "due")
    del assignment["reason"]
    msg = db_fetch.compose_message({"first_name": "Ada"}, [assignment], TODAY)
    assert "Just released:" not in msg
    assert "due in 8 days" in msg


def test_release_bullet_shows_the_due_date():
    msg = db_fetch.compose_message({"first_name": "Ada"}, [make_assignment("Lab 5", "release")], TODAY)
    assert "June 30" in msg, "a release bullet should still tell the student when it's due"


def test_resources_render_in_the_release_section():
    assignment = make_assignment("Lab 5", "release")
    assignment["resources"] = [{"resource_name": "Lab 5 spec", "resource_type": "Handout", "link": "https://x.test/lab5"}]
    msg = db_fetch.compose_message({"first_name": "Ada"}, [assignment], TODAY)
    assert "Helpful resources:" in msg
    assert "https://x.test/lab5" in msg


def make_entry(assignments):
    return {
        "student": {"email": "ada@berkeley.edu", "name": "Ada Lovelace", "preferred_first_name": "Ada"},
        "channels": [{"type": "email", "target": "ada@berkeley.edu"}],
        "assignments": assignments,
    }


def test_due_replaces_release_for_same_assignment():
    release_first = make_entry([make_assignment("Lab 5", "release")])
    due_second = make_entry([make_assignment("Lab 5", "due")])
    merged = db_fetch.merge_reminders_by_student([release_first, due_second])
    assert len(merged) == 1
    assignments = merged[0]["assignments"]
    assert len(assignments) == 1, "the same assignment must not be listed twice"
    assert assignments[0]["reason"] == "due"


def test_release_does_not_replace_due():
    due_first = make_entry([make_assignment("Lab 5", "due")])
    release_second = make_entry([make_assignment("Lab 5", "release")])
    merged = db_fetch.merge_reminders_by_student([due_first, release_second])
    assignments = merged[0]["assignments"]
    assert len(assignments) == 1
    assert assignments[0]["reason"] == "due", "a release payload must never displace a due one"


def test_canvas_payload_without_reason_beats_a_release():
    canvas = make_assignment("Lab 5", "due")
    del canvas["reason"]  # Canvas payloads carry no reason
    merged = db_fetch.merge_reminders_by_student([
        make_entry([make_assignment("Lab 5", "release")]),
        make_entry([canvas]),
    ])
    assignments = merged[0]["assignments"]
    assert len(assignments) == 1
    assert assignments[0].get("reason", "due") == "due"


def test_distinct_assignments_both_survive():
    merged = db_fetch.merge_reminders_by_student([
        make_entry([make_assignment("Lab 5", "release")]),
        make_entry([make_assignment("Hog", "due")]),
    ])
    assert len(merged[0]["assignments"]) == 2


if __name__ == "__main__":
    import sys

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc or 'assertion failed'}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
