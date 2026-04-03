"""
Course branding configuration for HTML email templates.
Maps course codes to their visual branding elements.
"""

COURSE_BRANDING = {
    "CS61A": {
        "primary_color": "#3E5F3A",
        "secondary_color": "#E7EFD9",
        "header_title": "CS 61A - Structure and Interpretation"
    },
    "CS61B": {
        "primary_color": "#4A90A4",
        "secondary_color": "#E3F2FD",
        "header_title": "CS 61B - Data Structures"
    },
    "CS10": {
        "primary_color": "#2E86AB",
        "secondary_color": "#E3F2FD",
        "header_title": "CS 10 - The Beauty and Joy of Computing"
    },
    "DATA8": {
        "primary_color": "#6B5B95",
        "secondary_color": "#F0EBF8",
        "header_title": "Data 8 - Foundations of Data Science"
    },
    "DEFAULT": {
        "primary_color": "#3E5F3A",
        "secondary_color": "#E7EFD9",
        "header_title": "AutoRemind"
    }
}


def get_branding(course_code: str) -> dict:
    """Get branding for a course, falling back to default if not found."""
    if not course_code:
        return COURSE_BRANDING["DEFAULT"]
    return COURSE_BRANDING.get(course_code.upper(), COURSE_BRANDING["DEFAULT"])
