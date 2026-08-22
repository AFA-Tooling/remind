"""Unit tests for roster → student course_code sync decisions."""

from sync_student_courses import decide_course_code_clear, decide_student_course_update


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
            {"email": "a@berkeley.edu", "course_code": "CS61A"},
            {"a@berkeley.edu": "CS61A"},
        )
        is None
    )


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
