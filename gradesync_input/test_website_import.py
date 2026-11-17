import json
import unittest
from unittest.mock import patch

import requests

from website_import import (
    NAMING_SYSTEM_PROMPT,
    OUTLINE_CHUNK_CHARS,
    _assert_public_host,
    _merge_same_deliverable,
    _outline_chunks,
    extract_assignments_from_page,
    fetch_page,
    import_course_website,
    page_lines,
    page_term,
)


class _ScriptedGroq:
    """Fake Groq client that answers each request with the next scripted item list."""

    def __init__(self, *answers, renames=None):
        self.answers = list(answers)
        self.requests = []  # page-reading requests
        self.renames = renames  # the naming call's answer: a list, an Exception, or None
        self.naming_requests = []
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        if kwargs["messages"][0]["content"] == NAMING_SYSTEM_PROMPT:
            self.naming_requests.append(kwargs)
            if isinstance(self.renames, Exception):
                raise self.renames
            content = json.dumps({"renames": self.renames or []})
        else:
            self.requests.append(kwargs)
            answer = self.answers.pop(0) if self.answers else []
            if isinstance(answer, Exception):
                raise answer
            content = json.dumps({"items": answer})
        message = type("Message", (), {"content": content})()
        choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
        return type("Completion", (), {"choices": [choice]})()


class _FakeResponse:
    encoding = "utf-8"

    def __init__(self, body="", status_code=200, headers=None):
        self.body = body.encode()
        self.status_code = status_code
        self.headers = {"Content-Type": "text/html", **(headers or {})}

    def iter_content(self, chunk_size):
        yield self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def close(self):
        return None


class _FakeSession:
    trust_env = True

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, **_kwargs):
        self.requested.append(url)
        return self.pages.get(url) or _FakeResponse(status_code=404)


def _read(html, url, term, client):
    lines, links = page_lines(html, url)
    assignments, _listed = extract_assignments_from_page(lines, links, url, term, client, lambda _s: None)
    return assignments


SCHEDULE_PAGE = """
<html><body><main>
  <table>
    <tr><td>Fri, Sep 18</td><td><strong class="label">Lecture 10</strong> <a href="/lectures/10/">Tree Recursion</a>
      <strong class="label">Homework 3</strong> <a href="/hw/hw03/">Recursion (due Thu 9/24)</a></td></tr>
  </table>
  <dl><dt>Fri Sep 25</dt><dd><strong class="label label-due">Homework 1 Part 2 due</strong></dd></dl>
  <p><a href="/hw/hw04" data-due="2026/10/08">HW4</a></p>
</main></body></html>
"""


class FetchTests(unittest.TestCase):
    def test_only_the_starting_page_is_requested(self):
        session = _FakeSession({
            "https://course.example.edu/": _FakeResponse(
                '<main><a href="/hw1">Homework 1</a><a href="https://other.example.edu/hw2">Homework 2</a></main>'
            ),
        })
        with patch("website_import._assert_public_host"):
            html, url = fetch_page("https://course.example.edu/", session=session, sleep=lambda _d: None)
        self.assertIn("Homework 1", html)
        self.assertEqual(url, "https://course.example.edu/")
        self.assertEqual(session.requested, ["https://course.example.edu/"])
        self.assertFalse(session.trust_env)

    def test_meta_refresh_pages_lead_to_the_course_page_on_the_same_site(self):
        session = _FakeSession({
            "https://cs61a.org/": _FakeResponse(
                '<html><head><meta http-equiv="refresh" content="0; url=/fa26/"></head></html>'
            ),
            "https://cs61a.org/fa26/": _FakeResponse("<main>Homework 1</main>"),
        })
        with patch("website_import._assert_public_host"), patch("website_import._log"):
            html, url = fetch_page("https://cs61a.org/", session=session, sleep=lambda _d: None)
        self.assertEqual(url, "https://cs61a.org/fa26/")
        self.assertIn("Homework 1", html)

        # A refresh to another site is not followed.
        session = _FakeSession({
            "https://course.example.edu/": _FakeResponse(
                "<meta http-equiv='refresh' content='0;URL=https://evil.example.com/'><p>Home</p>"
            ),
        })
        with patch("website_import._assert_public_host"):
            _html, url = fetch_page("https://course.example.edu/", session=session, sleep=lambda _d: None)
        self.assertEqual(url, "https://course.example.edu/")
        self.assertEqual(session.requested, ["https://course.example.edu/"])

    def test_a_missing_starting_page_is_an_error(self):
        with patch("website_import._assert_public_host"):
            with self.assertRaisesRegex(RuntimeError, "starting course website URL returned HTTP 404"):
                fetch_page("https://course.example.edu/", session=_FakeSession({}), sleep=lambda _d: None)

    def test_public_host_validation_rejects_loopback_addresses(self):
        with self.assertRaisesRegex(ValueError, "public IP"):
            _assert_public_host("http://127.0.0.1/")


