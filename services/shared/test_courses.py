"""Behavior-preserving tests for courses.json categorization (CS61A)."""

from shared.courses import (
    categorize_assignment,
    default_category_prefs,
    default_course_code,
    default_course_prefs,
    merge_category_prefs,
    should_apply_project_early,
    student_course_codes,
    student_course_prefs,
)

ALL_ON_61A = {"lab": True, "homework": True, "midterm": True, "quiz": True, "project": True}
ALL_ON_61C = {"lab": True, "homework": True, "project": True}


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


# --- merge_category_prefs ---------------------------------------------------

def test_merge_keeps_known_prefs_drops_unknown_and_defaults_new_on():
    assert merge_category_prefs("CS61C", {"lab": False, "discussion": False}) == {
        "lab": False, "homework": True, "project": True,
    }


def test_merge_treats_missing_prefs_as_all_on():
    assert merge_category_prefs("CS61C", None) == ALL_ON_61C


# --- student_course_codes ---------------------------------------------------

def test_course_codes_legacy_single_course():
    assert student_course_codes({"course_code": "CS61A"}) == ["CS61A"]


def test_course_codes_new_list_normalized_and_deduped():
    student = {"course_codes": [" cs61a", "CS61A", "CS61C", ""], "course_code": "CS10"}
    assert student_course_codes(student) == ["CS61A", "CS61C"]


def test_course_codes_empty_when_no_course():
    assert student_course_codes({}) == []
    assert student_course_codes({"course_code": ""}) == []  # 209 such students in prod


def test_course_codes_empty_list_wins_over_stale_legacy_field():
    assert student_course_codes({"course_codes": [], "course_code": "CS61A"}) == []


# --- student_course_prefs ---------------------------------------------------

def test_prefs_legacy_doc_for_its_own_course():
    student = {
        "course_code": "CS61A",
        "category_prefs": {"lab": False},
        "project_early_reminder": True,
        "release_reminder": False,
    }
    assert student_course_prefs(student, "CS61A") == {
        "category_prefs": {**ALL_ON_61A, "lab": False},
        "project_early_reminder": True,
        "release_reminder": False,
    }


def test_prefs_legacy_doc_for_another_course_are_defaults():
    student = {"course_code": "CS61A", "category_prefs": {"lab": False}, "release_reminder": False}
    assert student_course_prefs(student, "CS61C") == default_course_prefs("CS61C")


def test_prefs_new_doc_reads_per_course_entry_not_legacy_fields():
    student = {
        "course_code": "CS61A",
        "category_prefs": {"lab": False},  # stale legacy value, must be ignored
        "course_codes": ["CS61A", "CS61C"],
        "course_prefs": {
            "CS61A": {"category_prefs": {"homework": False}, "release_reminder": True},
            "CS61C": {"category_prefs": {"project": False}, "project_early_reminder": True},
        },
    }
    assert student_course_prefs(student, "CS61A")["category_prefs"] == {**ALL_ON_61A, "homework": False}
    assert student_course_prefs(student, "cs61c") == {
        "category_prefs": {**ALL_ON_61C, "project": False},
        "project_early_reminder": True,
        "release_reminder": True,
    }


def test_prefs_mixed_doc_falls_back_to_legacy_for_unmigrated_course():
    # Mid-migration: the list exists but this course's entry hasn't been written yet.
    student = {
        "course_code": "CS61A",
        "category_prefs": {"lab": False},
        "course_codes": ["CS61A", "CS61C"],
        "course_prefs": {"CS61C": {}},
    }
    assert student_course_prefs(student, "CS61A")["category_prefs"]["lab"] is False


def test_prefs_missing_fields_follow_pipeline_defaults():
    # Release reminders are opt-out, early reminders opt-in, categories default on.
    assert student_course_prefs({"course_prefs": {"CS61C": {}}}, "CS61C") == default_course_prefs("CS61C")
    assert default_course_prefs("CS61C") == {
        "category_prefs": ALL_ON_61C,
        "project_early_reminder": False,
        "release_reminder": True,
    }


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
