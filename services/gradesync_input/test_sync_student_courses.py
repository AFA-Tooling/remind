"""Unit tests for roster → student course sync decisions."""

from sync_student_courses import (
    decide_course_code_clear,
    decide_roster_entry,
    decide_roster_prune,
    decide_student_course_update,
)


def test_updates_when_roster_course_differs():
    patch = decide_student_course_update(
        {
            "email": "a@berkeley.edu",
            "course_code": "CS10",
            "category_prefs": {"lab": False, "homework": True},
        },
        {"a@berkeley.edu": "CS61A"},
    )
    assert patch is not None
    assert patch["course_code"] == "CS61A"
    assert patch["category_prefs"]["lab"] is False
    assert patch["category_prefs"]["quiz"] is True  # new key defaulted on


def test_no_op_when_already_matching():
    assert (
        decide_student_course_update(
            {"email": "a@berkeley.edu", "course_code": "CS61A", "course_codes": ["CS61A"]},
            {"a@berkeley.edu": ["CS61A"]},
        )
        is None
    )


def test_old_shape_doc_gets_its_course_list_without_changing_course():
    # Every existing student doc takes this path once, on the first sync.
    patch = decide_student_course_update(
        {"email": "a@berkeley.edu", "course_code": "CS61A", "category_prefs": {"lab": False}},
        {"a@berkeley.edu": ["CS61A"]},
    )
    assert patch["course_codes"] == ["CS61A"]
    assert "course_code" not in patch
    assert "category_prefs" not in patch


def test_leaves_non_roster_students_alone():
    assert (
        decide_student_course_update(
            {"email": "staff@berkeley.edu", "course_code": "CS61A"},
            {},
        )
        is None
    )


def test_blank_course_code_is_updated_from_roster():
    patch = decide_student_course_update(
        {"email": "a@berkeley.edu", "course_code": "  "},
        {"a@berkeley.edu": "CS61A"},
    )
    assert patch is not None
    assert patch["course_code"] == "CS61A"


def test_clears_course_code_when_dropped_from_its_own_roster():
    patch = decide_course_code_clear(
        {"email": "a@berkeley.edu", "course_code": "CS61A"},
        "CS61A",
    )
    assert patch is not None
    assert patch["course_code"] == ""


def test_leaves_course_code_alone_when_it_points_elsewhere():
    # e.g. a consent-enrolled participant, or a student who already moved courses —
    # being pruned from CS61A's roster should never touch their CS10 course_code.
    assert (
        decide_course_code_clear(
            {"email": "a@berkeley.edu", "course_code": "CS10"},
            "CS61A",
        )
        is None
    )


def test_leaves_unset_course_code_alone():
    assert (
        decide_course_code_clear(
            {"email": "a@berkeley.edu", "course_code": ""},
            "CS61A",
        )
        is None
    )


def test_pinned_student_ignores_a_conflicting_roster():
    # A student genuinely on more than one course's real roster can't be
    # represented by class_roster (one doc per email) — an admin pin is the
    # only way to hold them on a specific course regardless of what the
    # roster says.
    assert (
        decide_student_course_update(
            {"email": "a@berkeley.edu", "course_code": "CS61A", "course_code_pinned": True},
            {"a@berkeley.edu": "CS61C"},
        )
        is None
    )


def test_unpinned_student_still_updates_normally():
    # The pin field itself must not silently gate every student — only
    # those explicitly marked.
    patch = decide_student_course_update(
        {"email": "a@berkeley.edu", "course_code": "CS61A", "course_code_pinned": False},
        {"a@berkeley.edu": "CS61C"},
    )
    assert patch is not None
    assert patch["course_code"] == "CS61C"


def test_pinned_student_is_never_cleared_even_if_dropped_from_that_course():
    assert (
        decide_course_code_clear(
            {"email": "a@berkeley.edu", "course_code": "CS61A", "course_code_pinned": True},
            "CS61A",
        )
        is None
    )


# --- multi-course students ----------------------------------------------------

