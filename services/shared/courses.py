"""Per-course config: categorization rules, UI categories, and feature flags.

Source of truth: services/shared/courses.json
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

COURSES_JSON = Path(__file__).resolve().parent / "courses.json"


@lru_cache(maxsize=1)
def load_courses_config() -> Dict[str, Any]:
    with open(COURSES_JSON, encoding="utf-8") as f:
        return json.load(f)


def default_course_code() -> str:
    return str(load_courses_config().get("default_course_code") or "CS61A")


def get_course(course_code: Optional[str]) -> Optional[Dict[str, Any]]:
    code = (course_code or "").strip().upper()
    if not code:
        return None
    courses = load_courses_config().get("courses") or {}
    return courses.get(code)


def list_course_codes() -> List[str]:
    return sorted((load_courses_config().get("courses") or {}).keys())


def _category_by_id(course: Dict[str, Any], category_id: str) -> Optional[Dict[str, Any]]:
    needle = (category_id or "").strip().lower()
    for cat in course.get("categories") or []:
        if str(cat.get("id") or "").lower() == needle:
            return cat
    return None


def category_name(course: Dict[str, Any], category_id: str) -> Optional[str]:
    cat = _category_by_id(course, category_id)
    if not cat:
        return None
    return cat.get("name") or str(cat.get("id") or "").capitalize()


def default_category_prefs(course_code: Optional[str] = None) -> Dict[str, bool]:
    """All categories enabled for a course (or the default course)."""
    course = get_course(course_code) or get_course(default_course_code()) or {}
    prefs: Dict[str, bool] = {}
    for cat in course.get("categories") or []:
        cat_id = str(cat.get("id") or "").strip().lower()
        if cat_id:
            prefs[cat_id] = True
    return prefs


def _matcher_hits(name: str, matcher: Dict[str, Any]) -> bool:
    patterns = [str(p).lower() for p in (matcher.get("patterns") or []) if p]
    if not patterns:
        return False
    mode = str(matcher.get("match") or "prefix").lower()
    if mode == "contains":
        return any(p in name for p in patterns)
    if mode == "exact":
        return name in patterns
    # default: prefix
    return any(name.startswith(p) for p in patterns)


def categorize_assignment(
    course_code: Optional[str],
    *candidates: Optional[str],
    mode: str = "reminder",
) -> Optional[str]:
    """Map an assignment label to a category *name* (e.g. \"Lab\", \"Project\").

    mode=\"ingest\": used when syncing GradeSync sheet tabs. Matchers with
    ingest=false are skipped; unmatched returns None when ingest_unmatched is
    \"skip\" (so callers can drop unrecognized tabs).

    mode=\"reminder\": used by the daily reminder pipeline. Unmatched falls back
    to reminder_unmatched (CS61A → Project) so every deadline still has a
    category for prefs gating.
    """
    course = get_course(course_code) or get_course(default_course_code())
    if not course:
        return None

    for raw in candidates:
        if not raw:
            continue
        name = str(raw).strip().lower()
        if not name:
            continue
        for matcher in course.get("matchers") or []:
            if mode == "ingest" and matcher.get("ingest") is False:
                continue
            if not _matcher_hits(name, matcher):
                continue
            cat_id = str(matcher.get("category") or "").strip().lower()
            return category_name(course, cat_id) or cat_id.capitalize()

    unmatched_key = "ingest_unmatched" if mode == "ingest" else "reminder_unmatched"
    unmatched = course.get(unmatched_key)
    if unmatched is None or unmatched == "skip":
        return None
    return category_name(course, str(unmatched)) or str(unmatched).capitalize()


def should_apply_project_early(
    course_code: Optional[str],
    category_name_value: Optional[str],
    *label_parts: Optional[str],
) -> bool:
    """Whether the day-early project shift applies for this assignment."""
    course = get_course(course_code) or get_course(default_course_code())
    if not course:
        return False
    feature = (course.get("features") or {}).get("project_early_reminder") or {}
    if not feature.get("enabled"):
        return False
    expected = category_name(course, str(feature.get("category") or "project"))
    if not expected or category_name_value != expected:
        return False
    label = " ".join(str(p or "") for p in label_parts).lower()
    for needle in feature.get("exclude_contains") or []:
        if str(needle).lower() in label:
            return False
    return True


def public_course_config(course_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Subset of course config safe to send to the student dashboard."""
    course = get_course(course_code)
    if not course:
        return None
    features = course.get("features") or {}
    project_early = features.get("project_early_reminder") or {}
    release = features.get("release_reminder") or {}
    return {
        "course_code": (course_code or "").strip().upper(),
        "display_name": course.get("display_name") or course_code,
        "categories": [
            {
                "id": cat.get("id"),
                "label": cat.get("label") or cat.get("name") or cat.get("id"),
            }
            for cat in (course.get("categories") or [])
            if cat.get("id")
        ],
        "features": {
            "project_early_reminder": {
                "enabled": bool(project_early.get("enabled")),
                "ui_label": project_early.get("ui_label")
                or "Remind me a day earlier for projects",
            },
            "release_reminder": {
                "enabled": bool(release.get("enabled")),
                "ui_label": release.get("ui_label")
                or "Notify me when a new assignment is released",
            },
        },
    }
