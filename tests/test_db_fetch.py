from datetime import datetime
from types import SimpleNamespace
from copy import deepcopy
import pytest
import services.gradesync_input.db_fetch as db_fetch

# -----------------------------
# Helpers
# -----------------------------

class FakeResponse:
    def __init__(self, data, error=None):
        self.data = data
        self.error = error


class FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return FakeResponse(self._data)


class FakeSupabase:
    """
    Minimal fake supabase client that supports:
      supabase.table(name).select("*").limit(...).execute().data
    """
    def __init__(self, table_to_rows):
        self.table_to_rows = table_to_rows

    def table(self, name):
        return FakeQuery(self.table_to_rows.get(name, []))


def freeze_now(monkeypatch, dt: datetime):
    """
    Patch db_fetch.datetime.now() to return dt.
    db_fetch imports datetime via `from datetime import datetime`, so patch module name.
    """
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return dt

    monkeypatch.setattr(db_fetch, "datetime", FixedDateTime)

def make_deadlines_table():
    """Return a realistic deadlines table (list of dict rows)."""
    return [
        {
            "id": 4,
            "course_code": "CS10",
            "assignment_code": "PROJ04",
            "assignment_name": "Project 4: Feedback + Comments",
            "due": "2026-02-18 23:59:59",
            "created_at": "2026-01-21 23:32:07.893881",
            "updated_at": "2026-01-21 17:26:36.554923",
        },
        {
            "id": 5,
            "course_code": "CS10",
            "assignment_code": "PROJ05",
            "assignment_name": "Project 5: Final Project",
            "due": "2026-02-17 23:59:59",
            "created_at": "2026-01-21 23:32:07.893881",
            "updated_at": "2026-01-21 17:26:36.554923",
        },
        {
            "id": 1,
            "course_code": "CS61A",
            "assignment_code": "HW01",
            "assignment_name": "Functions, Control",
            "due": "2026-02-18 23:59:59",
            "created_at": "2026-01-21 23:32:07.893881",
            "updated_at": "2026-01-21 17:26:36.554923",
        },
    ]


def make_assignment_resources_table():
    """Return a realistic assignment_resources table (list of dict rows)."""
    return [
        {
            "idx": 0,
            "id": 1,
            "course_code": "CS61A",
            "assignment_code": "HW01",
            "assignment_name": "Functions, Control",
            "resource_type": "Reading",
            "resource_name": "Section 1.1",
            "link": "https://www.composingprograms.com/",
            "deadline": None,
        },
        {
            "idx": 1,
            "id": 2,
            "course_code": "CS10",
            "assignment_code": "PROJ04",
            "assignment_name": "Project 4: Feedback + Comments",
            "resource_type": "Reading",
            "resource_name": "Proj 4 Slides",
            "link": "http://p4",
            "deadline": None,
        },
        {
            "idx": 2,
            "id": 3,
            "course_code": "CS10",
            "assignment_code": "PROJ05",
            "assignment_name": "Project 5: Final Project",
            "resource_type": "Reading",
            "resource_name": "Spec",
            "link": "http://spec",
            "deadline": None,
        },
    ]


def make_students_table():
    """Return a realistic students_duplicate table (list of dict rows)."""
    return [
        {
            "id": 101,
            "email": "jshahatit@berkeley.edu",
            "course_code": "CS10",
            "days_before_deadline": 2,
            "email_pref": True,
            "discord_pref": False,
            "discord_id": None,
            "preferred_first_name": "Jacob",
        },
        {
            "id": 102,
            "email": "oindree@berkeley.edu",
            "course_code": "CS10",
            "days_before_deadline": 1,
            "email_pref": True,
            "discord_pref": True,
            "discord_id": "oindree",
            "preferred_first_name": "Oindree",
        },
        {
            "id": 103,
            "email": "lynn_kkcz@berkeley.edu",
            "course_code": "CS61A",
            "days_before_deadline": 2,
            "email_pref": True,
            "discord_pref": True,
            "discord_id": "catherine_cz",
            "preferred_first_name": None,
        },
        {
            "id": 104,
            "email": "autoremindberkeley@gmail.com",
            "course_code": "CS10",
            "days_before_deadline": 4,
            "email_pref": True,
            "discord_pref": False,
            "discord_id": None,
            "preferred_first_name": None,
        },
    ]

# -----------------------------
# Unit tests: deadlines loading/matching
# -----------------------------

def test_load_deadlines_from_rows_builds_maps():
    rows = make_deadlines_table()
    deadlines = db_fetch.load_deadlines_from_rows(rows)

    assert deadlines["CS10"]["code"]["PROJ04"].isoformat(sep=" ") == "2026-02-18 23:59:59"
    assert deadlines["CS10"]["name"]["Project 5: Final Project"].isoformat(sep=" ") == "2026-02-17 23:59:59"


