#!/usr/bin/env python3
"""Read a course website with a language model and list its deadlines for instructor review.

The page is fetched once, trimmed to numbered lines, and read by the model in parts;
code verifies the model's dates against the page and merges duplicate names.
"""

import hashlib
import html as html_lib
import ipaddress
import json
import os
import re
import socket
import sys
import time
from collections import Counter
from datetime import date
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

import requests

MAX_META_REFRESHES = 3
# Base wait before retrying a rate-limited model request (doubles each retry).
MODEL_DELAY_SECONDS = 2

MAX_PAGE_BYTES = 2_000_000


REQUEST_DELAY_SECONDS = 0.5


MAX_RATE_LIMIT_RETRIES = 2


MAX_RATE_LIMIT_WAIT_SECONDS = 120


REQUEST_TIMEOUT = (5, 15)


MAX_REDIRECTS = 5


DATE_SIGNAL = re.compile(
    r"\b(due|deadline|due date)\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?\b|"
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    re.IGNORECASE,
)


DATE_VALUE = re.compile(
    r"\b(?:(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})|"
    # "10/28-10/30" is a range, not October 28, 2010: a year is never followed by "/".
    r"(?P<month2>\d{1,2})[/-](?P<day2>\d{1,2})(?:[/-](?P<year2>(?:20)?\d{2})(?![/\d]))?|"
    r"(?P<month_name>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?\s+(?P<day3>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,?\s+(?P<year3>20\d{2}))?)\b",
    re.IGNORECASE,
)


MONTHS = {
    name.lower(): number
    for number, names in enumerate(
        (
            ("January", "Jan"), ("February", "Feb"), ("March", "Mar"),
            ("April", "Apr"), ("May",), ("June", "Jun"), ("July", "Jul"),
            ("August", "Aug"), ("September", "Sep"), ("October", "Oct"),
            ("November", "Nov"), ("December", "Dec"),
        ),
        start=1,
    )
    for name in names
}


DUE_WORD = re.compile(r"\b(due|deadline|submit by|turn in)\b", re.IGNORECASE)


TIME_OF_DAY = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.IGNORECASE)


# Fixed wall-clock budget for the whole import. The Node caller kills the script
# at 240 s, so stop early with a clear error instead of being killed mid-request.
DEFAULT_TIME_BUDGET_SECONDS = 225


GROQ_REQUEST_TIMEOUT_SECONDS = 20


# The model that reads course websites.
GROQ_MODEL = "openai/gpt-oss-120b"


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _validate_url(url):
    if len(url) > 2048:
        raise ValueError("Course website URLs must be 2048 characters or fewer.")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only public HTTP and HTTPS course websites are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Course website URLs must not contain credentials.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Course websites on non-standard ports are not supported.")
    return parsed


def _assert_public_host(url):
    parsed = _validate_url(url)
    host = parsed.hostname
    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except socket.gaierror as error:
        raise RuntimeError(f"Could not resolve course website host: {host}") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Course websites must resolve only to public IP addresses.")


def _canonical_url(url, base_url):
    absolute = urldefrag(urljoin(base_url, url))[0]
    parsed = _validate_url(absolute)
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _same_host(url, host):
    candidate_host = urlsplit(url).hostname.lower().removeprefix("www.")
    origin_host = host.lower().removeprefix("www.")
    return candidate_host == origin_host


def _read_response(response):
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_PAGE_BYTES:
        raise RuntimeError("A course website page exceeded the 2 MB size limit.")
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_PAGE_BYTES:
            raise RuntimeError("A course website page exceeded the 2 MB size limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_html(session, url, host, sleep):
    current_url = url
    for redirect_number in range(MAX_REDIRECTS + 1):
        _assert_public_host(current_url)
        try:
            response = session.get(
                current_url,
                allow_redirects=False,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "AutoRemindCourseImporter/1.0",
                },
            )
        except requests.exceptions.Timeout as error:
            raise RuntimeError(
                "WEBSITE_FETCH_ERROR: A course page request timed out."
            ) from error
        except requests.exceptions.RequestException as error:
            raise RuntimeError(
                "WEBSITE_FETCH_ERROR: Could not retrieve a course page."
            ) from error
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location or redirect_number == MAX_REDIRECTS:
                    raise RuntimeError(f"Course website exceeded {MAX_REDIRECTS} redirects.")
                next_url = _canonical_url(location, current_url)
                if not _same_host(next_url, host):
                    raise ValueError("Course website redirects to a different host.")
                current_url = next_url
                sleep(REQUEST_DELAY_SECONDS)
                continue
            if response.status_code == 404:
                return None, current_url, 0
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as error:
                status_code = getattr(error.response, "status_code", None)
                detail = f" The page returned HTTP {status_code}." if status_code else ""
                raise RuntimeError(
                    f"WEBSITE_FETCH_ERROR: A course page could not be retrieved.{detail}"
                ) from error
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and "html" not in content_type:
                return None, current_url, 0
            body = _read_response(response)
            return body.decode(response.encoding or "utf-8", errors="replace"), current_url, len(body)
        finally:
            response.close()
    raise RuntimeError("Course website redirect handling failed.")


def _year_from_term(term):
    match = re.search(r"\b(19|20)\d{2}\b", term or "")
    return int(match.group(0)) if match else None


SEASONS = {"fa": "Fall", "sp": "Spring", "su": "Summer", "wi": "Winter"}


TERM_PHRASE = re.compile(r"\b(fall|spring|summer|winter|autumn)\s+(20\d{2})\b", re.IGNORECASE)


def _address_names_term(url):
    parts = urlsplit(url or "")
    path = f"/{parts.netloc.lower().split('.')[0]}{parts.path.lower()}"
    return bool(re.search(r"(?:^|/)(fa|sp|su|wi)(\d{2})(?:/|$)", path))


def term_date_range(term, today=None):
    """(first, last) dates a term's deadlines can fall on, with generous margins."""
    today = today or date.today()
    year = _year_from_term(term)
    text = (term or "").lower()
    if year and re.search(r"\bfall\b|\bautumn\b", text):
        return date(year, 7, 15), date(year + 1, 1, 31)
    if year and re.search(r"\bspring\b", text):
        return date(year - 1, 12, 15), date(year, 6, 15)
    if year and re.search(r"\bsummer\b", text):
        return date(year, 5, 1), date(year, 9, 15)
    if year and re.search(r"\bwinter\b", text):
        return date(year - 1, 11, 15), date(year, 3, 31)
    if year:
        return date(year, 1, 1), date(year + 1, 1, 31)
    return date.fromordinal(today.toordinal() - 200), date.fromordinal(today.toordinal() + 280)


def _effective_term(term, url, today=None):
    """A term that includes a year, so dates like "Due 10/30" can be placed.

    Uses the instructor's term when it has a year; otherwise the course address
    ("cs61c.org/fa26/" -> "Fall 2026"); otherwise the current year.
    """
    term = clean_text(term)
    if _year_from_term(term):
        return term
    parts = urlsplit(url or "")
    path = f"/{parts.netloc.lower().split('.')[0]}{parts.path.lower()}"
    match = re.search(r"(?:^|/)(fa|sp|su|wi)(\d{2})(?:/|$)", path)
    if match:
        inferred = f"{SEASONS[match.group(1)]} 20{match.group(2)}"
    else:
        year = re.search(r"(?:^|[/\-_])(20\d{2})(?:[/\-_]|$)", path)
        inferred = year.group(1) if year else str((today or date.today()).year)
    if not term or term.casefold() in inferred.casefold():
        return inferred
    return f"{term} ({inferred})"


def _date_parts(groups, term):
    """Convert a DATE_VALUE match's groups to (year, month, day); year may be None."""
    if groups["year"]:
        return int(groups["year"]), int(groups["month"]), int(groups["day"])
    if groups["month2"]:
        raw_year = groups["year2"]
        year = int(raw_year) + (2000 if len(raw_year) == 2 else 0) if raw_year else _year_from_term(term)
        return year, int(groups["month2"]), int(groups["day2"])
    month = MONTHS[groups["month_name"].lower().rstrip(".")]
    year = int(groups["year3"]) if groups["year3"] else _year_from_term(term)
    return year, month, int(groups["day3"])


def _rate_limit_retry_delay(error, retry_number):
    detail = clean_text(
        getattr(error, "message", "") or str(error)
    )
    retry_match = re.search(r"retry after\s+(\d+)\s+seconds", detail, re.IGNORECASE)
    if retry_match:
        return int(retry_match.group(1))

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    retry_after = headers.get("retry-after") if headers else None
    if retry_after is not None:
        try:
            return max(1, int(float(retry_after)))
        except (TypeError, ValueError):
            pass

    reset_tokens = headers.get("x-ratelimit-reset-tokens") if headers else None
    if reset_tokens:
        duration = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)", reset_tokens.strip())
        if duration:
            value = float(duration.group(1))
            multiplier = {"ms": 0.001, "s": 1, "m": 60}[duration.group(2)]
            return max(1, int(value * multiplier + 0.999))

    return MODEL_DELAY_SECONDS * (2 ** (retry_number + 1))


def _is_daily_rate_limit(error):
    detail = clean_text(
        getattr(error, "message", "") or str(error)
    ).casefold()
    return "tokens per day" in detail or ("tpm" in detail and "per day" in detail)


def _is_json_output_limit_error(error):
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return False
    details = body.get("error", body)
    if not isinstance(details, dict):
        return False
    code = getattr(error, "code", None) or details.get("code")
    generation = clean_text(details.get("failed_generation", ""))
    message = clean_text(details.get("message", ""))
    return (
        code == "json_validate_failed"
        and "max completion token" in f"{message} {generation}".casefold()
    )


BRACKETED_SEGMENT = re.compile(r"\s*[\(\[][^()\[\]]*[\)\]]")


TITLE_STATUS_WORDS = re.compile(
    r"\b(checkpoint|released?|posted|extended|late|closed|open|new)\b", re.IGNORECASE,
)


# A separator followed only by a date (and optional weekday) at the end of a label.
TRAILING_DATE = re.compile(
    r"(?:\s+[-\u2013\u2014|]\s+|:\s+|,\s+)"
    r"(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
    r"(?:" + DATE_VALUE.pattern + r")\s*$",
    re.IGNORECASE,
)


