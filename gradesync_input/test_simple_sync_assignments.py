import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import simple_sync
from simple_sync import parse_assignments
from simple_sync import find_due_value
from course_import import extract_detail_due, fetch_course


class LoginResponse:
    def __init__(self, text, url, status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class LoginSession:
    def __init__(self, account_url, account_status=200):
        self.headers = {}
        self.account_url = account_url
        self.account_status = account_status

    def get(self, url):
        if url.endswith("/login"):
            return LoginResponse(
                '<input name="authenticity_token" value="csrf-token">',
                url,
            )
        return LoginResponse(
            "<html>Account page</html>",
            self.account_url,
            self.account_status,
        )

    def post(self, url, data, allow_redirects):
        self.login_data = data
        return LoginResponse("<html>Signed in</html>", url)


class GradescopeLoginTest(unittest.TestCase):
    def test_accepts_account_access_without_logout_html_marker(self):
        session = LoginSession("https://www.gradescope.com/account")

        with patch.object(simple_sync.requests, "Session", return_value=session):
            self.assertIs(simple_sync.gs_login("instructor@example.com", "password"), session)
        self.assertEqual(session.headers["User-Agent"], "Mozilla/5.0 SimpleSync")
        self.assertEqual(session.login_data["session[remember_me_code]"], "")

    def test_rejects_login_redirect_from_account_page(self):
        session = LoginSession("https://www.gradescope.com/login")

        with patch.object(simple_sync.requests, "Session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "GRADESCOPE_AUTH_ERROR"):
                simple_sync.gs_login("instructor@example.com", "password")

    def test_reports_unauthorized_account_access_as_authentication_error(self):
        session = LoginSession("https://www.gradescope.com/account", account_status=401)

        with patch.object(simple_sync.requests, "Session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                simple_sync.gs_login("instructor@example.com", "password")


class ParseAssignmentsTest(unittest.TestCase):
    def test_course_import_requires_numeric_id(self):
        with self.assertRaisesRegex(RuntimeError, "numeric Gradescope Course ID"):
            fetch_course("7KN4P5")

    def test_extracts_assignment_id_title_and_due_date(self):
        html = (
            '<div data-react-props="{&quot;table_data&quot;:['
            '{&quot;type&quot;:&quot;assignment&quot;,&quot;id&quot;:&quot;Assignment 123&quot;,'
            '&quot;title&quot;:&quot;Homework 1&quot;,&quot;due_at&quot;:&quot;2026-10-30T23:59:00Z&quot;}'
            ']}"></div>'
        )

        self.assertEqual(
            parse_assignments(html),
            [{
                "id": "123",
                "title": "Homework 1",
                "due": "2026-10-30T23:59:00Z",
            }],
        )

    def test_missing_due_date_is_preserved_as_none(self):
        html = (
            '<div data-react-props="{&quot;table_data&quot;:['
            '{&quot;type&quot;:&quot;assignment&quot;,&quot;id&quot;:&quot;Assignment 123&quot;,'
            '&quot;title&quot;:&quot;Homework 1&quot;}'
            ']}"></div>'
        )

        self.assertIsNone(parse_assignments(html)[0]["due"])

    def test_finds_nested_due_date_values(self):
        self.assertEqual(find_due_value({"assignment": {"dueDate": "2026-10-30T23:59:00Z"}}),
                         "2026-10-30T23:59:00Z")

    def test_reads_due_date_from_assignment_detail_props(self):
        html = (
            '<div data-react-props="{&quot;assignment&quot;:'
            '{&quot;due_at&quot;:&quot;2026-10-30T23:59:00Z&quot;}}"></div>'
        )
        self.assertEqual(extract_detail_due(html), "2026-10-30T23:59:00Z")


if __name__ == "__main__":
    unittest.main()
