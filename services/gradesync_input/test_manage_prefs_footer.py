"""Tests for the manage-preferences footer on reminder emails.

Students are enrolled for email at consent time and most never visit the dashboard,
so the email itself has to carry the way in. It is email-only: `compose_message` is
shared with Discord and SMS, where the footer would either bloat the segment count
or tell a Discord user to go enable Discord.
"""

import csv

import db_fetch
from shared import settings


def make_reminder(message="Hey there,\n\nHeads-up: Lab 3 is due soon."):
    return {
        "student": {"id": "stu1", "name": "Jo Student", "email": "jo@berkeley.edu", "sid": "123"},
        "channels": [{"type": "email", "target": "jo@berkeley.edu"}],
        "assignments": [{"assignment_code": "LAB03", "assignment_name": "Lab 3", "reason": "due"}],
        "message": message,
    }


def read_rows(output_dir):
    with (output_dir / "message_requests.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_footer_links_the_dashboard():
    body = db_fetch.append_manage_prefs_footer("Hey there,")

    assert settings.AUTOREMIND_SITE_URL in body


def test_footer_names_the_channels_a_student_can_add():
    body = db_fetch.append_manage_prefs_footer("Hey there,").lower()

    assert "text" in body
    assert "discord" in body


def test_footer_is_appended_without_disturbing_the_message():
    message = "Hey there,\n\nHeads-up: Lab 3 is due soon."

    body = db_fetch.append_manage_prefs_footer(message)

    assert body.startswith(message)


def test_gmail_csv_carries_the_footer(tmp_path):
    """The CSV is what the email service sends verbatim, so it must hold the footer."""
    db_fetch.write_gmail_csv([make_reminder()], tmp_path)

    rows = read_rows(tmp_path)
    assert len(rows) == 1
    assert settings.AUTOREMIND_SITE_URL in rows[0]["message_requests"]
    assert rows[0]["message_requests"].startswith("Hey there,")


def test_footer_is_not_added_to_discord_messages(tmp_path):
    """compose_message feeds every channel; only the Gmail writer appends the footer."""
    reminder = make_reminder()
    reminder["channels"] = [{"type": "discord", "target": "42"}]
    output = tmp_path / "discord_messages.csv"

    db_fetch.write_discord_csv([reminder], output)

    with output.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert settings.AUTOREMIND_SITE_URL not in rows[0]["message"]


def test_footer_is_not_added_to_sms_messages(tmp_path):
    reminder = make_reminder()
    reminder["channels"] = [{"type": "sms", "target": "+15105550123"}]
    output = tmp_path / "sms_messages.csv"

    db_fetch.write_sms_csv([reminder], output)

    with output.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert settings.AUTOREMIND_SITE_URL not in rows[0]["text_message"]