DATE_TIME_WORDS = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"|\b(?:am|pm|pt|pst|pdt|et|est|edt|ct|noon|midnight|to|and|through|thru|due)\b"
    r"|(?<=\d)(?:am|pm)\b",
    re.IGNORECASE,
)


# Tail after a separator; a colon inside a time ("11:30AM") does not end it.
DATE_TAIL = re.compile(
    r"(?:\s*[:|,]\s+|\s+[-\u2013\u2014]\s+)(?P<tail>(?:[^:|]|(?<=\d):(?=\d))*)$"
)


def _is_date_only(text):
    """"10/28-10/30", "12/14 11:30AM", "Wed Nov 4, 8-10 PM" -> True; "Lists" -> False."""
    return bool(re.search(r"\d", text)) and not re.search(
        r"[A-Za-z]", DATE_TIME_WORDS.sub(" ", text)
    )


def _strip_date_tail(title):
    while True:
        match = DATE_TAIL.search(title)
        if not match or not _is_date_only(match.group("tail")):
            return title
        title = title[: match.start()]


def _clean_title(label):
    """Strip due dates, deadlines, and status notes so only the assignment name remains.

    "Functions (due Thu 9/3)" -> "Functions"
    "The Game of Hog (due Thu 9/17; checkpoint Thu 9/10)" -> "The Game of Hog"
    "Homework 1 - Due 9/15" -> "Homework 1"
    """
    original = clean_text(label)

    def drop_dated_segment(match):
        inner = match.group(0)
        if (
            DATE_SIGNAL.search(inner)
            or DUE_WORD.search(inner)
            or TITLE_STATUS_WORDS.search(inner)
            or TIME_OF_DAY.search(inner)
        ):
            return ""
        return inner

    title = BRACKETED_SEGMENT.sub(drop_dated_segment, original)
    # Trailing "- Due 9/15", ": due Thu 9/3", ", deadline Friday" and similar.
    due_tail = re.search(
        r"(?:[-\u2013\u2014:,|]\s*|\s+)\b(?:due|deadline|submit by)\b.*$", title, re.IGNORECASE,
    )
    if due_tail:
        title = title[: due_tail.start()]
    # Trailing bare date after a separator: "Homework 1 - 9/15", "Lab 2: Sep 8",
    # including ranges and times: "Quest: 9/16-9/18", "Final Exam: 12/14 11:30AM - 2:30PM PT".
    title = TRAILING_DATE.sub("", title)
    title = _strip_date_tail(title)
    title = clean_text(title).strip(" -\u2013\u2014:,|;")
    return title or original


# Kinds of graded work and how sites abbreviate them, most specific first.
TITLE_KINDS = (
    ("Mini-Midterm", r"mini[- ]?midterm"),
    ("Midterm", r"midterm|mt"),
    ("Homework", r"homework|hw"),
    ("Discussion", r"discussion|disc"),
    ("Lab", r"lab"),
    ("Project", r"project|proj"),
    ("Quiz", r"quiz"),
    ("Problem Set", r"problem[- ]?set|pset"),
    ("Worksheet", r"worksheet"),
    ("Survey", r"survey"),
    ("Assignment", r"assignment"),
    ("Exam", r"exam"),
    ("Quest", r"quest"),
    ("Postterm", r"post[- ]?term"),
)


KIND_WITH_NUMBER = re.compile(
    r"\b(?P<kind>" + "|".join(f"(?:{pattern})" for _, pattern in TITLE_KINDS) + r")"
    r"(?P<part>\s+(?:part|pt\.?))?[\s\-#_]*0*(?P<number>\d+[a-z]?)\b",
    re.IGNORECASE,
)


TITLE_QUALIFIER = re.compile(
    r"\b(part\s*\d+[a-z]?|retake|make-?up|alternate|redo|extra credit|checkpoint\s*\d*[a-z]?)\b",
    re.IGNORECASE,
)


def _kind_name(raw_kind):
    for name, pattern in TITLE_KINDS:
        if re.fullmatch(pattern, raw_kind, re.IGNORECASE):
            return name
    return raw_kind.capitalize()


def _canonical_title(text):
    """"Coding HW3: IntLists" -> "Homework 3"; "Midterm 2 Retake (Thu 11/5)" -> "Midterm 2 Retake"."""
    text = clean_text(text)
    match = KIND_WITH_NUMBER.search(text)
    if match:
        part = " Part" if match.group("part") else ""
        title = f"{_kind_name(match.group('kind'))}{part} {match.group('number').upper()}"
        rest = BRACKETED_SEGMENT.sub("", text[match.end():])
        qualifier = TITLE_QUALIFIER.search(rest)
        if qualifier:
            title += " " + clean_text(qualifier.group(0)).title()
        return title
    if re.search(r"\bfinal exam\b", text, re.IGNORECASE):
        return "Final Exam"
    return None


EXAM_NAME = re.compile(
    r"(?:mini[- ]?)?midterm(?:\s+exam)?(?:\s+(?:retake|make-?up))?|final(?:\s+exam)?(?:\s+(?:retake|make-?up))?",
    re.IGNORECASE,
)


def _is_exam_name(text):
    """A bare exam name such as "Midterm Exam" or "Final (11:30 AM - 2:30 PM)"."""
    return bool(text) and bool(EXAM_NAME.fullmatch(_clean_title(text)))


class _RequestTooLarge(Exception):
    """Groq could not take or finish this request; the caller should send less."""

    def __init__(self, single_item_error):
        super().__init__(single_item_error)
        self.single_item_error = single_item_error


def _groq_request(client, system_prompt, user_content, *, sleep, deadline, clock,
                  max_completion_tokens):
    """One JSON-mode Groq call with rate-limit retries and classified errors.

    Raises _RequestTooLarge when the request or its answer is too big (so the caller
    can split its input), and RuntimeError with a WEBSITE_IMPORT_* marker otherwise.
    """
    model = GROQ_MODEL
    rate_limit_retries = 0
    while True:
        try:
            return client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                reasoning_effort="low",
                max_completion_tokens=max_completion_tokens,
            )
        except Exception as error:
            status_code = getattr(error, "status_code", None)
            error_code = clean_text(getattr(error, "code", ""))[:80]
            detail = clean_text(getattr(error, "message", "") or str(error))[:240]
            diagnostic = f"{type(error).__name__}"
            if status_code is not None:
                diagnostic += f" (HTTP {status_code}"
                if error_code:
                    diagnostic += f", {error_code}"
                diagnostic += ")"
            if detail:
                diagnostic += f": {detail}"

            if status_code == 429:
                retry_delay = _rate_limit_retry_delay(error, rate_limit_retries)
                if _is_daily_rate_limit(error):
                    raise RuntimeError(
                        "WEBSITE_IMPORT_DAILY_QUOTA_ERROR: Groq's daily token quota "
                        f"is exhausted. Retry after {retry_delay} seconds or use a "
                        "model with available quota."
                    ) from error
                fits_budget = deadline is None or clock() + retry_delay < deadline
                if (
                    rate_limit_retries < MAX_RATE_LIMIT_RETRIES
                    and retry_delay <= MAX_RATE_LIMIT_WAIT_SECONDS
                    and fits_budget
                ):
                    rate_limit_retries += 1
                    sleep(retry_delay)
                    continue
                raise RuntimeError(
                    "WEBSITE_IMPORT_RATE_LIMIT_ERROR: Groq rate limit persisted "
                    f"after {rate_limit_retries + 1} attempts ({diagnostic}). "
                    f"Retry after {retry_delay} seconds."
                ) from error
            if status_code == 413:
                raise _RequestTooLarge(
                    "WEBSITE_IMPORT_PROMPT_SIZE_ERROR: A single course assignment "
                    "candidate exceeds Groq's request limit."
                ) from error
            if status_code == 400 and _is_json_output_limit_error(error):
                raise _RequestTooLarge(
                    "WEBSITE_IMPORT_LLM_OUTPUT_LIMIT_ERROR: Groq could not finish "
                    "the JSON response for a single assignment."
                ) from error
            if status_code in (401, 403):
                raise RuntimeError(f"WEBSITE_IMPORT_GROQ_AUTH_ERROR: {diagnostic}") from error
            if status_code == 404:
                raise RuntimeError(f"WEBSITE_IMPORT_GROQ_MODEL_ERROR: {diagnostic}") from error
            raise RuntimeError(
                f"WEBSITE_IMPORT_LLM_ERROR: Groq request failed for model {model}: {diagnostic}"
            ) from error


def _time_budget_error(stage):
    return RuntimeError(
        f"WEBSITE_IMPORT_TIME_BUDGET_ERROR: The import ran out of time while {stage}; "
        "no partial import was saved."
    )


# A schedule row can hold a lecture, its slides and videos, and a homework at the end,
# so rows are kept whole up to a generous limit.
MAX_OUTLINE_LINE_CHARS = 2500


MAX_OUTLINE_LINES = 1500


# Characters of outline per Groq request (about 3,000 tokens), so each request stays
# within the free tier's per-minute token limit together with the answer.
OUTLINE_CHUNK_CHARS = 12_000


OUTLINE_CONTEXT_LINES = 8


# A date may be stated on the item's line or in a date heading/row up to this many lines above.
DATE_EVIDENCE_LOOKBACK = 30


OUTLINE_MAX_COMPLETION_TOKENS = 4096


def _short_link(url, page_url):
    """Compact link text for the outline: the path on the course site, or the other
    site's host plus its last path segment. The full URL is kept in a lookup table."""
    parsed, page = urlsplit(url), urlsplit(page_url)
    if parsed.netloc.lower() == page.netloc.lower():
        return urlunsplit(("", "", parsed.path or "/", parsed.query[:40], ""))
    segments = [part for part in parsed.path.split("/") if part]
    tail = f"/…/{segments[-1][:40]}" if len(segments) > 1 else (f"/{segments[0][:40]}" if segments else "")
    return f"{parsed.netloc.lower().removeprefix('www.')}{tail}"


def _log(message):
    """Operator diagnostics on stderr; the server writes them to its log."""
    print(f"[website import] {message}", file=sys.stderr)


def _progress(message):
    """A step the instructor sees while the course syncs (the server relays these)."""
    print(f"[progress] {message}", file=sys.stderr, flush=True)