class PageLinesTests(unittest.TestCase):
    def test_rows_badges_links_and_site_due_markers_are_kept(self):
        lines, links = page_lines(SCHEDULE_PAGE, "https://course.example.edu/fa26/")

        self.assertEqual(lines[0].split(" | ")[0], "Fri, Sep 18")
        self.assertIn('«Homework 3» <a href="/hw/hw03/">Recursion (due Thu 9/24)</a>', lines[0])
        self.assertEqual(lines[1:3], ["Fri Sep 25", "«Homework 1 Part 2 due»"])
        self.assertEqual(lines[3], '{due 2026/10/08} <a href="/hw/hw04">HW4</a>')
        self.assertEqual(links["/hw/hw03/"], "https://course.example.edu/hw/hw03/")

    def test_scripts_styles_and_attributes_are_dropped_and_rows_stay_whole(self):
        page = """<html><head><title>CS 1</title><style>p { color: red }</style></head><body>
          <nav><a href="/">Home</a></nav>
          <script>var due = "Homework 9 due 1/1";</script>
          <!-- Homework 8 -->
          <table class="schedule" style="width: 100%"><tr data-date="2026-09-21">
            <td style="width: 12%">Mon,
               Sep 21</td>
            <td><div class="item"><strong class="label label-lab">Lab 3</strong>
              <a href="/labs/lab03/" target="_blank">Lists &amp; Trees (due Wed 9/23)</a></div>
              <div class="item"><span class="label">Project 2</span><a href="/projects/cats/">CATS</a></div></td>
          </tr></table></body></html>"""
        lines, _links = page_lines(page, "https://course.example.edu/")
        self.assertEqual(lines, [
            'Mon, Sep 21 | «Lab 3» <a href="/labs/lab03/">Lists & Trees (due Wed 9/23)</a> '
            '«Project 2» <a href="/projects/cats/">CATS</a>',
        ])

    def test_the_website_decides_which_term_it_is_for(self):
        self.assertEqual(page_term("<title>Home | CS 61A Fall 2026</title>", "https://cs61a.org/"), "Fall 2026")
        self.assertEqual(page_term("<p>Spring 2027 and Spring 2027</p><p>Fall 2026</p>", "https://x.edu/"),
                         "Spring 2027")
        self.assertEqual(page_term("<title>Course</title>", "https://fa26.datastructur.es/"), "Fall 2026")
        self.assertIsNone(page_term("<title>Course</title>", "https://course.example.edu/"))


