"""
Fun and motivating email message templates for student reminders.
Each template incorporates assignment name, resources, and personalized greetings.
"""
import random
from typing import List


# Collection of motivating and fun email message templates.
# {resources_section} is replaced with the intro + bulleted resources when the
# assignment has resources, or with an empty string when it has none (so the
# "helpful resources" block never shows up empty).
EMAIL_TEMPLATES: List[str] = [
    """Hey {student_name}! 👋

Just a friendly reminder that "{assignment_name}" is still on your to-do list!
{resources_section}
Remember: every expert was once a beginner. You've totally got this! 🚀

– The AutoRemind Team""",

    """Hi {student_name}! ✨

We noticed "{assignment_name}" is still waiting for you. No worries though – we've got your back!
{resources_section}
You're capable of amazing things. Time to show yourself what you can do! 💪

– The AutoRemind Team""",

    """Hello {student_name}! 🌟

Quick heads up: "{assignment_name}" is still pending. But hey, that's totally okay – you've got this!
{resources_section}
Think of this as your moment to shine. Let's make it happen! ⭐

– The AutoRemind Team""",

    """Hey {student_name}! 🎯

Just checking in – "{assignment_name}" is still on your radar. Ready to tackle it?
{resources_section}
You're stronger than you think and smarter than you know. Time to prove it to yourself! 🔥

– The AutoRemind Team""",

    """Hi {student_name}! 💡

Friendly reminder: "{assignment_name}" is still waiting for you. But don't stress – you've got everything you need!
{resources_section}
Every journey starts with a single step. This is yours – let's go! 🌈

– The AutoRemind Team"""
]


def get_random_email_template() -> str:
    """
    Get a random email template from the collection.
    
    Returns:
        A randomly selected email template string
    """
    return random.choice(EMAIL_TEMPLATES)


def format_email_body(template: str, student_name: str, assignment_name: str, resources_text: str) -> str:
    """
    Format an email template with the provided values.

    Args:
        template: The email template string with placeholders
        student_name: Student's name
        assignment_name: Name of the assignment
        resources_text: Formatted resources text (can be empty string)

    Returns:
        Formatted email body string
    """
    # Only include the "helpful resources" block when there are resources.
    # With none, the section collapses to nothing so it never shows up empty.
    if resources_text and resources_text.strip():
        resources_section = f"\nHere are some helpful resources to get you started:\n{resources_text}\n"
    else:
        resources_section = ""

    return template.format(
        student_name=student_name,
        assignment_name=assignment_name,
        resources_section=resources_section
    )


def get_motivating_email_body(student_name: str, assignment_name: str, resources_text: str) -> str:
    """
    Get a randomly selected, formatted motivating email body.
    
    Args:
        student_name: Student's name
        assignment_name: Name of the assignment
        resources_text: Formatted resources text (can be empty string)
        
    Returns:
        A complete, formatted email body with a randomly selected template
    """
    template = get_random_email_template()
    return format_email_body(template, student_name, assignment_name, resources_text)