def _outline_chunks(lines):
    """Split numbered lines into request-sized parts, each with a little context."""
    chunks, start = [], 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (size == 0 or size + len(lines[end]) < OUTLINE_CHUNK_CHARS):
            size += len(lines[end]) + 8
            end += 1
        chunks.append((max(0, start - OUTLINE_CONTEXT_LINES), start, end))
        start = end
    return chunks


def _parse_claimed_date(value):
    """A model-supplied date: "2026-09-24", "2026-09-24T23:59:00-07:00" or "09/24/2026"."""
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text[:10])
    if match:
        try:
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
    return None


ROMAN_PART = re.compile(r"\b(part|pt\.?)\s+(iv|vi|v|iii|ii|i)\b", re.IGNORECASE)
ROMAN_VALUES = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}


def _arabic_parts(text):
    """"Midterm Part II Retake" -> "Midterm Part 2 Retake", so both spellings are one item."""
    return ROMAN_PART.sub(lambda m: f"{m.group(1)} {ROMAN_VALUES[m.group(2).lower()]}", text or "")


def _tidy_title(title):
    """Normal capitalization, and no topic after a numbered kind ("Lab 1. Welcome" -> "Lab 1").

    "Part II" -> "Part 2" and "Project 2 A" -> "Project 2A", so spellings of one item match.
    """
    title = _arabic_parts(title)
    title = re.sub(
        r"\b(" + "|".join(name for name, _ in TITLE_KINDS) + r")\s+(\d+)\s+([A-H])(?=\s|$)",
        r"\1 \2\3", title,
    )
    words = [
        word.capitalize() if word.isalpha() and word.isupper() and len(word) >= 4 else word
        for word in title.split()
    ]
    title = " ".join(words)
    match = KIND_WITH_NUMBER.match(title)
    if match and title[match.end():match.end() + 1] in (".", ":"):
        return _canonical_title(title) or title
    return title


# Kinds whose numbered mentions are always shown for review, even if the model missed them.
SAFETY_NET_KINDS = {
    "Homework", "Lab", "Project", "Problem Set", "Worksheet", "Assignment", "Quiz",
    "Midterm", "Mini-Midterm", "Exam",
}


# Not imported for any course for now, even if the model lists them.
EXCLUDED_TITLE = re.compile(r"^\s*(?:discussion|disc)\b", re.IGNORECASE)


ALIAS_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "your", "you", "this", "that", "are",
    "due", "points", "point", "pts", "bonus", "early", "submission", "submit", "optional",
    "released", "release", "posted", "checkpoint", "part", "parts", "final", "version",
    "projects", "labs", "homeworks", "assignments", "slides", "videos", "solutions",
    "today", "tonight", "tomorrow", "week", "next", "now", "available", "only", "just",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
    "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "may", "jun", "jul",
    "aug", "sep", "sept", "oct", "nov", "dec", "noon", "midnight",
}


KIND_WORD = re.compile(
    r"\b(?:" + "|".join(f"(?:{pattern})" for _, pattern in TITLE_KINDS) + r")s?\b", re.IGNORECASE,
)


def _url_words(url, page_url):
    """Words of a link's last path segment: ".../projects/cats/" -> {"cats"}."""
    if not url or url.rstrip("/") == (page_url or "").rstrip("/"):
        return set()
    segments = [part for part in urlsplit(url).path.split("/") if part]
    if not segments:
        return set()
    return _alias_words(re.sub(r"\.html?$", "", segments[-1]).replace("-", " ").replace("_", " "))


BARE_QUALIFIER = re.compile(r"^\s*(?:" + TITLE_QUALIFIER.pattern + r")\s*$", re.IGNORECASE)


def _due_day(assignment):
    """(month, day) of an item's due date, or None."""
    try:
        due = date.fromisoformat((assignment.get("due") or "")[:10])
    except ValueError:
        return None
    return due.month, due.day


def _part_label(base, own_part, day, aliases):
    """The part's name, numbered from the page when the item's own name lacks it.

    "Checkpoint" due 10/16 -> "Checkpoint 1" when the page gives Project 3
    "checkpoint 1 Fri 10/16"; a part that already has a number keeps it.
    """
    page_part = aliases.get(base, {}).get("days", {}).get(day) if day else None
    if not own_part:
        return None
    if page_part and not re.search(r"\d", own_part) and \
            page_part.split()[0].casefold() == own_part.split()[0].casefold():
        return page_part
    return own_part


def _numbered_title_for(assignment, aliases, page_url):
    """The numbered title an item should have ("Cats project" -> "Project 2"), or None.

    Unnumbered parts get their number from the page's dates ("Checkpoint" -> "Project 4 Checkpoint 1").
    """
    title = assignment["title"]
    day = _due_day(assignment)
    if _is_exam_name(title):
        return None
    numbered_match = KIND_WITH_NUMBER.search(title)
    if numbered_match and _canonical_title(title):
        base = _canonical_title(numbered_match.group(0))
        own = TITLE_QUALIFIER.search(title[numbered_match.end():])
        own_part = clean_text(own.group(0)).title() if own else None
        part = _part_label(base, own_part, day, aliases)
        return f"{base} {part}" if part and part != own_part else None
    qualifier = TITLE_QUALIFIER.search(title)
    own_part = clean_text(qualifier.group(0)).title() if qualifier else None
    words = _alias_words(TITLE_QUALIFIER.sub(" ", title))
    url_words = _url_words(assignment.get("html_url"), page_url)
    kind_match = KIND_WORD.search(title)
    kind = _kind_name(kind_match.group(0).rstrip("sS")) if kind_match else None
    if kind == "Assignment":
        kind = None  # "Cats assignment" may be any kind of work
    found = set()
    evidence = words or url_words  # the name's topic words, else its link's
    if evidence:
        for numbered, entry in aliases.items():
            if (not kind or numbered.startswith(kind + " ")) and evidence <= entry["words"]:
                found.add(numbered)
    elif BARE_QUALIFIER.match(title) and day:
        for numbered, entry in aliases.items():
            if day in entry["days"]:
                found.add(numbered)
    if len(found) != 1:
        return None
    numbered = found.pop()
    part = _part_label(numbered, own_part, day, aliases)
    return f"{numbered} {part}" if part else numbered


def _same_term(first, second):
    a, b = TERM_PHRASE.search(first or ""), TERM_PHRASE.search(second or "")
    if not a or not b:
        return _year_from_term(first) == _year_from_term(second)
    return (a.group(1).lower().replace("autumn", "fall"), a.group(2)) == \
        (b.group(1).lower().replace("autumn", "fall"), b.group(2))


def _time_budget_seconds():
    try:
        budget = float(os.environ.get("WEBSITE_IMPORT_TIME_BUDGET_SECONDS", ""))
    except ValueError:
        budget = DEFAULT_TIME_BUDGET_SECONDS
    return budget if budget > 0 else DEFAULT_TIME_BUDGET_SECONDS

# --- Fetching: one HTTP request (plus same-site redirects) ---

ATTRIBUTE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")


def _attributes(text):
    """Attributes of a tag's text: ' href="/hw/" class="x"' -> {"href": "/hw/", "class": "x"}."""
    found = {}
    for match in ATTRIBUTE.finditer(text or ""):
        value = next(group for group in match.groups()[1:] if group is not None)
        found.setdefault(match.group(1).lower(), html_lib.unescape(value))
    return found


def _meta_refresh_target(html, page_url):
    """Where a <meta http-equiv="refresh" content="0; url=/fa26/"> page sends visitors."""
    for match in TAG.finditer(html[:20_000]):
        if match.group(1) or match.group(2).lower() != "meta":
            continue
        attributes = _attributes(match.group(3))
        if attributes.get("http-equiv", "").lower() != "refresh":
            continue
        target = re.search(r"url\s*=\s*['\"]?([^'\"]+)", attributes.get("content", ""), re.IGNORECASE)
        if target:
            try:
                return _canonical_url(target.group(1).strip(), page_url)
            except ValueError:
                return None
    return None


def fetch_page(start_url, session=None, sleep=time.sleep):
    """The course page's HTML and final address, following same-site redirects,
    including the <meta refresh> pages some sites use ("cs61a.org" -> "/fa26/")."""
    url = _canonical_url(start_url, start_url)
    host = _validate_url(url).hostname
    _assert_public_host(url)
    http = session or requests.Session()
    if hasattr(http, "trust_env"):
        http.trust_env = False
    for _refresh in range(MAX_META_REFRESHES + 1):
        html, url, _size = _fetch_html(http, url, host, sleep)
        if html is None:
            raise RuntimeError(
                "WEBSITE_FETCH_ERROR: The starting course website URL returned HTTP 404 or non-HTML content."
            )
        target = _meta_refresh_target(html, url)
        if not target or target == url or not _same_host(target, host):
            return html, url
        _log(f"following the page's redirect to {target}")
        url = target
    return html, url


# --- Page lines: trimmed HTML, one numbered line per block element ---

DROPPED_ELEMENTS = re.compile(
    r"(?is)<(script|style|noscript|template|svg|head|nav|footer|iframe|math|select)\b.*?</\1\s*>"
)
COMMENT = re.compile(r"(?s)<!--.*?-->")
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "caption", "dd", "details", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "ol", "p", "pre", "section", "summary", "table", "tbody",
    "thead", "tfoot", "tr", "ul",
}
CELL_TAGS = {"td", "th"}
BADGE_CLASS = re.compile(r"label|badge|tag|pill|chip", re.IGNORECASE)
# A badge-styled element with plain text inside: <span class="label">Project 2</span>.
BADGE_ELEMENT = re.compile(r"(?is)<(span|div|b|strong|em|small|mark|code|i)\b([^>]*)>([^<]{1,40})</\1\s*>")
DUE_ATTRIBUTES = ("data-due", "data-deadline", "data-due-date")
NAME_ATTRIBUTES = ("data-assignment-name", "data-name", "data-title")
HTML_LINK = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)
ANY_TAG = re.compile(r"<[^>]+>")
TABLE_ROW = re.compile(r"(?is)<tr\b.*?</tr\s*>")
INNER_BLOCK_TAG = re.compile(
    r"(?i)</?(" + "|".join(sorted(BLOCK_TAGS, key=len, reverse=True)) + r")\b[^>]*>"
)