class PageReadingTests(unittest.TestCase):
    def test_model_answers_are_checked_against_the_page(self):
        client = _ScriptedGroq([
            # Correct: date text on the item's line.
            {"line": 1, "title": "Homework 3", "due": "2026-09-24",
             "date_text": "due Thu 9/24", "link": "/hw/hw03/"},
            # Correct: date from the date heading one line above.
            {"line": 3, "title": "Homework 1 Part 2", "due": "2026-09-25",
             "date_text": "Fri Sep 25", "link": ""},
            # Wrong date for its quoted text: kept, but undated rather than trusted.
            {"line": 4, "title": "Homework 4", "due": "2026-10-09",
             "date_text": "2026/10/08", "link": "/hw/hw04"},
            # Quoted text that is not on the page: kept, undated.
            {"line": 1, "title": "Lab 9 (due Fri 12/4)", "due": "2026-12-04",
             "date_text": "due Fri 12/4", "link": "/labs/lab09/"},
            # Not a line on the page: dropped.
            {"line": 99, "title": "Project 9", "due": None, "date_text": "", "link": ""},
        ])

        assignments = _read(SCHEDULE_PAGE, "https://course.example.edu/fa26/", "Fall 2026", client)

        self.assertEqual(
            [(a["title"], a["due"], a["html_url"]) for a in assignments],
            [
                ("Homework 3", "2026-09-24", "https://course.example.edu/hw/hw03/"),
                ("Homework 1 Part 2", "2026-09-25", "https://course.example.edu/fa26/"),
                ("Homework 4", None, "https://course.example.edu/hw/hw04"),
                # Dates are stripped from titles, and a link not on its line is not used.
                ("Lab 9", None, "https://course.example.edu/fa26/"),
            ],
        )
        self.assertTrue(all(len(a["id"]) == 32 and a["source"] == "website" for a in assignments))
        system = client.requests[0]["messages"][0]["content"]
        self.assertIn("kind and number only, never the topic", system)
        self.assertIn("A missing date is never a reason to leave something out", system)
        self.assertEqual(client.requests[0]["response_format"], {"type": "json_object"})

    def test_titles_are_tidied_labs_are_never_dropped_and_discussions_are_excluded(self):
        page = """
        <html><body><main><table>
          <tr><th>Date</th><th>Lab</th><th>Discussion</th><th>Assignment / Exam</th></tr>
          <tr><td>Mon 9/14</td><td><a href="/fa26/labs/lab04/">Lab 4. Iteration</a></td>
              <td><a href="https://docs.example.com/disc5">Disc 5. Lists</a></td><td>Proj 1 Due</td></tr>
          <tr><td>Fri 10/23</td><td>Practice Midterm</td><td></td><td>MIDTERM 1</td></tr>
          <tr><td>Fri 12/11</td><td></td><td></td><td>POSTTERM</td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 2, "title": "Project 1", "due": "2026-09-14", "date_text": "Mon 9/14", "link": ""},
            {"line": 2, "title": "Lab 4. Iteration", "due": None, "date_text": "", "link": "/fa26/labs/lab04/"},
            {"line": 3, "title": "MIDTERM 1", "due": "2026-10-23", "date_text": "Fri 10/23", "link": ""},
            {"line": 4, "title": "POSTTERM", "due": "2026-12-11", "date_text": "Fri 12/11", "link": ""},
            # Discussions are excluded for every course, even if the model lists one.
            {"line": 2, "title": "Discussion 5", "due": None, "date_text": "", "link": ""},
        ])

        assignments = _read(page, "https://cs10.example.org/fa26/", "Fall 2026", client)

        self.assertEqual(
            [(a["title"], a["due"]) for a in assignments],
            [("Project 1", "2026-09-14"), ("Lab 4", None), ("Midterm 1", "2026-10-23"), ("Postterm", "2026-12-11")],
        )
        system = client.requests[0]["messages"][0]["content"]
        self.assertIn("Include every numbered lab listed on the page", system)
        self.assertIn("Exclude discussions", system)

    def test_dates_are_verified_by_meaning_not_exact_wording(self):
        page = """
        <html><body><main><dl>
          <dt>Fri Sep 18</dt><dd><strong class="label label-due">Homework 1 Part 1 due</strong></dd>
          <dt>Fri Sep 25</dt><dd><strong class="label label-hw">Homework 2</strong></dd>
          <dd><strong class="label label-due">Homework 1 Part 2 due</strong></dd>
          <dt>Tue Oct 20</dt><dd><span class="label label-exam">Midterm Exam</span> Midterm (5:00-6:30 PM)</dd>
        </dl></main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 2, "title": "Homework 1 Part 1", "due": "2026-09-18",
             "date_text": "Fri Sep 18 - Homework 1 Part 1 due", "link": ""},
            {"line": 5, "title": "Homework 1 Part 2", "due": "2026-09-25", "date_text": "", "link": ""},
            {"line": 7, "title": "Midterm Exam", "due": "2026-10-20T17:00:00", "date_text": "October 20", "link": ""},
            # A date that is nowhere near the item is still not trusted.
            {"line": 2, "title": "Homework 3", "due": "2026-12-01", "date_text": "Dec 1", "link": ""},
        ])

        assignments = _read(page, "https://eecs189.example.org/fa26/", "Fall 2026", client)

        self.assertEqual(
            [(a["title"], a["due"]) for a in assignments],
            [
                ("Homework 1 Part 1", "2026-09-18"),
                ("Homework 1 Part 2", "2026-09-25"),
                ("Midterm Exam", "2026-10-20"),
                ("Homework 3", None),
                # Not listed by the model, so the safety net shows its badge for review.
                ("Homework 2", None),
            ],
        )

    def test_dates_in_link_addresses_are_not_evidence(self):
        page = '<p><a href="/2026/12/01/hw3/">Homework 3</a></p>'
        client = _ScriptedGroq([
            {"line": 1, "title": "Homework 3", "due": "2026-12-01", "date_text": "2026/12/01", "link": ""},
        ])
        assignments = _read(page, "https://course.example.edu/", "Fall 2026", client)
        self.assertEqual([(a["title"], a["due"]) for a in assignments], [("Homework 3", None)])

    def test_dates_must_fall_in_the_course_term(self):
        page = """
        <html><body><main><table>
          <tr><td>Thu 9/24</td><td><a href="/hw/hw03/">Homework 3</a> (due Thu 9/24)</td></tr>
          <tr><td>Thu 10/8</td><td><a href="/hw/hw04/">Homework 4</a></td></tr>
          <tr><td></td><td>(due Thu 10/8)</td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq([
            # Right day, wrong year: not when the course runs.
            {"line": 1, "title": "Homework 3", "due": "2029-09-24", "date_text": "due Thu 9/24", "link": ""},
            # US-style date, and a line number one above where the date is written.
            {"line": 2, "title": "Homework 4", "due": "10/08/2026", "date_text": "due Thu 10/8", "link": ""},
        ])

        assignments = _read(page, "https://cs61a.example.org/fa26/", "Fall 2026", client)

        self.assertEqual([(a["title"], a["due"]) for a in assignments],
                         [("Homework 3", None), ("Homework 4", "2026-10-08")])
        prompt = json.loads(client.requests[0]["messages"][1]["content"])
        self.assertEqual(prompt["course_dates"], {"first": "2026-07-15", "last": "2027-01-31"})

    def test_large_pages_are_read_in_parts_with_context_and_no_double_counting(self):
        rows = "".join(
            f"<p>Week {week}: <a href='/hw/hw{week:02d}/'>Homework {week}</a> {'x' * 900}</p>"
            for week in range(1, 31)
        )
        page = f"<html><body><main>{rows}</main></body></html>"
        lines, _links = page_lines(page, "https://course.example.edu/")
        chunks = _outline_chunks(lines)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(sum(len(line) for line in lines[s:e]) <= OUTLINE_CHUNK_CHARS
                            for _c, s, e in chunks))
        self.assertTrue(all(context < start for context, start, _e in chunks[1:]))

        first_end = chunks[0][2]
        second_context, second_start = chunks[1][0], chunks[1][1]
        client = _ScriptedGroq(
            [{"line": first_end, "title": f"Homework {first_end}", "due": None, "date_text": "", "link": ""}],
            # The second part also lists an item from its context lines: ignored there.
            [{"line": second_context + 1, "title": f"Homework {second_context + 1}", "due": None,
              "date_text": "", "link": ""},
             {"line": second_start + 1, "title": f"Homework {second_start + 1}", "due": None,
              "date_text": "", "link": ""}],
        )

        assignments = _read(page, "https://course.example.edu/", "Fall 2026", client)

        self.assertEqual(len(client.requests), len(chunks))
        self.assertIn("--- START ---", json.loads(client.requests[1]["messages"][1]["content"])["lines"])
        titles = [a["title"] for a in assignments]
        self.assertEqual(titles[:2], [f"Homework {first_end}", f"Homework {second_start + 1}"])
        # Every other numbered homework the model missed is still shown for review, once.
        self.assertEqual(sorted(titles, key=lambda t: int(t.split()[1])),
                         [f"Homework {week}" for week in range(1, 31)])

    def test_model_listing_nothing_still_shows_numbered_work_for_review(self):
        assignments = _read(SCHEDULE_PAGE, "https://course.example.edu/fa26/", "Fall 2026", _ScriptedGroq([]))
        # Dated only by wording the site gives the item itself: "«Homework 3» Recursion (due Thu 9/24)".
        self.assertEqual([(a["title"], a["due"]) for a in assignments],
                         [("Homework 3", "2026-09-24"), ("Homework 1 Part 2", "2026-09-25"), ("Homework 4", None)])

    def test_items_without_their_own_date_do_not_take_the_class_date(self):
        # Like cs61a.org: graded work states its own due date, so a lecture row's date is
        # the day of class. A quiz there has no stated date; an exam is held that day.
        page = """
        <html><body><main><table>
          <tr><td>Tue, Sep 08</td><td><b class="label">QUIZ 1</b> Functions
              <b class="label">Lab 2</b> <a href="/labs/lab02/">HOFs (due Wed 9/9)</a></td></tr>
          <tr><td>Mon, Sep 14</td><td><b class="label">Exam</b> Midterm 1 (8pm-9pm)
              <b class="label">Homework 3</b> <a href="/hw/hw03/">Recursion (due Thu 9/24)</a></td></tr>
          <tr><td>Mon, Oct 05</td><td><b class="label">Exam</b> Midterm 2 (in the CBTF, Mon 10/5 - Fri 10/9)
              <b class="label">Lab 5</b> <a href="/labs/lab05/">Trees (due Wed 10/7)</a></td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 1, "title": "Quiz 1", "due": "2026-09-08", "date_text": "Tue, Sep 08", "link": ""},
            {"line": 1, "title": "Lab 2", "due": "2026-09-09", "date_text": "due Wed 9/9", "link": "/labs/lab02/"},
            {"line": 2, "title": "Midterm 1", "due": "2026-09-14", "date_text": "Mon, Sep 14", "link": ""},
            {"line": 2, "title": "Homework 3", "due": "2026-09-24", "date_text": "due Thu 9/24", "link": "/hw/hw03/"},
            {"line": 3, "title": "Midterm 2", "due": "2026-10-09", "date_text": "Mon 10/5 - Fri 10/9", "link": ""},
            # Cited one line off: its own entry is the line that names it.
            {"line": 2, "title": "Lab 5", "due": "2026-10-07", "date_text": "due Wed 10/7", "link": ""},
        ])

        assignments = _read(page, "https://cs61a.example.org/fa26/", "Fall 2026", client)

        self.assertEqual([(a["title"], a["due"]) for a in assignments], [
            ("Quiz 1", None), ("Lab 2", "2026-09-09"), ("Midterm 1", "2026-09-14"),
            ("Homework 3", "2026-09-24"), ("Midterm 2", "2026-10-09"), ("Lab 5", "2026-10-07"),
        ])

    def test_bare_due_entries_take_the_date_of_the_day_heading_above(self):
        # Like eecs189.org: each day is a heading, and its entries are listed below it.
        page = """
        <html><body><main>
          <h3>Fri Sep 4</h3><div><span class="label">Homework 1</span></div>
          <h3>Thu Sep 17</h3><div><span class="label">Lecture 7</span> <a href="/lec/7/">Regularization</a></div>
          <h3>Fri Sep 18</h3><div><span class="label">Homework 1 Part 1 due</span></div>
          <h3>Fri Sep 25</h3><div><span class="label">Homework 2</span></div>
          <div><span class="label">Homework 1 Part 2 due</span></div>
          <h3>Fri Oct 2</h3><div><span class="label">Homework 2 due</span></div>
        </main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 6, "title": "Homework 1 Part 1", "due": None, "date_text": "", "link": ""},
            {"line": 9, "title": "Homework 1 Part 2", "due": None, "date_text": "", "link": ""},
            # The release line of work due in parts.
            {"line": 2, "title": "Homework 1", "due": None, "date_text": "", "link": ""},
            # The release line read with its heading's date: the page's "Homework 2 due" decides.
            {"line": 8, "title": "Homework 2", "due": "2026-09-25", "date_text": "Fri Sep 25", "link": ""},
        ])

        assignments = _read(page, "https://eecs189.example.org/fa26/", "Fall 2026", client)

        # Homework 1's release line goes: its deadlines are its two parts.
        self.assertEqual([(a["title"], a["due"]) for a in assignments], [
            ("Homework 1 Part 1", "2026-09-18"), ("Homework 1 Part 2", "2026-09-25"),
            ("Homework 2", "2026-10-02"),
        ])

    def test_undated_exam_entries_take_the_date_of_the_day_heading_above(self):
        # Like eecs189.org: the exam's entry gives only its time.
        page = """
        <html><body><main>
          <h3>Mon Oct 19</h3><div><span class="label">Midterm Review</span> Midterm Review</div>
          <h3>Tue Oct 20</h3><div><span class="label">Midterm Exam</span> Midterm (5:00-6:30 PM)</div>
          <h3>Thu Dec 17</h3><div><span class="label">Final Exam</span> Final (11:30 AM - 2:30 PM, cumulative)</div>
        </main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 4, "title": "Midterm Exam", "due": None, "date_text": "", "link": ""},
            {"line": 6, "title": "Final Exam", "due": None, "date_text": "", "link": ""},
        ])

        assignments = _read(page, "https://eecs189.example.org/fa26/", "Fall 2026", client)

        self.assertEqual([(a["title"], a["due"]) for a in assignments],
                         [("Midterm Exam", "2026-10-20"), ("Final Exam", "2026-12-17")])

    def test_cells_styled_like_a_numbered_item_are_named_after_it(self):
        # Like cs162.org: each project's cells share a color (a class here), and only the
        # release names the project. Homework cells say "HW 4 Due" on their own row.
        page = """
        <html><body><main><table>
          <tr><td>Sat 09/12</td><td class="hw1"></td><td class="proj2"><a href="/proj1/">Release Project 1: User Programs</a></td></tr>
          <tr><td>Sun 09/20</td><td class="hw1">HW 1 Due</td><td class="proj2">Design Document Due</td></tr>
          <tr><td>Thu 10/08</td><td></td><td class="proj2">Code and Final Report Due</td></tr>
          <tr><td>Tue 10/27</td><td class="hw5">Release HW5: Map Reduce</td><td></td></tr>
          <tr><td>Thu 10/29</td><td class="hw4">HW 4 Due</td><td></td></tr>
          <tr><td>Fri 11/13</td><td class="hw5">Checkpoint Deadline (C version)</td><td></td></tr>
          <tr><td>Fri 11/20</td><td class="hw5">HW 5 Due</td><td></td></tr>
        </table></main></body></html>
        """
        lines, _links = page_lines(page, "https://cs162.example.org/")
        self.assertEqual(lines[1], "Sun 09/20 | HW 1 Due | Project 1: Design Document Due")
        self.assertEqual(lines[2], "Thu 10/08 | | Project 1: Code and Final Report Due")

        client = _ScriptedGroq([
            {"line": 2, "title": "Homework 1", "due": "2026-09-20", "date_text": "Sun 09/20", "link": ""},
            {"line": 2, "title": "Project 1 Design Document", "due": "2026-09-20", "date_text": "Sun 09/20", "link": ""},
            # Read with the date of a row above: the row that says "HW 4 Due" decides.
            {"line": 5, "title": "Homework 4", "due": "2026-10-27", "date_text": "Tue 10/27", "link": ""},
            # Two names for one cell's deadline: the specific one stays.
            {"line": 3, "title": "Project 1", "due": "2026-10-08", "date_text": "Thu 10/08", "link": ""},
            {"line": 3, "title": "Project 1 Code and Final Report", "due": "2026-10-08", "date_text": "Thu 10/08", "link": ""},
            {"line": 7, "title": "Homework 5", "due": "2026-11-20", "date_text": "Fri 11/20", "link": ""},
            # The model names the checkpoint as some other item; the cell's label decides.
            {"line": 6, "title": "Lab 5", "due": "2026-11-13", "date_text": "Fri 11/13", "link": ""},
        ])

        assignments = _read(page, "https://cs162.example.org/", "Fall 2026", client)

        self.assertEqual(sorted((a["title"], a["due"]) for a in assignments), [
            ("Homework 1", "2026-09-20"), ("Homework 4", "2026-10-29"), ("Homework 5", "2026-11-20"),
            ("Homework 5 Checkpoint", "2026-11-13"),
            ("Project 1 Code and Final Report", "2026-10-08"), ("Project 1 Design Document", "2026-09-20"),
        ])

    def test_table_rows_date_the_deadlines_and_exams_they_name(self):
        # Like cs10.org: "Proj 2 Due QUEST 2" in one cell, previews and practice beside them.
        page = """
        <html><body><main>
          <p>Lab 801L: Monday, Wednesday @ 4-6 PM in SOCS 110</p>
          <table>
          <tr><th>Date</th><th>Lecture</th><th>Assignment / Exam</th></tr>
          <tr><td>Fri 9/25</td><td>Talk 5. Quest 1 Preview</td><td>QUEST 1</td></tr>
          <tr><td>Fri 10/2</td><td>Talk 6. Quest 1 Review (open until Sun 10/4)</td><td>Proj 2 Due QUEST 2</td></tr>
          <tr><td>Wed 10/28</td><td>Lec 18. OOP</td><td>Proj 4 Research Document Due</td></tr>
          <tr><td>Fri 11/13</td><td>Talk 12</td><td>Final Project Meetings Proj 4 Artifact Due</td></tr>
          <tr><td>Mon 12/7</td><td>POSTTERM 2 REVIEW</td><td>Final Project Due</td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 1, "title": "Lab 801L", "due": None, "date_text": "", "link": ""},
            {"line": 4, "title": "Quest 1", "due": None, "date_text": "", "link": ""},
            # A date from another row is replaced by the row that says "Proj 2 Due".
            {"line": 3, "title": "Project 2", "due": "2026-09-25", "date_text": "Fri 9/25", "link": ""},
            {"line": 5, "title": "Project 4 Research Document", "due": "2026-10-30", "date_text": "Due", "link": ""},
            # A bare name for a row that gives Project 4's part deadlines.
            {"line": 6, "title": "Project 4", "due": "2026-11-13", "date_text": "Fri 11/13", "link": ""},
            # One exam window: the schedule's first day and the announcement's last day.
            {"line": 4, "title": "Quest 2", "due": "2026-10-02", "date_text": "Fri 10/2", "link": ""},
            {"line": 4, "title": "Quest 2", "due": "2026-10-04", "date_text": "Sun 10/4", "link": ""},
        ])

        assignments = _read(page, "https://cs10.example.org/fa26/", "Fall 2026", client)

        self.assertEqual(sorted((a["title"], a["due"]) for a in assignments), [
            ("Final Project", "2026-12-07"),
            ("Project 2", "2026-10-02"),
            ("Project 4 Artifact", "2026-11-13"),
            ("Project 4 Research Document", "2026-10-28"),
            ("Quest 1", "2026-09-25"),
            ("Quest 2", "2026-10-04"),
        ])

    def test_hidden_announcements_are_not_read(self):
        page = """
        <html><body><main>
          <div class="announcement" data-date="2026-11-18"><p>Midterm 2 Retakes 11/5-11/6 &amp; 11/9-11/10</p></div>
          <div class="announcement" style="display: none;"><div><p>Midterm 2 Retakes 11/5-11/6</p></div>
            <p>Quiz 1 is this Friday 9/4</p></div>
          <div class="week" style="display: none;"><p>Lab 1 due 9/2</p></div>
        </main></body></html>
        """
        lines, _links = page_lines(page, "https://cs61a.example.org/fa26/")
        # The visible announcement stays; a hidden schedule week is not an announcement and stays too.
        self.assertEqual(lines, ["Midterm 2 Retakes 11/5-11/6 & 11/9-11/10", "Lab 1 due 9/2"])

    def test_numbered_exams_the_model_missed_are_added_with_the_site_due_date(self):
        # Like cs61c.org: a long row the model passed over. A retake is its own sitting,
        # so listing "Midterm Part 2 Retake" does not stand for "Midterm Part 2".
        page = """
        <html><body><main><table>
          <tr><td>Mon 11/9</td><td><a href="/exams/exam04/">Midterm Part 2: 11/9-11/13</a> <span class="badge">Due 11/13</span></td>
              <td><a href="/disc/disc11/">Discussion 11</a></td></tr>
          <tr><td>Thu 11/19</td><td><a href="/exams/exam05/">Midterm Part 2 Retake: 11/19-11/20</a> <span class="badge">Due 11/20</span></td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 2, "title": "Midterm Part II Retake", "due": "2026-11-20", "date_text": "Due 11/20",
             "link": "/exams/exam05/"},
        ])

        assignments = _read(page, "https://cs61c.example.org/fa26/", "Fall 2026", client)

        self.assertEqual([(a["title"], a["due"], a["html_url"]) for a in assignments], [
            ("Midterm Part 2 Retake", "2026-11-20", "https://cs61c.example.org/exams/exam05/"),
            ("Midterm Part 2", "2026-11-13", "https://cs61c.example.org/exams/exam04/"),
        ])

    def test_lines_naming_graded_work_with_no_item_are_read_again(self):
        page = """
        <html><body><main><table>
          <tr><td>Fri 10/23</td><td>Practice Midterm</td><td>MIDTERM 1</td></tr>
          <tr><td>Mon 10/26</td><td><a href="/lec/20/">Lecture 20</a></td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq(
            [],  # the first reading passes over the exam row
            [{"line": 1, "title": "Midterm 1", "due": "2026-10-23", "date_text": "Fri 10/23", "link": ""}],
        )

        assignments = _read(page, "https://cs10.example.org/fa26/", "Fall 2026", client)

        self.assertEqual([(a["title"], a["due"]) for a in assignments], [("Midterm 1", "2026-10-23")])
        self.assertEqual(len(client.requests), 2)
        recheck = json.loads(client.requests[1]["messages"][1]["content"])
        self.assertIn("passed over in a first reading", recheck["note"])
        self.assertEqual(recheck["lines"], "--- START ---\n1: Fri 10/23 | Practice Midterm | MIDTERM 1")

    def test_part_numerals_and_spacing_name_one_item(self):
        client = _ScriptedGroq([
            {"line": 1, "title": "Project 2 A", "due": None, "date_text": "", "link": ""},
            {"line": 1, "title": "Midterm Part II", "due": None, "date_text": "", "link": ""},
        ])
        assignments = _read("<p>Project 2A and Midterm Part 2</p>", "https://x.example.org/", "Fall 2026", client)
        self.assertEqual([a["title"] for a in assignments], ["Project 2A", "Midterm Part 2"])

    def test_invalid_model_json_is_an_error(self):
        class BadJson(_ScriptedGroq):
            def create(self, **kwargs):
                message = type("Message", (), {"content": "not json"})()
                choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
                return type("Completion", (), {"choices": [choice]})()

        with self.assertRaisesRegex(RuntimeError, "WEBSITE_IMPORT_LLM_ERROR"):
            _read(SCHEDULE_PAGE, "https://course.example.edu/", "Fall 2026", BadJson())


class _ProviderError(Exception):
    def __init__(self, status_code, code="", message="", headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.response = type("Response", (), {"headers": headers or {}})()


class ImportTests(unittest.TestCase):
    URL = "https://cs61a.org/fa26/"

    def run_import(self, client, term="Fall 2026", page=SCHEDULE_PAGE, sleep=lambda _s: None):
        with (
            patch("website_import.fetch_page", return_value=(page, self.URL)),
            patch.dict("website_import.os.environ", {}, clear=True),
            patch("website_import._log"),
        ):
            return import_course_website(self.URL, term, client=client, sleep=sleep)

    def test_import_output_matches_what_the_server_expects(self):
        client = _ScriptedGroq([{"line": 1, "title": "Homework 3", "due": "2026-09-24",
                                 "date_text": "due Thu 9/24", "link": "/hw/hw03/"}])
        imported = self.run_import(client)
        self.assertEqual(imported["course_url"], self.URL)
        self.assertEqual((imported["pages_crawled"], imported["pages_skipped"]), (1, 0))
        self.assertEqual(imported["candidates_reviewed"], 1)
        self.assertEqual([(a["title"], a["due"]) for a in imported["assignments"]],
                         [("Homework 3", "2026-09-24"), ("Homework 1 Part 2", "2026-09-25"), ("Homework 4", None)])
        self.assertEqual(len(client.requests), 1)

    def test_the_website_decides_when_the_course_runs_over_a_mistyped_term(self):
        page = """
        <html><head><title>Home | CS 61A Fall 2026</title></head><body><main><table>
          <tr><td>Thu 9/24</td><td><a href="/hw/hw03/">Homework 3</a> (due Thu 9/24)</td></tr>
        </table></main></body></html>
        """
        client = _ScriptedGroq([
            {"line": 1, "title": "Homework 3", "due": "2026-09-24", "date_text": "due Thu 9/24", "link": "/hw/hw03/"},
        ])
        imported = self.run_import(client, term="Spring 2029", page=page)
        self.assertEqual(imported["website_term"], "Fall 2026")
        self.assertEqual([(a["title"], a["due"]) for a in imported["assignments"]], [("Homework 3", "2026-09-24")])
        self.assertEqual(json.loads(client.requests[0]["messages"][1]["content"])["course_term"], "Fall 2026")

    def test_groq_auth_and_model_errors_are_distinguished(self):
        for status_code, marker, detail in (
            (401, "WEBSITE_IMPORT_GROQ_AUTH_ERROR:", "invalid_api_key"),
            (404, "WEBSITE_IMPORT_GROQ_MODEL_ERROR:", "model_not_found"),
        ):
            with self.subTest(status_code=status_code):
                client = _ScriptedGroq(_ProviderError(status_code, detail, "provider response"))
                with self.assertRaisesRegex(RuntimeError, marker) as raised:
                    self.run_import(client)
                self.assertIn(f"HTTP {status_code}", str(raised.exception))
                self.assertIn(detail, str(raised.exception))

    def test_groq_rate_limit_retries_after_provider_delay(self):
        delays = []
        client = _ScriptedGroq(
            _ProviderError(429, "rate_limit_exceeded", "Rate limit exceeded", {"retry-after": "5"}),
            [],
        )
        imported = self.run_import(client, sleep=delays.append)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(delays, [5])
        self.assertEqual(len(imported["assignments"]), 3)  # the safety net's numbered items

    def test_groq_daily_quota_returns_reset_wait_without_retries(self):
        delays = []
        client = _ScriptedGroq(_ProviderError(
            429, "rate_limit_exceeded",
            "Rate limit reached on tokens per day. Please retry after 1278 seconds.",
        ))
        with self.assertRaisesRegex(RuntimeError, r"WEBSITE_IMPORT_DAILY_QUOTA_ERROR:.*1278 seconds"):
            self.run_import(client, sleep=delays.append)
        self.assertEqual(delays, [])

    def test_groq_stops_before_a_request_that_cannot_finish_in_the_time_budget(self):
        lines, links = page_lines(SCHEDULE_PAGE, self.URL)
        client = _ScriptedGroq()
        with self.assertRaisesRegex(RuntimeError, "WEBSITE_IMPORT_TIME_BUDGET_ERROR"):
            extract_assignments_from_page(lines, links, self.URL, "Fall 2026", client, lambda _s: None,
                                          deadline=110, clock=lambda: 100)
        self.assertEqual(client.requests, [])

    def test_groq_rate_limit_wait_past_the_time_budget_fails_without_waiting(self):
        lines, links = page_lines(SCHEDULE_PAGE, self.URL)
        delays = []
        client = _ScriptedGroq(_ProviderError(429, "rate_limit_exceeded", "Rate limit exceeded",
                                              {"retry-after": "60"}))
        with self.assertRaisesRegex(RuntimeError, "WEBSITE_IMPORT_RATE_LIMIT_ERROR"):
            extract_assignments_from_page(lines, links, self.URL, "Fall 2026", client, delays.append,
                                          deadline=130, clock=lambda: 100)
        self.assertEqual(delays, [])


ANTS_PAGE = """<html><head><title>CS 61A Fall 2026</title></head><body>
<p>Ants checkpoint due Friday 10/16</p>
<p>Checkpoint 2 due Wednesday 10/21</p>
<table><tr><td>Mon, Oct 12</td><td><span class="label">Project 3</span>
  <a href="/fa26/projects/ants/">Ants Vs. SomeBees (due Fri 10/23; checkpoint 1 Fri 10/16; checkpoint 2 Wed 10/21)</a>
  <span class="label">Contest</span> <a href="/fa26/projects/hog_contest/">Hog Strategy Contest (due Mon 10/12)</a></td></tr></table>
