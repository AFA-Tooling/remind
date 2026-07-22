"""Tests for the consent-enrollment backfill's bucketing decisions.

The risk this guards against is overriding a student who deliberately turned email
off, so the opt-out cases carry the most weight here.
"""

from backfill_consent_enrollment import (
    DEFAULT_COURSE_CODE,
    DEFAULT_DAYS_BEFORE_DEADLINE,
    build_student_doc,
    never_touched_settings,
    plan_enrollment,
)

NOW = "2026-07-22T12:00:00+00:00"


def bucket_emails(plan, key):
    if key == "skipped_optout":
        return plan[key]
    return [email for email, _ in plan[key]]


def test_consented_student_with_no_doc_is_created():
    plan = plan_enrollment(["jo@berkeley.edu"], {}, {}, NOW)

    assert bucket_emails(plan, "create") == ["jo@berkeley.edu"]
    doc = plan["create"][0][1]
    assert doc["email_pref"] is True
    assert doc["days_before_deadline"] == DEFAULT_DAYS_BEFORE_DEADLINE
    assert doc["enrolled_via"] == "consent"


def test_created_doc_takes_course_code_and_name_from_the_roster():
    roster = {"jo@berkeley.edu": {"name": "Jo Student", "course_code": "CS61A"}}

    doc = plan_enrollment(["jo@berkeley.edu"], {}, roster, NOW)["create"][0][1]

    assert doc["course_code"] == "CS61A"
    assert doc["preferred_first_name"] == "Jo"


def test_created_doc_falls_back_to_the_default_course_when_not_on_the_roster():
    doc = plan_enrollment(["staff@berkeley.edu"], {}, {}, NOW)["create"][0][1]

    assert doc["course_code"] == DEFAULT_COURSE_CODE
    assert doc["preferred_first_name"] is None


def test_untouched_doc_with_email_off_is_activated():
    students = {
        "jo@berkeley.edu": {
            "email": "jo@berkeley.edu",
            "email_pref": False,
            "days_before_deadline": 1,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-01T00:00:00+00:00",
        }
    }

    plan = plan_enrollment(["jo@berkeley.edu"], students, {}, NOW)

    assert bucket_emails(plan, "activate") == ["jo@berkeley.edu"]
    updates = plan["activate"][0][1]
    assert updates["email_pref"] is True
    assert updates["days_before_deadline"] == DEFAULT_DAYS_BEFORE_DEADLINE


def test_activation_touches_only_the_delivery_fields():
    """Anything the student may have set themselves must survive untouched."""
    students = {
        "jo@berkeley.edu": {
            "email_pref": False,
            "phone_number": "+15105550123",
            "preferred_first_name": "Jojo",
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-01T00:00:00+00:00",
        }
    }

    updates = plan_enrollment(["jo@berkeley.edu"], students, {}, NOW)["activate"][0][1]

    assert set(updates) == {
        "email_pref",
        "days_before_deadline",
        "category_prefs",
        "updated_at",
    }


def test_explicit_opt_out_is_never_overridden():
    """Divergent timestamps mean the student saved settings with email off."""
    students = {
        "jo@berkeley.edu": {
            "email_pref": False,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-06-15T09:30:00+00:00",
        }
    }

    plan = plan_enrollment(["jo@berkeley.edu"], students, {}, NOW)

    assert plan["skipped_optout"] == ["jo@berkeley.edu"]
    assert plan["create"] == []
    assert plan["activate"] == []


def test_doc_missing_timestamps_is_treated_as_an_opt_out():
    """Unknown provenance must fail toward leaving the student's choice alone."""
    students = {"jo@berkeley.edu": {"email_pref": False}}

    plan = plan_enrollment(["jo@berkeley.edu"], students, {}, NOW)

    assert plan["skipped_optout"] == ["jo@berkeley.edu"]


def test_student_with_email_already_on_is_left_alone():
    students = {"jo@berkeley.edu": {"email_pref": True}}

    plan = plan_enrollment(["jo@berkeley.edu"], students, {}, NOW)

    assert plan["no_change"] == 1
    assert plan["create"] == []
    assert plan["activate"] == []
    assert plan["skipped_optout"] == []


def test_a_student_doc_without_consent_is_ignored():
    """The participant list drives the backfill; non-consenters are not enrolled."""
    students = {"stranger@berkeley.edu": {"email_pref": False}}

    plan = plan_enrollment([], students, {}, NOW)

    assert plan == {"create": [], "activate": [], "skipped_optout": [], "no_change": 0}


def test_duplicate_participant_emails_produce_one_write():
    plan = plan_enrollment(["jo@berkeley.edu", "jo@berkeley.edu"], {}, {}, NOW)

    assert len(plan["create"]) == 1


def test_every_participant_lands_in_exactly_one_bucket():
    students = {
        "on@berkeley.edu": {"email_pref": True},
        "untouched@berkeley.edu": {
            "email_pref": False,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-01T00:00:00+00:00",
        },
        "optout@berkeley.edu": {
            "email_pref": False,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
        },
    }
    participants = ["on@berkeley.edu", "untouched@berkeley.edu", "optout@berkeley.edu", "new@berkeley.edu"]

    plan = plan_enrollment(participants, students, {}, NOW)

    counted = (
        len(plan["create"]) + len(plan["activate"]) + len(plan["skipped_optout"]) + plan["no_change"]
    )
    assert counted == len(participants)


def test_never_touched_settings_requires_both_timestamps():
    assert never_touched_settings({"created_at": "a", "updated_at": "a"}) is True
    assert never_touched_settings({"created_at": "a", "updated_at": "b"}) is False
    assert never_touched_settings({"created_at": "a"}) is False
    assert never_touched_settings({}) is False


def test_build_student_doc_stamps_matching_timestamps():
    """So a doc this script creates is itself recognisable as never-touched."""
    doc = build_student_doc("jo@berkeley.edu", {}, NOW)

    assert doc["created_at"] == doc["updated_at"] == NOW