def _plain(text):
    """A line without its tags: '<a href="/hw/">HW 3</a> due 9/8' -> 'HW 3 due 9/8'."""
    return clean_text(ANY_TAG.sub(" ", text or ""))


HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
BARE_HIDDEN_ATTRIBUTE = re.compile(r"(?:^|\s)hidden(?=[\s/]|$)", re.IGNORECASE)


def _is_hidden_announcement(attribute_text):
    attributes = _attributes(attribute_text)
    names = f"{attributes.get('class', '')} {attributes.get('id', '')}"
    if not re.search(r"announce", names, re.IGNORECASE):
        return False
    return bool(
        HIDDEN_STYLE.search(attributes.get("style", ""))
        or attributes.get("aria-hidden", "").lower() == "true"
        or BARE_HIDDEN_ATTRIBUTE.search(attribute_text)
    )


def _drop_hidden_announcements(html):
    """Removes announcements the site hides from students (old posts behind "Previous").

    They repeat dates that were later changed ("Retakes 11/5-11/6", then "11/5-11/6 &
    11/9-11/10"). Only hidden elements marked as announcements go: some sites hide past
    schedule weeks the same way, and those are still needed.
    """
    kept, position = [], 0
    for match in TAG.finditer(html):
        if match.start() < position or match.group(1) or not _is_hidden_announcement(match.group(3)):
            continue
        name, depth = match.group(2).lower(), 1
        for inner in TAG.finditer(html, match.end()):
            if inner.group(2).lower() != name:
                continue
            depth += -1 if inner.group(1) else 1
            if depth == 0:
                kept.append(html[position:match.start()])
                position = inner.end()
                break
    kept.append(html[position:])
    return " ".join(kept)


TABLE_CELL = re.compile(r"(?is)<(td|th)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>(.*?)</\1\s*>")
BACKGROUND_STYLE = re.compile(r"background(?:-color)?\s*:\s*([^;]+)", re.IGNORECASE)


def _cell_groups(attribute_text):
    """What styles a cell like others: its class names and background color."""
    attributes = _attributes(attribute_text)
    groups = [f"class:{name}" for name in attributes.get("class", "").split()]
    background = BACKGROUND_STYLE.search(attributes.get("style", ""))
    if background:
        groups.append("background:" + clean_text(background.group(1)).lower())
    return groups


def _label_grouped_cells(html):
    """Names cells by the item whose other cells are styled the same way.

    A calendar may color each project's cells alike: "Release Project 1", then
    "Design Document Due" and "Code and Final Report Due" in the same color, without
    naming the project again. When every numbered item among a style's cells is the
    same one, the cells that name nothing get it: "Project 1: Design Document Due".
    """
    cells = list(TABLE_CELL.finditer(html))
    named = {}  # style -> numbered items named in its cells
    counts = Counter()
    for cell in cells:
        text = _plain(html_lib.unescape(cell.group(3)))
        mentions = {_canonical_title(m.group(0)) for m in KIND_WITH_NUMBER.finditer(_arabic_parts(text))}
        for group in _cell_groups(cell.group(2)):
            counts[group] += 1
            named.setdefault(group, set()).update(title for title in mentions if title)
    labels = {group: next(iter(titles)) for group, titles in named.items()
              if len(titles) == 1 and counts[group] >= 2}
    if not labels:
        return html
    pieces, position = [], 0
    for cell in cells:
        text = _plain(html_lib.unescape(cell.group(3)))
        if not text or KIND_WITH_NUMBER.search(_arabic_parts(text)) or _is_date_only(text):
            continue
        found = {labels[group] for group in _cell_groups(cell.group(2)) if group in labels}
        if len(found) != 1:
            continue
        pieces += [html[position:cell.start(3)], f"{found.pop()}: "]
        position = cell.start(3)
    pieces.append(html[position:])
    return "".join(pieces)


def page_lines(html, page_url):
    """Numbered-line text of a page, plus the full address of each short link in it."""
    links = {}
    text = DROPPED_ELEMENTS.sub(" ", COMMENT.sub(" ", html or ""))
    text = _drop_hidden_announcements(text)
    text = _label_grouped_cells(text)
    # Line breaks in the source mean nothing in HTML; only block tags start lines.
    text = re.sub(r"\s+", " ", text)

    def badge(match):
        if not BADGE_CLASS.search(_attributes(match.group(2)).get("class", "")):
            return match.group(0)
        return f" «{clean_text(match.group(3))}» "

    text = BADGE_ELEMENT.sub(badge, text)
    # A table row stays one line: block tags inside its cells become spaces.
    text = TABLE_ROW.sub(
        lambda row: INNER_BLOCK_TAG.sub(
            lambda tag: tag.group(0) if tag.group(1).lower() in ("tr", "table") else " ", row.group(0),
        ),
        text,
    )

    def render(match):
        closing, name, attribute_text = match.group(1), match.group(2).lower(), match.group(3)
        attributes = {} if closing else _attributes(attribute_text)
        due = next((attributes[key] for key in DUE_ATTRIBUTES if attributes.get(key)), None)
        marker = ""
        if due:
            label = next((attributes[key] for key in NAME_ATTRIBUTES if attributes.get(key)), "")
            marker = f' {{due {clean_text(due)}{f" {json.dumps(clean_text(label))}" if label else ""}}} '
        if name == "a":
            if closing:
                return "</a>"
            try:
                url = _canonical_url(attributes["href"], page_url) if attributes.get("href") else ""
            except ValueError:
                url = ""
            if not url:
                return marker + "<a>"
            short = _short_link(url, page_url)
            links[short] = url
            return marker + f'<a href="{short}">'
        if name in CELL_TAGS:
            return (" | " if not closing else "") + marker
        if name in BLOCK_TAGS:
            return "\n" + marker
        return marker or ""

    text = html_lib.unescape(TAG.sub(render, text))
    lines = []
    for raw in text.split("\n"):
        line = clean_text(raw).strip(" |")
        # An empty anchor or a lone separator is not content.
        if not _plain(line).strip(" |"):
            continue
        lines.append(line[:MAX_OUTLINE_LINE_CHARS])
        if len(lines) >= MAX_OUTLINE_LINES:
            break
    return lines, links


def page_term(html, url):
    """The term a course website is for, from the site itself, or None.

    In order: "Fall 2026" in the page title; otherwise the term most mentioned on the
    page; otherwise a term code in its address ("/fa26/", "fa26.datastructur.es").
    """
    html = html or ""
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    match = TERM_PHRASE.search(_plain(html_lib.unescape(title.group(1))) if title else "")
    if match:
        return f"{match.group(1).capitalize().replace('Autumn', 'Fall')} {match.group(2)}"
    text = _plain(html_lib.unescape(DROPPED_ELEMENTS.sub(" ", COMMENT.sub(" ", html))))
    mentions = Counter(
        f"{season.capitalize().replace('Autumn', 'Fall')} {year}"
        for season, year in TERM_PHRASE.findall(text)
    )
    if mentions:
        return mentions.most_common(1)[0][0]
    return _effective_term("", url) if _address_names_term(url) else None


# --- Page reading: the model lists deadlines from the numbered lines ---

OUTLINE_SYSTEM_PROMPT = """You read a university course homepage, given as numbered lines of its HTML, and list every graded deadline on it, the way a careful TA would.

The page's HTML is lightly trimmed: each line starts at a block element (row, list item, paragraph, heading), table cells are separated by " | ", links keep their address as <a href="...">text</a>, badges appear as «text», and {due YYYY/MM/DD "name"} is a due date the site itself attached to an item. Lines before "--- START ---" are context only: never list items from them, but use them to understand dates (for example a date heading or table row above).

Course websites are laid out in many different ways, so don't expect any particular format. Read the whole page the way a student would to find out what they must turn in or take, and when. Go through every line after "--- START ---", including every row of every table, and list every graded item on each line: one row can hold several (an exam, a lab, a homework and a project), and none may be skipped. When an announcement and a schedule or table disagree about an item's date, the schedule's date is the one to use. A deadline can appear anywhere (a list, a table, a calendar, an announcement, a sentence) and as a link or as plain text. Its date may be written next to it, or only implied by where it sits on the page (under a date heading, in a dated row or section). Use whatever the page's own structure tells you.

List each graded item once:
- Include homework, labs, projects (and each separately dated part, checkpoint, milestone, design doc or proposal), problem sets, worksheets, quizzes, quests, midterms, postterms, finals, exams, and graded surveys or forms with a due date.
- Include every numbered lab listed on the page, even when it has no due date or "due" wording (for example a "Lab 4. Iteration" link in a Lab column). The instructor reviews the list and removes what they don't need.
- Include items even when no due date is given (use null). A missing date is never a reason to leave something out.
- Exclude discussions (discussion sections and their worksheets), lectures, talks, section times, readings, slides, videos, notes, solutions, office hours, review sessions, practice material (practice exams or quizzes), study guides, project parties or work sessions, announcements about logistics, holidays, and release notices (an entry that only says an assignment was released, when the page also lists when it is due).
- If the same item is listed with two different due dates, list both. But a window or several sittings of one exam or quiz is one item, not one per day.

For each item return:
- line: the line number where the item appears (where its own entry is, not a date heading)
- title: kind and number only, never the topic and never a date: "Homework 3", "Lab 5", "Project 2A", "Project 4B Checkpoint", "Homework 1 Part 2", "Quiz 1", "Midterm Part 1 Retake", "Final Exam". Expand abbreviations (HW -> Homework, Proj -> Project). When a line names the item only by its topic ("Maze project", "Robots checkpoint"), use the kind and number the page gives that topic elsewhere if you can see it; otherwise its short name. If an item has no number, use its short name ("Postterm", "Chess AI Contest"). Write titles in normal capitalization even when the page uses ALL CAPS ("MIDTERM 1" -> "Midterm 1", "POSTTERM" -> "Postterm").
- due: YYYY-MM-DD, or null. Only a date the page gives for this item; never guess one. If the site marks the item's due date itself (a «Due ...» badge, a {due ...} marker, or "due ..." wording), use exactly that date. If the item's own entry gives a window or several sittings ("10/28-10/30", "Mon 10/5 - Fri 10/9", "Thu 11/5 and Fri 11/6"), use the last day, since that is when it must be done. A row's or heading's date counts only when the page uses it as the item's date: the entry says it is due then ("Proj 1 Due"), it is an exam held then (with a time, or in an exam column), or the page's items generally carry no dates of their own. When other items on the page state their own dates ("Lab 2 Higher-Order Functions (due Wed 9/9)") and this item states none (a «QUIZ 1» badge in a lecture row), the row's date is only a class meeting: use null. The course runs between course_dates.first and course_dates.last, so every deadline falls in that range; dates without a year belong to course_term.
- date_text: the exact characters from the lines that state that date (copied verbatim, for example "due Tue Sep 08", "Fri Sep 25", "2026/09/08", "11/19-11/20"), or "" when due is null. It may come from the item's line or from a date heading or table row above it.
- link: the href of the item's own link on that line, copied exactly, or "".

Return JSON exactly as {"items":[{"line":12,"title":"Homework 3","due":"2026-09-08","date_text":"due Tue Sep 08","link":"/homeworks/hw03"}]}"""