</body></html>"""
ANTS_ITEMS = [
    {"line": 1, "title": "Ants Checkpoint", "due": "2026-10-16", "date_text": "Friday 10/16", "link": ""},
    {"line": 2, "title": "Checkpoint 2", "due": "2026-10-21", "date_text": "Wednesday 10/21", "link": ""},
    {"line": 3, "title": "Project 3", "due": "2026-10-23", "date_text": "due Fri 10/23", "link": "/fa26/projects/ants/"},
    {"line": 3, "title": "Hog Strategy Contest", "due": "2026-10-12", "date_text": "due Mon 10/12",
     "link": "/fa26/projects/hog_contest/"},
]


class NamingTests(unittest.TestCase):
    """The naming call sees every item and the page's numbered items at once."""

    def run_import(self, client):
        with (
            patch("website_import.fetch_page", return_value=(ANTS_PAGE, "https://cs61a.org/fa26/")),
            patch("website_import._log"),
        ):
            imported = import_course_website("https://cs61a.org/fa26/", "Fall 2026", client=client,
                                             sleep=lambda _s: None)
        self.assertTrue(all("_line" not in a for a in imported["assignments"]))
        return sorted((a["title"], a["due"]) for a in imported["assignments"])

    def test_the_model_names_topic_items_from_the_whole_page(self):
        client = _ScriptedGroq(ANTS_ITEMS, renames=[
            {"id": "i1", "title": "Project 3 Checkpoint 1"},
            {"id": "i2", "title": "Project 3 Checkpoint 2"},
        ])
        self.assertEqual(self.run_import(client), [
            ("Hog Strategy Contest", "2026-10-12"),
            ("Project 3", "2026-10-23"),
            ("Project 3 Checkpoint 1", "2026-10-16"),
            ("Project 3 Checkpoint 2", "2026-10-21"),
        ])
        sent = json.loads(client.naming_requests[0]["messages"][1]["content"])
        self.assertIn("Ants Vs. SomeBees", " ".join(sent["numbered_items"]["Project 3"]))
        self.assertEqual(sent["items"][0], {"id": "i1", "title": "Ants Checkpoint", "due": "2026-10-16",
                                            "line": "Ants checkpoint due Friday 10/16"})

    def test_renames_that_would_merge_different_deadlines_or_invent_items_are_refused(self):
        client = _ScriptedGroq(ANTS_ITEMS, renames=[
            # Both checkpoints given one name: the second is refused, the first kept.
            {"id": "i1", "title": "Project 3 Checkpoint"},
            {"id": "i2", "title": "Project 3 Checkpoint"},
            # Not a numbered item on this page.
            {"id": "i4", "title": "Project 9"},
            # Would give the contest the title of a deadline on another day.
            {"id": "i4", "title": "Project 3"},
            {"id": "i99", "title": "Project 3"},
        ])
        titles = self.run_import(client)
        self.assertIn(("Hog Strategy Contest", "2026-10-12"), titles)
        checkpoint_titles = [title for title, _due in titles if "Checkpoint" in title]
        self.assertEqual(len(checkpoint_titles), len(set(checkpoint_titles)))
        # The code step still numbers them from the page's checkpoint dates.
        self.assertEqual(sorted(checkpoint_titles), ["Project 3 Checkpoint 1", "Project 3 Checkpoint 2"])

    def test_a_failed_naming_call_does_not_fail_the_import(self):
        client = _ScriptedGroq(ANTS_ITEMS, renames=_ProviderError(500, "server_error", "boom"))
        titles = self.run_import(client)
        self.assertEqual(len(client.naming_requests), 1)
        self.assertIn(("Project 3", "2026-10-23"), titles)