def test_student_on_two_rosters_gets_both_and_keeps_legacy_course():
    patch = decide_student_course_update(
        {"email": "a@berkeley.edu", "course_code": "CS61C", "category_prefs": {"lab": False}},
        {"a@berkeley.edu": ["CS61A", "CS61C"]},
    )
    assert patch["course_codes"] == ["CS61A", "CS61C"]
    # The legacy field already names one of their courses, so it (and the
    # prefs that go with it) stays put.
    assert "course_code" not in patch
    assert "category_prefs" not in patch


def test_legacy_course_moves_only_when_no_longer_in_the_list():
    patch = decide_student_course_update(
        {"email": "a@berkeley.edu", "course_code": "CS10", "course_codes": ["CS10"]},
        {"a@berkeley.edu": ["CS61A", "CS61C"]},
    )
    assert patch["course_codes"] == ["CS61A", "CS61C"]
    assert patch["course_code"] == "CS61A"


def test_dropping_one_of_two_courses_keeps_the_other():
    patch = decide_course_code_clear(
        {"email": "a@berkeley.edu", "course_code": "CS61A", "course_codes": ["CS61A", "CS61C"],
         "category_prefs": {"lab": False}},
        "CS61A",
    )
    assert patch["course_codes"] == ["CS61C"]
    assert patch["course_code"] == "CS61C"
    assert patch["category_prefs"] == {"lab": False, "homework": True, "project": True}


def test_dropping_the_non_legacy_course_leaves_course_code_alone():
    patch = decide_course_code_clear(
        {"email": "a@berkeley.edu", "course_code": "CS61A", "course_codes": ["CS61A", "CS61C"]},
        "CS61C",
    )
    assert patch["course_codes"] == ["CS61A"]
    assert "course_code" not in patch


def test_dropping_last_course_empties_both_fields():
    patch = decide_course_code_clear(
        {"email": "a@berkeley.edu", "course_code": "CS61A", "course_codes": ["CS61A"]},
        "CS61A",
    )
    assert patch["course_codes"] == []
    assert patch["course_code"] == ""


# --- class_roster ---------------------------------------------------------------

def test_roster_entry_new_student():
    rec = decide_roster_entry(None, "CS61C", "Al Ice", "Al@berkeley.edu")
    assert rec["course_codes"] == ["CS61C"]
    assert rec["course_code"] == "CS61C"
    assert rec["email"] == "Al@berkeley.edu"


def test_roster_entry_adds_course_to_old_shape_doc():
    # Production today: one course, whichever course synced last.
    rec = decide_roster_entry({"course_code": "CS61C"}, "CS61A", "Al", "al@berkeley.edu")
    assert rec["course_codes"] == ["CS61C", "CS61A"]
    assert rec["course_code"] == "CS61C"  # legacy field no longer flips each sync


def test_roster_entry_is_idempotent():
    existing = {"course_code": "CS61A", "course_codes": ["CS61A", "CS61C"]}
    rec = decide_roster_entry(existing, "CS61C", "Al", "al@berkeley.edu")
    assert rec["course_codes"] == ["CS61A", "CS61C"]
    assert rec["course_code"] == "CS61A"


def test_roster_prune_keeps_doc_not_in_that_course():
    assert decide_roster_prune({"course_codes": ["CS61C"], "course_code": "CS61C"}, "CS61A") == ("keep", None)


def test_roster_prune_drops_only_that_course():
    action, patch = decide_roster_prune(
        {"course_codes": ["CS61A", "CS61C"], "course_code": "CS61A"}, "CS61A"
    )
    assert action == "update"
    assert patch["course_codes"] == ["CS61C"]
    assert patch["course_code"] == "CS61C"


def test_roster_prune_deletes_when_no_course_left():
    assert decide_roster_prune({"course_codes": ["CS61A"]}, "CS61A") == ("delete", None)
    # Old-shape doc, as before this change.
    assert decide_roster_prune({"course_code": "CS61A"}, "CS61A") == ("delete", None)


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