# "(due Wed 9/9)", "«Due 11/13»", "due Thu 11/19": a date the site gives an item itself.
OWN_DUE_DATE = re.compile(
    r"\bdue\b\W{0,3}(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?(?:" + DATE_VALUE.pattern + r")",
    re.IGNORECASE,
)
# Exams take place on the day their row or heading gives, even with no "due" wording.
EXAM_KIND = re.compile(r"\b(?:midterm|exam|final|postterm|quest)\b", re.IGNORECASE)


def _site_dates_its_items(lines):
    """Whether the page gives its items their own due dates ("Lab 2 ... (due Wed 9/9)").

    On such a page a row's date is the day of class: an item listed there without a
    date of its own (a «QUIZ 1» badge in a lecture row) has no stated due date.
    """
    return sum(1 for line in lines if OWN_DUE_DATE.search(_plain(line))) >= 3


def _mentions_day(text, claimed, term):
    for match in DATE_VALUE.finditer(text):
        year, month, day = _date_parts(match.groupdict(), term)
        if (month, day) == (claimed.month, claimed.day) and (not year or year == claimed.year):
            return True
    return False


def _date_from_own_entry(item, lines, claimed, term):
    """Whether the date is on the item's own line, beyond the row's date cells.

    The model's line number can be off by one, so the line that names the item is used.
    """
    cited = item["line"]
    named = re.compile(r"(?<!\w)" + re.escape(_arabic_parts(item.get("title") or "")) + r"(?!\w)", re.IGNORECASE)
    entry = next(
        (n for n in (cited, cited - 1, cited + 1)
         if 1 <= n <= len(lines) and named.search(_arabic_parts(_plain(lines[n - 1])))),
        cited,
    )
    cells = _plain(lines[entry - 1]).split(" | ")
    own = " ".join(cell for cell in cells if len(cells) == 1 or not _is_date_only(cell))
    return _mentions_day(own, claimed, term)


def _validated_due(item, lines, term, items_dated_by_site=False):
    """The model's due date, only if that month/day appears on or just above the item's line.

    When the site dates its items itself, only exams may take their date from a row's
    date cell or a heading; anything else needs a date in its own entry.
    """
    due, line = item.get("due"), item.get("line")
    if not isinstance(due, str) or not isinstance(line, int):
        return None
    claimed = _parse_claimed_date(due)
    if claimed is None:
        return None
    first, last = term_date_range(term)
    if not first <= claimed <= last:
        return None  # not when this course runs
    # The cited line and the lines above it (date headings), plus a couple below in
    # case the model's line number is slightly off.
    window = " ".join(_plain(text) for text in lines[max(0, line - 1 - DATE_EVIDENCE_LOOKBACK): line + 2])
    if not _mentions_day(window, claimed, term):
        return None
    if items_dated_by_site and not EXAM_KIND.search(item.get("title") or "") \
            and not _date_from_own_entry(item, lines, claimed, term):
        return None  # only the row's or heading's date, which is not this item's
    return claimed.isoformat()


# Right after an item's link: the site's own due badge, "«Due 11/13»".
DUE_BADGE_AFTER = re.compile(r"^\s*«\s*due\b([^»]*)»", re.IGNORECASE)
# A retake or make-up is its own sitting: "Midterm 2 Retake" does not stand for "Midterm 2".
SEPARATE_SITTING = re.compile(r"\b(?:retake|make-?up|alternate|redo)\b", re.IGNORECASE)


def _due_after(rest, badge_only=False):
    """The due wording that belongs to a mention, from the text right after it.

    After a link, only the site's own badge counts ("Midterm Part 2: 11/9-11/13 «Due 11/13»");
    after a badge, the item's own text up to the next badge or cell
    ("«Homework 6» Classes (due Thu 10/22)").
    """
    if badge_only:
        match = DUE_BADGE_AFTER.match(rest)
        return match.group(1) if match else None
    segment = _plain(re.split(r"«| \| ", rest, maxsplit=1)[0])
    match = OWN_DUE_DATE.search(segment)
    return match.group(0) if match else None


def _badge_due(text, term):
    """The date in a "«Due 11/13»" badge, if it falls in the course's term."""
    match = DATE_VALUE.search(text)
    if not match:
        return None
    year, month, day = _date_parts(match.groupdict(), term)
    first, last = term_date_range(term)
    for candidate_year in ([year] if year else sorted({first.year, last.year})):
        try:
            due = date(candidate_year, month, day)
        except ValueError:
            continue
        if first <= due <= last:
            return due.isoformat()
    return None


def _missed_numbered_items(lines, links, page_url, covered_titles, term=""):
    """Numbered work the model did not list, from link texts and badges on the page.

    Plain sentences such as "Lab 14: No lab" or a section's meeting time are left to
    the model's judgment. Each missing item is added once, dated only by due wording the
    site gives that item itself.
    """
    covered = {title.casefold() for title in covered_titles}
    added = []
    for number, line in enumerate(lines, start=1):
        mentions = [
            (_plain(link.group(2)), link.group(1), _due_after(line[link.end():], badge_only=True))
            for link in HTML_LINK.finditer(line)
        ]
        mentions += [
            (badge.group(1), None, _due_after(line[badge.end():]))
            for badge in re.finditer(r"«([^»]*)»", line)
        ]
        for text, address, due_badge in mentions:
            text = _arabic_parts(clean_text(text).strip("«» "))
            match = KIND_WITH_NUMBER.match(text)
            if not match or _kind_name(match.group("kind")) not in SAFETY_NET_KINDS:
                continue
            title = _canonical_title(_clean_title(text)) or _canonical_title(match.group(0))
            key = title.casefold()
            if key in covered or any(
                c.startswith(key + " ") and not SEPARATE_SITTING.search(c[len(key):]) for c in covered
            ):
                continue
            covered.add(key)
            url = links.get(address, "") if address else ""
            due = _badge_due(due_badge, term) if due_badge else None
            added.append({"line": number, "title": title, "url": url or page_url, "due": due})
    return added


def _assignment(title, due, html_url, line=None):
    """An imported item. "_line" (the page line it came from) is for naming only and
    is removed before the import is returned."""
    key = f"{html_url}\n{title.casefold()}\n{due or ''}"
    return key, {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:32],
        "title": title,
        "due": due,
        "html_url": html_url,
        "source": "website",
        "resources": [],
        "_line": line,
    }


# An entry that is only "<item> due", with no date of its own: «Homework 1 Part 1 due».
BARE_DUE_ENTRY = re.compile(r"^\s*(?P<name>.+?)\s+due\s*$", re.IGNORECASE)


def _bare_due_dates(lines, term):
    """Title -> due date for every bare "<item> due" entry under a day heading.

    Some calendars give each day a heading ("Fri Sep 18") with that day's entries below
    it: «Homework 2» where it is released, «Homework 2 due» where it is due. The page
    states the due day this way, so it decides that item's date over any reading of
    the release line. Pages without such entries are unaffected.
    """
    found = {}
    for number, line in enumerate(lines, start=1):
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*", _plain(line))]
        if len(cells) > 1:
            # A table row: "Thu 10/29 | ... | HW 4 Due" is due on the row's date.
            row_date = next((cell for cell in cells if _is_date_only(cell) and DATE_VALUE.search(cell)), None)
            for cell in cells:
                match = BARE_DUE_ENTRY.match(_arabic_parts(cell))
                name = clean_text(match.group("name")) if match else ""
                if not row_date or not KIND_WITH_NUMBER.fullmatch(name):
                    continue
                due = _badge_due(DATE_VALUE.search(row_date).group(0), term)
                if due:
                    found.setdefault(_canonical_title(name).casefold(), due)
            continue
        text = _arabic_parts(_plain(re.sub(r"[«»]", " ", line)))
        match = BARE_DUE_ENTRY.match(text)
        if not match or DATE_VALUE.search(text) or not KIND_WITH_NUMBER.search(match.group("name")):
            continue
        for above in range(number - 1, max(0, number - 1 - DATE_EVIDENCE_LOOKBACK), -1):
            heading = _plain(lines[above - 1])
            if _is_date_only(heading):
                date_match = DATE_VALUE.search(heading)
                due = _badge_due(date_match.group(0), term) if date_match else None
                if due:
                    found.setdefault(_tidy_title(clean_text(match.group("name"))).casefold(), due)
                break
    return found


# An exam's own entry under a day heading, with a time but no date:
# «Midterm Exam» Midterm (5:00–6:30 PM). Review sessions and practice exams are not exams.
EXAM_BADGE_ENTRY = re.compile(r"^\s*«(?P<badge>[^»]*\b(?:midterm|exam|final|postterm)\b[^»]*)»", re.IGNORECASE)
NOT_AN_EXAM = re.compile(r"\b(?:review|practice|study|prep)\b", re.IGNORECASE)


def _exam_heading_days(lines, term):
    """Line number -> date of the day heading above each undated exam entry."""
    found = {}
    for number, line in enumerate(lines, start=1):
        text = _plain(line)
        match = EXAM_BADGE_ENTRY.match(text)
        untimed = re.sub(r"\d{1,2}:\d{2}", " ", text)  # "5:00-6:30" is a time, not a date
        if not match or NOT_AN_EXAM.search(text) or DATE_VALUE.search(untimed):
            continue
        for above in range(number - 1, max(0, number - 1 - DATE_EVIDENCE_LOOKBACK), -1):
            heading = _plain(lines[above - 1])
            if _is_date_only(heading):
                date_match = DATE_VALUE.search(heading)
                due = _badge_due(date_match.group(0), term) if date_match else None
                if due:
                    found[number] = due
                break
    return found