class MergeSameDeliverableTests(unittest.TestCase):
    """One deadline listed under several names is merged using what the page says."""

    PAGE = "https://cs.example.edu/fa26/"
    HTML = """<html><body><table>
      <tr><td>Mon, Sep 21</td><td><span class="label">Lab 3</span> <a href="labs/lab03/">Lists (due Wed 9/23)</a>
        <span class="label">Project 2</span> <a href="projects/cats/">Computer Aided Typing Software (due Fri 10/2; checkpoint Mon 9/28)</a></td></tr>
      <tr><td>Mon, Oct 12</td><td><span class="label">Project 3</span> <a href="projects/ants/">Ants Vs. SomeBees (due Fri 10/23; checkpoint 1 Fri 10/16; checkpoint 2 Wed 10/21)</a>
        <span class="label">Contest</span> <a href="projects/hog_contest/">Hog Strategy Contest (due Mon 10/12)</a></td></tr>
      <tr><td>Fri, Sep 04</td><td><span class="label">Project 1</span> <a href="projects/hog/">The Game of Hog (due Thu 9/17)</a></td></tr>
    </table><p>Cats project due Friday 10/2</p></body></html>"""

    def item(self, title, due, url=None):
        return {"id": title + str(due), "title": title, "due": due,
                "html_url": url or self.PAGE, "resources": []}

    def merge(self, items):
        lines, links = page_lines(self.HTML, self.PAGE)
        with patch("website_import._log"):
            return _merge_same_deliverable(items, lines, links, self.PAGE)

    def merged(self, items):
        return sorted((a["title"], a["due"], a["html_url"]) for a in self.merge(items))

    def test_topic_names_join_their_numbered_item(self):
        result = self.merged([
            self.item("Project 2", "2026-10-02", self.PAGE + "projects/cats/"),
            self.item("Cats project", "2026-10-02"),
            self.item("Project Cats", None),
            self.item("Ants vs SomeBees", "2026-10-23"),
        ])
        self.assertEqual(result, [
            ("Project 2", "2026-10-02", self.PAGE + "projects/cats/"),
            ("Project 3", "2026-10-23", self.PAGE),
        ])

    def test_checkpoints_join_by_name_or_by_the_date_the_page_gives_them(self):
        result = self.merged([
            self.item("Project 3 Checkpoint 1", "2026-10-16", self.PAGE + "projects/ants/"),
            self.item("Ants checkpoint 1", "2026-10-16"),
            self.item("Checkpoint", "2026-09-28"),
        ])
        self.assertEqual(result, [
            ("Project 2 Checkpoint", "2026-09-28", self.PAGE),
            ("Project 3 Checkpoint 1", "2026-10-16", self.PAGE + "projects/ants/"),
        ])

    def test_checkpoints_without_a_number_take_the_page_number_for_their_date(self):
        result = self.merged([
            self.item("Project 3 Checkpoint", "2026-10-16"),
            self.item("Project 3 Checkpoint", "2026-10-21"),
            self.item("Checkpoint", "2026-10-21"),
            self.item("Project 3 Checkpoint 2", "2026-10-21", self.PAGE + "projects/ants/"),
        ])
        self.assertEqual(result, [
            ("Project 3 Checkpoint 1", "2026-10-16", self.PAGE),
            ("Project 3 Checkpoint 2", "2026-10-21", self.PAGE + "projects/ants/"),
        ])

    def test_distinct_work_and_different_dates_are_kept(self):
        result = self.merged([
            self.item("Project 1", "2026-09-17"),
            self.item("Hog Strategy Contest", "2026-10-12"),
            self.item("Lab 3", "2026-09-23"),
            self.item("Lab 3", "2026-09-24"),
            self.item("Checkpoint", "2026-11-30"),  # no part of any item is due that day
        ])
        self.assertEqual([title for title, _due, _url in result], [
            "Checkpoint", "Hog Strategy Contest", "Lab 3", "Lab 3", "Project 1",
        ])

    def test_same_title_keeps_the_linked_dated_copy_and_its_resources(self):
        linked = self.item("Homework 5", "2026-10-15", self.PAGE + "hw/hw05/")
        bare = self.item("Homework 5", "2026-10-15")
        bare["resources"] = [{"resource_name": "Solutions", "resource_type": "Link", "link": "https://x.edu/s"}]
        result = self.merge([bare, linked, self.item("Homework 5", None)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["html_url"], self.PAGE + "hw/hw05/")
        self.assertEqual([r["link"] for r in result[0]["resources"]], ["https://x.edu/s"])


if __name__ == "__main__":
    unittest.main()
