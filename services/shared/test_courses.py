"""Behavior-preserving tests for courses.json categorization (CS61A)."""

from shared.courses import (
    categorize_assignment,
    default_category_prefs,
    default_course_code,
    should_apply_project_early,
)


def test_default_course_is_cs61a():
    assert default_course_code() == "CS61A"


def test_default_prefs_match_legacy_keys():
    assert default_category_prefs("CS61A") == {
        "lab": True,
        "homework": True,
        "midterm": True,
        "quiz": True,
        "project": True,
    }


def test_ingest_skips_quiz_and_unknown():
    assert categorize_assignment("CS61A", "Quiz 1", mode="ingest") is None
    assert categorize_assignment("CS61A", "Test Autograder", mode="ingest") is None
    assert categorize_assignment("CS61A", "Lab 1", mode="ingest") == "Lab"
    assert categorize_assignment("CS61A", "Homework 5", mode="ingest") == "Homework"
    assert categorize_assignment("CS61A", "hw03", mode="ingest") == "Homework"
    assert categorize_assignment("CS61A", "Midterm 1", mode="ingest") == "Midterm"
    assert categorize_assignment("CS61A", "Hog", mode="ingest") == "Project"
    assert categorize_assignment("CS61A", "Hog Checkpoint", mode="ingest") == "Project"
    assert categorize_assignment("CS61A", "Scheme Challenge", mode="ingest") == "Project"


def test_reminder_categorizes_quiz_and_falls_back_to_project():
    assert categorize_assignment("CS61A", "Quiz 1", mode="reminder") == "Quiz"
    assert (
        categorize_assignment("CS61A", "Orientation Quiz (Optional)", mode="reminder")
        == "Quiz"
    )
    assert categorize_assignment("CS61A", "Mystery Thing", mode="reminder") == "Project"
    assert categorize_assignment("CS61A", "Lab 0", mode="reminder") == "Lab"


def test_project_early_excludes_checkpoints():
    assert should_apply_project_early("CS61A", "Project", "Hog")
    assert not should_apply_project_early("CS61A", "Project", "Hog Checkpoint")
    assert not should_apply_project_early("CS61A", "Homework", "Homework 5")
    assert not should_apply_project_early("CS61A", "Quiz", "Quiz 1")


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