# A cell named by its style group (see _label_grouped_cells) that is a deadline:
# "Homework 5: Checkpoint Deadline", "Project 2: Design Document Due".
LABELED_DEADLINE_CELL = re.compile(r"^(?P<item>[^:]+):\s+(?P<part>.+?)\s+(?:due|deadline)$", re.IGNORECASE)


def _labeled_cell_deadlines(lines, term):
    """(line, title, due) for each labeled deadline cell, dated by its table row."""
    found = []
    for number, line in enumerate(lines, start=1):
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*", _plain(line))]
        row_date = next((cell for cell in cells if _is_date_only(cell) and DATE_VALUE.search(cell)), None)
        if len(cells) < 2 or not row_date:
            continue
        for cell in cells:
            match = LABELED_DEADLINE_CELL.match(BRACKETED_SEGMENT.sub("", cell).strip())
            if not match or not KIND_WITH_NUMBER.fullmatch(match.group("item").strip()):
                continue
            due = _badge_due(DATE_VALUE.search(row_date).group(0), term)
            part = clean_text(match.group("part"))
            if due and part:
                found.append((number, f"{_canonical_title(match.group('item'))} {part}", due))
    return found


def _drop_same_line_generic_copies(assignments, labeled_lines):
    """"Project 1" and "Project 1 Code and Final Report" read from one labeled cell's
    row, due the same day, are one deadline: the specific name stays. Only rows with a
    labeled deadline cell: elsewhere one row can list two items ("Project 4" and
    "Project 4 TypeScript")."""
    generic = [
        a for a in assignments
        if a["due"] and a.get("_line") in labeled_lines and any(
            other is not a and other.get("_line") == a.get("_line") and other["due"] == a["due"]
            and other["title"].casefold().startswith(a["title"].casefold() + " ")
            for other in assignments
        )
    ]
    if generic:
        _log("dropped names repeated by a more specific one on the same entry: "
             + ", ".join(a["title"] for a in generic))
    return [a for a in assignments if a not in generic]


# "Proj 4 Research Document Due", "Final Project Due", "HW 1 Due": a deadline named in a
# table cell, due on its row's date. "Due" followed by a date ("«Due 9/22»") states its
# own date and is read as such elsewhere.
DUE_PHRASE = re.compile(
    r"(?P<name>(?:[A-Z0-9][\w'\-]*\.?:?\s+){1,6}?)Due\b(?!\s*(?:on\s+|by\s+)?(?:[\d(]|(?:mon|tue|wed|thu|fri|sat|sun)))"
)
# An exam named in a table cell: "QUEST 1", "MIDTERM 2", "Postterm 3".
EXAM_IN_CELL = re.compile(r"\b(?:quest|midterm|post[- ]?term)\s+\d+\b", re.IGNORECASE)
NOT_THE_EXAM_ITSELF = re.compile(r"\b(?:review|preview|practice|talk|study|prep|conflict)\b", re.IGNORECASE)
# Section codes are meeting times, not work: "Lab 801L: Monday, Wednesday @ 4–6 PM".
SECTION_CODE_TITLE = re.compile(r"^(?:lab|discussion|disc)\s+\d{3,}[a-z]?$", re.IGNORECASE)


def _due_phrase_title(name):
    """"Proj 4 Research Document" -> "Project 4 Research Document"; "Proj 3:" -> "Project 3"."""
    name = clean_text(name).strip(" :")
    numbered = list(KIND_WITH_NUMBER.finditer(name))
    if numbered:
        last = numbered[-1]
        rest = clean_text(name[last.end():]).strip(" :")
        return f"{_canonical_title(last.group(0))}{' ' + rest if rest else ''}"
    if not KIND_WORD.search(name):
        return None
    return name


def _row_deadlines(lines, term):
    """(line, title, due, kind) for deadlines and exams a table row dates itself.

    kind is "due" for "<item> Due" phrases and "exam" for an exam named in a cell.
    """
    found = []
    for number, line in enumerate(lines, start=1):
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*", _plain(line))]
        row_date = next((cell for cell in cells if _is_date_only(cell) and DATE_VALUE.search(cell)), None)
        if len(cells) < 2 or not row_date:
            continue
        due = _badge_due(DATE_VALUE.search(row_date).group(0), term)
        if not due:
            continue
        for cell in cells:
            for match in DUE_PHRASE.finditer(cell):
                title = _due_phrase_title(match.group("name"))
                if title:
                    found.append((number, title, due, "due"))
            untimed = re.sub(r"\d{1,2}:\d{2}", " ", cell)
            if NOT_THE_EXAM_ITSELF.search(cell) or DATE_VALUE.search(untimed):
                continue
            for match in EXAM_IN_CELL.finditer(cell):
                found.append((number, _canonical_title(match.group(0)), due, "exam"))
    return found


def _outline_items_to_assignments(items, lines, links, page_url, term):
    assignments, seen = [], set()
    items_dated_by_site = _site_dates_its_items(lines)
    bare_due = _bare_due_dates(lines, term)
    row_deadlines = _row_deadlines(lines, term)
    row_due = {}
    for _line, title, due, kind in row_deadlines:
        if kind == "due":
            row_due.setdefault(title.casefold(), due)
    row_exam = {}
    for _line, title, due, kind in row_deadlines:
        if kind == "exam":
            row_exam.setdefault(title.casefold(), due)
    exam_days = _exam_heading_days(lines, term)
    rejected = []
    for item in items:
        if not isinstance(item, dict):
            continue
        line, title = item.get("line"), item.get("title")
        if not isinstance(line, int) or not 1 <= line <= len(lines) or not isinstance(title, str):
            continue
        title = _tidy_title(_strip_date_tail(BRACKETED_SEGMENT.sub(
            lambda m: "" if DATE_SIGNAL.search(m.group(0)) or TIME_OF_DAY.search(m.group(0)) else m.group(0),
            clean_text(title),
        )).strip(" -:,"))
        if not title or len(title) > 100 or EXCLUDED_TITLE.match(title) or SECTION_CODE_TITLE.match(title):
            continue
        due = _validated_due(item, lines, term, items_dated_by_site)
        if isinstance(item.get("due"), str) and due is None:
            rejected.append(item)
        due = bare_due.get(_tidy_title(title).casefold(), due)
        due = bare_due.get((_canonical_title(title) or "").casefold(), due) \
            if KIND_WITH_NUMBER.fullmatch(_tidy_title(title)) else due
        due = row_due.get(title.casefold(), due)
        if due is None:
            due = row_exam.get(title.casefold())
        if due is None and EXAM_KIND.search(title):
            # The model's line number can be off by one.
            due = next((exam_days[n] for n in (line, line - 1, line + 1) if n in exam_days), None)
        link = clean_text(item.get("link"))
        url = links.get(link) or (link if link in links.values() else "")
        if url and f'"{_short_link(url, page_url)}"' not in lines[line - 1]:
            url = ""  # only a link from the item's own line
        key, assignment = _assignment(title, due, url or page_url, line)
        if key in seen:
            continue  # the same item read twice (for example in a part's context lines)
        seen.add(key)
        assignments.append(assignment)
    if rejected:
        _log("page reading: dates not verified (first 8): " + "; ".join(
            f"{item.get('title')!r} line {item.get('line')} due {item.get('due')!r} "
            f"date_text {item.get('date_text')!r}"
            for item in rejected[:8]
        ))
    missed = _missed_numbered_items(lines, links, page_url, [a["title"] for a in assignments], term)
    _log(
        f"page reading: model listed {len(items)} item(s), {len(assignments)} usable; "
        f"{sum(1 for a in assignments if a['due'])} with a due date verified on the page; "
        f"safety net added {len(missed)} numbered item(s) the model missed"
        + (f" ({', '.join(m['title'] for m in missed[:15])}{', ...' if len(missed) > 15 else ''})"
           if missed else "")
    )
    for item in missed:
        due = item["due"] or bare_due.get(_tidy_title(item["title"]).casefold())
        assignments.append(_assignment(item["title"], due, item["url"], item["line"])[1])
    # Deadlines in labeled cells the model passed over ("Homework 5: Checkpoint Deadline").
    labeled = _labeled_cell_deadlines(lines, term)
    for line, title, due in labeled:
        base = (_canonical_title(title) or title).split(" ")[:2]
        if any(a["due"] == due and a["title"].split(" ")[:2] == base for a in assignments):
            continue  # already listed for that day
        _log(f"added labeled deadline the model missed: {title!r} due {due}")
        assignments.append(_assignment(title, due, page_url, line)[1])
    # Row deadlines the model passed over ("Proj 4 Research Document Due", "QUEST 1").
    listed = {a["title"].casefold() for a in assignments}
    for line, title, due, _kind in row_deadlines:
        if title.casefold() in listed:
            continue
        listed.add(title.casefold())
        _log(f"added row deadline the model missed: {title!r} due {due}")
        assignments.append(_assignment(title, due, page_url, line)[1])
    assignments = _drop_same_line_generic_copies(assignments, {line for line, _title, _due in labeled})
    # Rows that name a project's deadlines ("Proj 4 Artifact Due", "Proj 4 Peer Comments
    # Due") leave no deadline for "Project 4" itself unless a row says "Proj 4 Due".
    row_due_titles = {title.casefold() for _line, title, _due, kind in row_deadlines if kind == "due"}
    generic = [
        a for a in assignments
        if KIND_WITH_NUMBER.fullmatch(a["title"]) and a["title"].casefold() not in row_due_titles
        and any(title.startswith(a["title"].casefold() + " ") for title in row_due_titles)
    ]
    if generic:
        _log("dropped bare names of work the rows give part deadlines for: "
             + ", ".join(f"{a['title']} ({a['due']})" for a in generic))
    assignments = [a for a in assignments if a not in generic]
    # One exam listed on two days at most 3 days apart is one sitting window ("released
    # Friday 11/20 ... open until Sunday 11/22"): it is done by the later day.
    exam_dates = {}
    for a in assignments:
        if a["due"] and re.match(r"(?:quest|midterm|post[- ]?term|final exam|exam)\b", a["title"], re.IGNORECASE):
            exam_dates.setdefault(a["title"].casefold(), []).append(a)
    window_starts = []
    for copies in exam_dates.values():
        days = sorted({date.fromisoformat(a["due"][:10]) for a in copies})
        if len(days) > 1 and (days[-1] - days[0]).days <= 3:
            window_starts += [a for a in copies if date.fromisoformat(a["due"][:10]) != days[-1]]
    if window_starts:
        _log("kept the last day of exam windows over: "
             + ", ".join(f"{a['title']} ({a['due']})" for a in window_starts))
    assignments = [a for a in assignments if a not in window_starts]
    # On a labeled cell's row, the label is the page's own name for that day's deadline:
    # a model name for it that is some other item ("Lab 5" for "Homework 5: RPC Lab
    # Deadline") goes. Other deadlines on the row ("HW 1 Due") keep their own names.
    labeled_bases = {(line, due): (_canonical_title(title) or title).split(" ")[:2] for line, title, due in labeled}
    misnamed = [
        a for a in assignments
        if (a.get("_line"), a["due"]) in labeled_bases
        and a["title"].split(" ")[:2] != labeled_bases[(a.get("_line"), a["due"])]
        and (_canonical_title(a["title"]) or a["title"]).casefold() not in bare_due
    ]
    if misnamed:
        _log("dropped other names for a labeled cell's deadline: " + ", ".join(a["title"] for a in misnamed))
    assignments = [a for a in assignments if a not in misnamed]
    # «Homework 1» where it is released, then «Homework 1 Part 1 due» and «... Part 2 due»:
    # the parts are the deadlines, and the undated release line is not one.
    released_in_parts = [
        a for a in assignments
        if not a["due"] and any(key.startswith(a["title"].casefold() + " part ") for key in bare_due)
    ]
    if released_in_parts:
        _log("dropped release lines of work due in parts: " + ", ".join(a["title"] for a in released_in_parts))
    return [a for a in assignments if a not in released_in_parts]


