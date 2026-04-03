"""
HTML email template rendering with course branding support.
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from templates.branding import get_branding

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _render_variables(template: str, context: Dict[str, Any]) -> str:
    """Replace {{variable}} with context values."""
    def get_nested(ctx, key):
        parts = key.split('.')
        val = ctx
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                return None
        return val

    def replace(match):
        key = match.group(1).strip()
        value = get_nested(context, key)
        return str(value) if value is not None else ''

    return re.sub(r'\{\{([^#/}]+?)\}\}', replace, template)


def _render_conditionals(template: str, context: Dict[str, Any]) -> str:
    """Handle {{#if var}}...{{/if}} blocks."""
    def get_nested(ctx, key):
        parts = key.split('.')
        val = ctx
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                return None
        return val

    pattern = r'\{\{#if\s+(\S+)\}\}(.*?)\{\{/if\}\}'
    def replace(match):
        key = match.group(1)
        content = match.group(2)
        value = get_nested(context, key)
        return content if value else ''
    return re.sub(pattern, replace, template, flags=re.DOTALL)


def _render_loops(template: str, context: Dict[str, Any]) -> str:
    """Handle {{#each items}}...{{/each}} blocks."""
    pattern = r'\{\{#each\s+(\S+)\}\}(.*?)\{\{/each\}\}'

    def replace(match):
        key = match.group(1)
        item_template = match.group(2)
        items = context.get(key, [])
        if not items or not isinstance(items, list):
            return ''
        rendered_items = []
        for item in items:
            rendered = item_template
            if isinstance(item, dict):
                # Also include parent context for colors
                merged = {**context, **item}
                rendered = _render_variables(rendered, merged)
            rendered_items.append(rendered)
        return ''.join(rendered_items)

    return re.sub(pattern, replace, template, flags=re.DOTALL)


def render_template(template_name: str, context: Dict[str, Any]) -> str:
    """Render an HTML template with the given context."""
    template_path = TEMPLATES_DIR / f"{template_name}.html"
    base_path = TEMPLATES_DIR / "base.html"

    with open(template_path, 'r') as f:
        content_template = f.read()

    with open(base_path, 'r') as f:
        base_template = f.read()

    # Render content first
    rendered_content = _render_conditionals(content_template, context)
    rendered_content = _render_loops(rendered_content, context)
    rendered_content = _render_variables(rendered_content, context)

    # Insert into base
    context['content'] = rendered_content

    # Render base template
    final_html = _render_variables(base_template, context)
    final_html = _render_conditionals(final_html, context)

    return final_html


def render_reminder_email(
    student_name: str,
    assignment_name: str,
    resources: Optional[List[Dict]] = None,
    course_code: str = "",
    unsubscribe_url: str = "",
    assignments_url: str = ""
) -> str:
    """Render a reminder email with course branding."""
    branding = get_branding(course_code)

    context = {
        "student_name": student_name,
        "assignment_name": assignment_name,
        "resources": resources or [],
        "course_code": course_code,
        "subject": f"Reminder: {assignment_name} is due soon!",
        "unsubscribe_url": unsubscribe_url or "#",
        "assignments_url": assignments_url or "#",
        **branding
    }

    return render_template("reminder", context)


def render_welcome_email(
    student_name: str,
    channels: Dict[str, Any],
    days_before: int,
    course_code: str = "",
    settings_url: str = ""
) -> str:
    """Render a welcome email."""
    branding = get_branding(course_code)

    context = {
        "student_name": student_name,
        "channels": channels,
        "days_before": days_before,
        "course_code": course_code,
        "subject": "Welcome to AutoRemind!",
        "settings_url": settings_url or "#",
        "unsubscribe_url": "#",
        **branding
    }

    return render_template("welcome", context)
