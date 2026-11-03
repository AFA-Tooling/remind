
import pandas as pd
import numpy as np

import pandas as pd
import numpy as np

print(pd.__version__)
print(np.__version__)

from pathlib import Path

BASE_DIR = Path("C:/Users/cathe/Documents/Github/remind/Analysis")
INPUTS_DIR = BASE_DIR / "inputs"
GROUPS_DIR = INPUTS_DIR / "groups"
ANONYMIZED_DIR = BASE_DIR / "anonymized"

# Folder name under inputs/ for each class. Also used (uppercased) to find
# that class's study_<CLASS>_group_1.csv / _2.csv under inputs/groups/.
CLASSES = ["cs10", "cs61a", "cs61c"]

def normalize_email(email):
    return str(email).strip().lower()

def load_group_emails(course_code):
    """Return (group1_emails, group2_emails) for one class."""
    course = course_code.upper()
    group1_path = GROUPS_DIR / f"study_{course}_group_1.csv"
    group2_path = GROUPS_DIR / f"study_{course}_group_2.csv"
    group1_emails = set(pd.read_csv(group1_path)["email"].map(normalize_email))
    group2_emails = set(pd.read_csv(group2_path)["email"].map(normalize_email))
    return group1_emails, group2_emails

def assign_group(email, group1_emails, group2_emails):
    email = normalize_email(email)
    if email in group1_emails:
        return "Group 1"
    if email in group2_emails:
        return "Group 2"
    return "None"

PII_COLUMNS = ["First Name", "Last Name", "Email"]


def process_class(course_code):
    """Load every assignment CSV for one class, tag each row with its study
    group, write an anonymized copy, and return {assignment_name: dataframe}.
    Safe to call on a class with no input files yet -- returns an empty dict.
    """
    group1_emails, group2_emails = load_group_emails(course_code)
    input_dir = INPUTS_DIR / course_code
    output_dir = ANONYMIZED_DIR / course_code
    output_dir.mkdir(parents=True, exist_ok=True)

    assignments = {}
    for csv_path in sorted(input_dir.glob("*.csv")):
        df = pd.read_csv(csv_path)
        df["Study Group"] = df["Email"].map(
            lambda email: assign_group(email, group1_emails, group2_emails)
        )
        df = df.drop(columns=PII_COLUMNS, errors="ignore")
        df.to_csv(output_dir / csv_path.name, index=False)
        assignments[csv_path.stem] = df
    return assignments

class_data = {course: process_class(course) for course in CLASSES}

for course, assignments in class_data.items():
    print(f"{course}: {len(assignments)} assignment file(s)")

def classify_submission(status, lateness):
    status = str(status).strip().lower()
    if status == "missing":
        return "Missing"
    if status == "graded":
        return "Graded" if str(lateness).strip() == "00:00:00" else "Late"
    return "Other"


CATEGORIES = ["Graded", "Late", "Missing"]

def submission_category_counts(class_data):
    """One row per (Class, Assignment, Study Group) with Graded/Late/Missing counts."""
    rows = []
    for course, assignments in class_data.items():
        for assignment_name, df in assignments.items():
            category = df.apply(
                lambda row: classify_submission(row["Status"], row["Lateness (H:M:S)"]),
                axis=1,
            )
            counts = (
                df.assign(**{"Submission Category": category})
                .groupby(["Study Group", "Submission Category"])
                .size()
                .unstack(fill_value=0)
            )
            for category_name in CATEGORIES:
                if category_name not in counts.columns:
                    counts[category_name] = 0
            counts = counts.reset_index()
            counts.insert(0, "Assignment", assignment_name)
            counts.insert(0, "Class", course)
            rows.append(counts)

    if not rows:
        return pd.DataFrame(columns=["Class", "Assignment", "Study Group", *CATEGORIES])

    combined = pd.concat(rows, ignore_index=True)
    other_cols = [
        c for c in combined.columns
        if c not in ["Class", "Assignment", "Study Group", *CATEGORIES]
    ]
    return combined[["Class", "Assignment", "Study Group", *CATEGORIES, *other_cols]]

submission_summary = submission_category_counts(class_data)
submission_summary

def submission_category_rates(counts_df):
    rates = counts_df.copy()
    total = rates[CATEGORIES].sum(axis=1)
    for category_name in CATEGORIES:
        rates[f"{category_name} Rate"] = rates[category_name] / total
    return rates


submission_rates = submission_category_rates(submission_summary)
submission_rates