def _request_items(client, numbered, term, page_url, sleep, deadline, clock, note=None):
    """One page-reading request over numbered lines; returns the model's item list."""
    first, last = term_date_range(term)
    request = {
        "course_term": term,
        "course_dates": {"first": first.isoformat(), "last": last.isoformat()},
        "today": date.today().isoformat(),
        "page_url": page_url,
    }
    if note:
        request["note"] = note
    request["lines"] = "\n".join(numbered)
    completion = _groq_request(
        client, OUTLINE_SYSTEM_PROMPT, json.dumps(request, ensure_ascii=True), sleep=sleep,
        deadline=deadline, clock=clock, max_completion_tokens=OUTLINE_MAX_COMPLETION_TOKENS,
    )
    choices = getattr(completion, "choices", None)
    content = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
    try:
        result = json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "WEBSITE_IMPORT_LLM_ERROR: The model returned invalid JSON while reading the page."
        ) from error
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise RuntimeError("WEBSITE_IMPORT_LLM_ERROR: The model response must contain an items array.")
    return [item for item in result["items"] if isinstance(item, dict) and isinstance(item.get("line"), int)]


# Graded work named in a line's own text (not inside a link or badge, which the
# safety net checks): "«Exam» Midterm 2 (in the CBTF, Mon 10/5 - Fri 10/9)".
GRADED_WORDS = re.compile(r"\b(?:midterm|exam|quiz|quest|postterm|final)\b", re.IGNORECASE)
RECHECK_CONTEXT_LINES = 3


def _skipped_lines(lines, cited):
    """Lines that name graded work in plain text but that no listed item came from."""
    skipped = []
    for number, line in enumerate(lines, start=1):
        if number in cited:
            continue
        text = _plain(re.sub(r"«[^»]*»", " ", HTML_LINK.sub(" ", line)))
        numbered = [m for m in KIND_WITH_NUMBER.finditer(text) if _kind_name(m.group("kind")) in SAFETY_NET_KINDS]
        if numbered or GRADED_WORDS.search(text):
            skipped.append(number)
    return skipped


def _recheck_skipped_lines(lines, cited, term, page_url, client, sleep, deadline, clock):
    """A second, focused read of lines that name graded work but gave no item.

    A long page read in parts can make the model pass over a row; every such row is
    shown to it again on its own, with a few lines above it for its date.
    """
    skipped = _skipped_lines(lines, cited)
    if not skipped:
        return []
    groups, current, size = [], [], 0
    for number in skipped:
        block = [f"{n}: {lines[n - 1]}" for n in range(max(1, number - RECHECK_CONTEXT_LINES), number)]
        block += ["--- START ---", f"{number}: {lines[number - 1]}"]
        block_size = sum(len(text) for text in block)
        if current and size + block_size > OUTLINE_CHUNK_CHARS:
            groups.append(current)
            current, size = [], 0
        current.append((number, block))
        size += block_size
    if current:
        groups.append(current)
    _progress(f"Web sync is double-checking {len(skipped)} line{'' if len(skipped) == 1 else 's'} it may have missed")
    note = (
        "These lines were passed over in a first reading although they name graded work. "
        "Each line after a \"--- START ---\" marker is one to check; the lines just above "
        "each marker are context only. List the graded items on the checked lines."
    )
    found = []
    for group in groups:
        if deadline is not None and clock() + GROQ_REQUEST_TIMEOUT_SECONDS > deadline:
            _log("recheck: skipped, not enough time left")
            break
        wanted = {number for number, _block in group}
        numbered = [text for _number, block in group for text in block]
        try:
            answer = _request_items(client, numbered, term, page_url, sleep, deadline, clock, note=note)
        except _RequestTooLarge:
            _log(f"recheck: {len(wanted)} line(s) too large to send again")
            continue
        found += [item for item in answer if item["line"] in wanted]
    _log(f"recheck: {len(skipped)} line(s) named graded work but gave no item; "
         f"model listed {len(found)} item(s) from them")
    return found


def extract_assignments_from_page(lines, links, page_url, term, client, sleep, deadline=None,
                                  clock=time.monotonic):
    """Have the model read the page lines and list its deadlines, part by part.

    Lines that name graded work but gave no item are read again on their own.
    Returns the assignments and how many items the model listed.
    """
    items = []
    pending = list(_outline_chunks(lines))
    parts_read = 0
    while pending:
        context_start, start, end = pending.pop(0)
        if deadline is not None and clock() + GROQ_REQUEST_TIMEOUT_SECONDS > deadline:
            raise _time_budget_error("reading the course page")
        parts_total = parts_read + len(pending) + 1
        _progress("Web sync is reading the page for assignments and due dates"
                  + (f" (part {parts_read + 1} of {parts_total})" if parts_total > 1 else ""))
        numbered = [f"{number}: {lines[number - 1]}" for number in range(context_start + 1, start + 1)]
        numbered.append("--- START ---")
        numbered += [f"{number}: {lines[number - 1]}" for number in range(start + 1, end + 1)]
        try:
            answer = _request_items(client, numbered, term, page_url, sleep, deadline, clock)
        except _RequestTooLarge as too_large:
            if end - start <= 1:
                raise RuntimeError(too_large.single_item_error) from too_large.__cause__
            middle = (start + end) // 2
            pending[0:0] = [(max(0, start - OUTLINE_CONTEXT_LINES), start, middle),
                            (max(0, middle - OUTLINE_CONTEXT_LINES), middle, end)]
            continue
        # Items cited from context lines belong to the previous part and were listed there.
        items += [item for item in answer if start < item["line"] <= end]
        parts_read += 1
    items += _recheck_skipped_lines(
        lines, {item["line"] for item in items}, term, page_url, client, sleep, deadline, clock,
    )
    return _outline_items_to_assignments(items, lines, links, page_url, term), len(items)


# --- Merging names ("Cats project" == "Project 2"), using links on the page ---

def _alias_words(text):
    """Topic words of a name: "Cats project" -> {"cats"}; "The Game of Hog" -> {"game", "hog"}."""
    text = KIND_WORD.sub(" ", _plain(text))
    return {
        word for word in re.findall(r"[a-z]+", text.lower())
        if len(word) >= 3 and word not in ALIAS_STOPWORDS
    }


def _numbered_mentions(lines):
    """(numbered title, what the page says right after it) for every numbered mention
    in the page's text: ("Project 3", ' <a href="/projects/ants/">Ants Vs. SomeBees
    (due Fri 10/23; checkpoint 1 Fri 10/16)</a>'). The text runs to the next mention,
    badge or table cell."""
    for line in lines:
        # Mentions in the page's text, not inside a tag ('<a href="/hw/hw03">').
        mentions = [
            match for match in KIND_WITH_NUMBER.finditer(line)
            if "<" not in line[:match.start()].rsplit(">", 1)[-1]
        ]
        for index, match in enumerate(mentions):
            title = _canonical_title(match.group(0))
            if not title:
                continue
            end = mentions[index + 1].start() if index + 1 < len(mentions) else len(line)
            yield title, re.split(r"«| \| ", line[match.end():end].lstrip("»"), maxsplit=1)[0][:400]


def _numbered_aliases(lines, links, page_url, assignments):
    """Numbered title ("Project 2") -> topic words and part dates the page gives for it."""
    aliases = {}
    for title, segment in _numbered_mentions(lines):
        entry = aliases.setdefault(title, {"words": set(), "days": {}})
        entry["words"] |= _alias_words(segment)
        for address, _text in HTML_LINK.findall(segment):
            entry["words"] |= _url_words(links.get(address, ""), page_url)
        # Only dates given for a part of the item ("checkpoint 1 Thu 11/19").
        text = _plain(segment)
        for qualifier in TITLE_QUALIFIER.finditer(text):
            date_match = DATE_VALUE.search(text[qualifier.end():qualifier.end() + 30])
            if date_match:
                _year, month, day = _date_parts(date_match.groupdict(), "")
                # The page's name for that part: "checkpoint 1" -> "Checkpoint 1".
                entry["days"].setdefault((month, day), clean_text(qualifier.group(0)).title())
    for assignment in assignments:
        # Keyed by the item itself: "Project 3 Checkpoint 1" adds to "Project 3".
        match = KIND_WITH_NUMBER.search(assignment["title"])
        title = _canonical_title(match.group(0)) if match else None
        if title:
            entry = aliases.setdefault(title, {"words": set(), "days": {}})
            entry["words"] |= _url_words(assignment.get("html_url"), page_url)
    return aliases