def test_find_deadline_for_entry_matches_by_code_first():
    deadlines = db_fetch.load_deadlines_from_rows(make_deadlines_table())

    due = db_fetch.find_deadline_for_entry(
        "CS10",
        assignment_name="Some other name",
        assignment_code="PROJ04",
        deadlines=deadlines,
    )
    assert due.isoformat(sep=" ") == "2026-02-18 23:59:59"


def test_find_deadline_for_entry_matches_by_name_if_code_missing():
    rows = deepcopy(make_deadlines_table())

    for r in rows:
        if r.get("course_code") == "CS10" and r.get("assignment_code") == "PROJ04":
            r["assignment_code"] = ""
            break

    deadlines = db_fetch.load_deadlines_from_rows(rows)

    due = db_fetch.find_deadline_for_entry(
        "CS10",
        assignment_name="Project 4: Feedback + Comments",
        assignment_code=None,
        deadlines=deadlines,
    )
    assert due.isoformat(sep=" ") == "2026-02-18 23:59:59"


# -----------------------------
# Unit tests: assignment payload logic
# -----------------------------

def test_build_assignment_payload_skips_when_delta_not_equal_freq():
    today = datetime(2026, 2, 16, 7, 0, 0)

    deadlines = db_fetch.load_deadlines_from_rows(make_deadlines_table())
    lookup = db_fetch.build_assignment_lookup(make_assignment_resources_table(), deadlines)

    student = {
        "email": "autoremindberkeley@gmail.com",
        "course_code": "CS10",
        "days_before_deadline": 4,
        "email_pref": True,
        "discord_pref": False,
        "discord_id": None,
    }

    payload = db_fetch.build_assignment_payload(student, "PROJ04", lookup, today, debug=False)
    assert payload is None


def test_build_assignment_payload_returns_when_delta_equals_freq():
    today = datetime(2026, 2, 16, 7, 0, 0)

    deadlines = db_fetch.load_deadlines_from_rows(make_deadlines_table())
    lookup = db_fetch.build_assignment_lookup(make_assignment_resources_table(), deadlines)

    student = {
        "email": "lynn_kkcz@berkeley.edu",
        "course_code": "CS10",
        "days_before_deadline": 2,
        "email_pref": True,
        "discord_pref": True,
        "discord_id": "catherine_cz",
        "preferred_first_name": None,
    }

    payload = db_fetch.build_assignment_payload(student, "PROJ04", lookup, today, debug=False)
    assert payload is not None
    assert payload["assignment_code"] == "PROJ04"
    assert payload["assignment_name"] == "Project 4: Feedback + Comments"
    assert payload["personal_deadline"].date().isoformat() == "2026-02-18"
    assert payload["notification_window_days"] == 2


def test_gather_reminders_creates_entries(monkeypatch):
    # Freeze "today" so delta_days math is deterministic
    freeze_now(monkeypatch, datetime(2026, 2, 16, 7, 0, 0))

    monkeypatch.setattr(
        db_fetch,
        "settings",
        SimpleNamespace(SUPABASE_URL="http://fake", SUPABASE_SERVICE_ROLE_KEY="fakekey"),
    )

    deadlines_rows = make_deadlines_table()
    resources_rows = make_assignment_resources_table()
    students_rows = make_students_table()

    supabase = FakeSupabase({
        "deadlines": deadlines_rows,
        "assignment_resources": resources_rows,
        "students_duplicate": students_rows,
    })

    args = SimpleNamespace(
        debug=False,
        limit=None,
        resources_table="assignment_resources",
        deadlines_table="deadlines",
    )

    reminders = db_fetch.gather_reminders(supabase, args)

    # With our hardcoded tables:
    # - Jacob (CS10, freq=2) should match PROJ04 (due Feb18, today Feb16 => delta=2)
    # - Oindree (CS10, freq=1) should match PROJ05 (due Feb17, today Feb16 => delta=1)
    # - Lynn (CS61A, freq=2) should match HW01 (due Feb18, today Feb16 => delta=2)
    # - autoremindberkeley (CS10, freq=4) should match nothing
    emails = sorted(r["student"]["email"] for r in reminders)
    assert emails == ["jshahatit@berkeley.edu", "lynn_kkcz@berkeley.edu", "oindree@berkeley.edu"]

    jacob = next(r for r in reminders if r["student"]["email"] == "jshahatit@berkeley.edu")
    assert any(ch["type"] == "email" for ch in jacob["channels"])
    assert any(a["assignment_code"] == "PROJ04" for a in jacob["assignments"])

    oindree = next(r for r in reminders if r["student"]["email"] == "oindree@berkeley.edu")
    assert any(ch["type"] == "email" for ch in oindree["channels"])
    assert any(ch["type"] == "discord" for ch in oindree["channels"])
    assert any(a["assignment_code"] == "PROJ05" for a in oindree["assignments"])

    lynn = next(r for r in reminders if r["student"]["email"] == "lynn_kkcz@berkeley.edu")
    assert any(ch["type"] == "email" for ch in lynn["channels"])
    assert any(ch["type"] == "discord" for ch in lynn["channels"])
    assert any(a["assignment_code"] == "HW01" for a in lynn["assignments"])