def _merge_same_deliverable(assignments, lines, links, page_url):
    """Renames items to their numbered title, then dedupes by title + due day."""
    if not assignments:
        return assignments
    aliases = _numbered_aliases(lines, links, page_url, assignments)
    for assignment in assignments:
        numbered = _numbered_title_for(assignment, aliases, page_url)
        if numbered:
            _log(f"merged name: {assignment['title']!r} is {numbered!r} on this page")
            assignment["title"] = numbered

    groups = {}
    for assignment in assignments:
        groups.setdefault(assignment["title"].casefold(), []).append(assignment)
    kept_ids = set()
    for group in groups.values():
        dated_days = {item["due"][:10] for item in group if item["due"]}
        by_day = {}
        for item in group:
            day = item["due"][:10] if item["due"] else None
            if day is None and dated_days:
                continue  # an undated mention of a deadline dated elsewhere
            best = by_day.get(day)
            if best is None:
                by_day[day] = item
                continue
            # Keep the copy with its own link; it collects the other's resources.
            keep, drop = (item, best) if best["html_url"] == page_url != item["html_url"] else (best, item)
            seen = {resource.get("link") for resource in keep.get("resources", [])}
            keep["resources"] = keep.get("resources", []) + [
                resource for resource in drop.get("resources", []) if resource.get("link") not in seen
            ]
            by_day[day] = keep
        kept_ids.update(id(item) for item in by_day.values())
        if len(group) > len(by_day):
            _log(f"merged {len(group)} listings of {group[0]['title']!r} into {len(by_day)}")
    return [assignment for assignment in assignments if id(assignment) in kept_ids]


# --- Naming: one model call over the full list to assign numbered titles ---

NAMING_SYSTEM_PROMPT = """You check the list of deadlines read from one university course homepage. The page was read in parts, so one deliverable may appear under a topic name in one part ("Robots checkpoint", "Maze project", "Sudoku") and under its number in another ("Project 3 Checkpoint 1").

You get:
- numbered_items: what the page itself says about each numbered item, for example "Project 3": ["Robot Arena (due Fri 10/23; checkpoint 1 Fri 10/16; checkpoint 2 Wed 10/21) [/projects/robots/]"]
- items: the deadlines found, each with an id, title, due date (or null) and the text of the page line it came from.

Give an item the numbered title of the deliverable it is, when the page shows they are the same: the same topic or project name, a link to the same page, or a part (checkpoint, milestone, part) whose date matches one the page gives for that numbered item. Keep the part in the title, numbered the way the page numbers it: "Robots checkpoint" due 10/16 -> "Project 3 Checkpoint 1"; "Checkpoint" due 10/21 on a line about Robot Arena -> "Project 3 Checkpoint 2".

Rules:
- A new title is "<numbered item>" or "<numbered item> <part>", where <numbered item> is one of the keys of numbered_items.
- Different deadlines keep different titles: two checkpoints, parts or milestones of one project are never given the same title.
- Leave unchanged anything that is not one of the numbered items (contests, exams, surveys) and anything you are unsure about.
- List only the items whose title should change.

Return JSON exactly as {"renames":[{"id":"i3","title":"Project 3 Checkpoint 1"}]}"""
NAMING_MAX_PAGE_NOTES = 3
NAMING_MAX_NOTES_CHARS = 8_000


def _page_notes(lines, links):
    """What the page says about each numbered item, in the page's own words."""
    notes = {}
    for title, segment in _numbered_mentions(lines):
        addresses = [address for address, _text in HTML_LINK.findall(segment) if address in links]
        note = clean_text(_plain(segment) + (f" [{', '.join(addresses[:2])}]" if addresses else ""))
        if note and note not in notes.setdefault(title, []) and len(notes[title]) < NAMING_MAX_PAGE_NOTES:
            notes[title].append(note[:300])
    # Keep the request small: drop the longest notes first if the page is very long.
    while sum(len(n) for items in notes.values() for n in items) > NAMING_MAX_NOTES_CHARS:
        title = max(notes, key=lambda t: sum(len(n) for n in notes[t]))
        notes[title].pop()
        if not notes[title]:
            del notes[title]
    return notes


def _name_items_with_model(assignments, lines, links, client, sleep, deadline=None,
                           clock=time.monotonic):
    """Applies the model's renames that match a numbered item and don't merge different dates."""
    notes = _page_notes(lines, links)
    if not notes or not assignments:
        return assignments
    if deadline is not None and clock() + GROQ_REQUEST_TIMEOUT_SECONDS > deadline:
        _log("naming: skipped, not enough time left")
        return assignments
    ids = {f"i{number}": assignment for number, assignment in enumerate(assignments, start=1)}
    _progress(f"Web sync is matching names for {len(assignments)} assignment{'' if len(assignments) == 1 else 's'}")
    payload = json.dumps({
        "numbered_items": notes,
        "items": [
            {"id": item_id, "title": a["title"], "due": a["due"],
             "line": _plain(lines[a["_line"] - 1])[:240] if a.get("_line") else ""}
            for item_id, a in ids.items()
        ],
    }, ensure_ascii=True)
    try:
        completion = _groq_request(
            client, NAMING_SYSTEM_PROMPT, payload, sleep=sleep, deadline=deadline, clock=clock,
            max_completion_tokens=OUTLINE_MAX_COMPLETION_TOKENS,
        )
        choices = getattr(completion, "choices", None)
        content = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
        renames = json.loads(content).get("renames")
        if not isinstance(renames, list):
            raise ValueError("no renames list")
    except (_RequestTooLarge, RuntimeError, ValueError, TypeError, AttributeError) as error:
        _log(f"naming: skipped ({type(error).__name__}: {str(error)[:160]})")
        return assignments

    applied, refused = [], []
    for rename in renames:
        if not isinstance(rename, dict) or rename.get("id") not in ids or not isinstance(rename.get("title"), str):
            continue
        assignment = ids[rename["id"]]
        proposed = clean_text(rename["title"])[:100]
        match = KIND_WITH_NUMBER.match(proposed)
        title = _canonical_title(proposed) if match else None
        base = _canonical_title(match.group(0)) if match else None
        if not title or base not in notes or title == assignment["title"]:
            refused.append(f"{assignment['title']!r} -> {proposed!r}")
            continue
        old_words = assignment["title"].casefold().split()
        if len(title.split()) < len(old_words) and set(title.casefold().split()) <= set(old_words):
            # A rename names a topic by its number; it never drops a part's name
            # ("Project 4 Peer Comments" is not "Project 4").
            refused.append(f"{assignment['title']!r} -> {title!r}: drops part of the name")
            continue
        clash = assignment["due"] and any(
            other is not assignment and other["title"].casefold() == title.casefold()
            and other["due"] and other["due"][:10] != assignment["due"][:10]
            for other in assignments
        )
        if clash:
            refused.append(f"{assignment['title']!r} ({assignment['due']}) -> {title!r}: another {title!r} is due on a different day")
            continue
        applied.append(f"{assignment['title']!r} -> {title!r}")
        assignment["title"] = title
    _log(f"naming: model renamed {len(applied)} item(s)"
         + (f": {'; '.join(applied[:20])}" if applied else "")
         + (f"; refused {len(refused)}: {'; '.join(refused[:8])}" if refused else ""))
    return assignments


def import_course_website(url, term="", session=None, client=None, sleep=time.sleep,
                          clock=time.monotonic):
    started = clock()
    deadline = started + _time_budget_seconds()
    if client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "WEBSITE_IMPORT_CONFIG_ERROR: Set GROQ_API_KEY to enable course website imports."
            )
        from groq import Groq

        client = Groq(api_key=api_key, timeout=GROQ_REQUEST_TIMEOUT_SECONDS, max_retries=0)

    _progress("Loading the course website")
    html, page_url = fetch_page(url, session=session, sleep=sleep)
    # When the course runs comes from the website itself when it says so; the term
    # typed for the course is used only when the site gives no clue.
    website_term = page_term(html, page_url)
    effective_term = website_term or _effective_term(term, url)
    if website_term and _year_from_term(term) and not _same_term(website_term, term):
        _log(f"the website is for {website_term}, but the course term is {term!r}; using {website_term}")

    lines, links = page_lines(html, page_url)
    _progress(f"Read {len(lines)} lines from the page")
    assignments, items_listed = extract_assignments_from_page(
        lines, links, page_url, effective_term, client, sleep, deadline=deadline, clock=clock,
    )
    # Discussions are not imported for any course for now.
    assignments = [a for a in assignments if not EXCLUDED_TITLE.match(a["title"])]
    # A date outside the course's term is a misreading: leave it for the instructor.
    first, last = term_date_range(effective_term)
    for assignment in assignments:
        if assignment["due"] and not first.isoformat() <= assignment["due"][:10] <= last.isoformat():
            _log(f"cleared {assignment['title']!r} due {assignment['due']}: outside {effective_term}")
            assignment["due"] = None
    # The model names every item with the whole list and the page's numbered items in
    # view; then code merges what is still listed twice.
    assignments = _name_items_with_model(
        assignments, lines, links, client, sleep, deadline=deadline, clock=clock,
    )
    _progress("Merging duplicate assignments")
    assignments = _merge_same_deliverable(assignments, lines, links, page_url)
    for assignment in assignments:
        assignment.pop("_line", None)
    _progress(f"Found {len(assignments)} assignment{'' if len(assignments) == 1 else 's'}")
    return {
        "course_url": url,
        "assignments": assignments,
        "pages_crawled": 1,
        "pages_skipped": 0,
        "candidates_reviewed": min(items_listed, 2000),
        "website_term": website_term,
    }


if __name__ == "__main__":
    try:
        if len(sys.argv) not in (2, 3):
            raise ValueError("Usage: website_import.py COURSE_WEBSITE_URL [COURSE_TERM]")
        print(json.dumps(import_course_website(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "")))
    except Exception as error:
        print(str(error) or "Course website import failed", file=sys.stderr)
        sys.exit(1)
