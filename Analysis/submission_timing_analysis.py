import pandas as pd

GROUP1_PATH = "/Users/irenechung/Downloads/study_group_1.csv"  # AutoRemind
GROUP2_PATH = "/Users/irenechung/Downloads/study_group_2.csv"  # Waitlist
OUTPUT_DIR = "/Users/irenechung/Desktop/autoremind-repo/Analysis/output"

# Only these are consented, randomized study participants. "None" (never
# consented) and "Both" (bad data) are excluded from all comparison stats.
STUDY_GROUPS_FOR_ANALYSIS = ["AutoRemind", "Waitlist"]

ASSIGNMENTS = [
    {
        "name": "Hog",
        "path": "/Users/irenechung/Downloads/HogSheet.csv",
        "deadline": pd.Timestamp("2026-07-07 23:59:00-0700"),
    },
    {
        "name": "Hog Checkpoint",
        "path": "/Users/irenechung/Downloads/HogCheckpointAnalysis.csv",
        "deadline": pd.Timestamp("2026-07-01 23:59:00-0700"),
    },
    {
        "name": "Cats",
        "path": "/Users/irenechung/Downloads/cats.csv",
        "deadline": pd.Timestamp("2026-07-17 23:59:00-0700"),
    },
    {
        "name": "Cats Checkpoint",
        "path": "/Users/irenechung/Downloads/cats-checkpoint.csv",
        "deadline": pd.Timestamp("2026-07-14 23:59:00-0700"),
    },
    {
        "name": "HW 2",
        "path": "/Users/irenechung/Downloads/hw-2.csv",
        "deadline": pd.Timestamp("2026-07-08 23:59:00-0700"),
    },
    {
        "name": "HW 3",
        "path": "/Users/irenechung/Downloads/hw-3.csv",
        "deadline": pd.Timestamp("2026-07-15 23:59:00-0700"),
    },
    {
        "name": "Lab 3",
        "path": "/Users/irenechung/Downloads/lab-3.csv",
        "deadline": pd.Timestamp("2026-07-02 23:59:00-0700"),
    },
    {
        "name": "Lab 4",
        "path": "/Users/irenechung/Downloads/lab-4.csv",
        "deadline": pd.Timestamp("2026-07-07 23:59:00-0700"),
    },
    {
        "name": "Lab 5",
        "path": "/Users/irenechung/Downloads/lab-5.csv",
        "deadline": pd.Timestamp("2026-07-09 23:59:00-0700"),
    },
     {
        "name": "Lab 6",
        "path": "/Users/irenechung/Downloads/lab-6.csv",
        "deadline": pd.Timestamp("2026-07-16 23:59:00-0700"),
    },
]


def normalize_email(email):
    return str(email).strip().lower()


def load_groups():
    group1_emails = set(pd.read_csv(GROUP1_PATH)["email"].map(normalize_email))
    group2_emails = set(pd.read_csv(GROUP2_PATH)["email"].map(normalize_email))
    return group1_emails, group2_emails


def assign_group(email, group1_emails, group2_emails):
    email = normalize_email(email)
    in_group1 = email in group1_emails
    in_group2 = email in group2_emails
    if in_group1 and in_group2:
        return "Both"
    if in_group1:
        return "AutoRemind"
    if in_group2:
        return "Waitlist"
    return "None"


def process_assignment(name, path, deadline, group1_emails, group2_emails):
    df = pd.read_csv(path)
    df["Study Group"] = df["Email"].map(lambda e: assign_group(e, group1_emails, group2_emails))
    df["Assignment"] = name

    submitted = df[df["Status"] == "Graded"].copy()
    submitted["Submission Time"] = pd.to_datetime(submitted["Submission Time"])
    submitted["Time Before Deadline"] = deadline - submitted["Submission Time"]
    submitted["Days Before Deadline"] = submitted["Time Before Deadline"].dt.total_seconds() / 86400

    df = df.join(submitted[["Time Before Deadline", "Days Before Deadline"]])

    out_path = f"{OUTPUT_DIR}/{name.replace(' ', '_').lower()}_timing.csv"
    df.to_csv(out_path, index=False)

    # Only AutoRemind/Waitlist are in-study, consented comparison groups.
    # "None" (never consented) and "Both" (bad data) are excluded from stats.
    in_study = df[df["Study Group"].isin(STUDY_GROUPS_FOR_ANALYSIS)]

    print(f"=== {name} ===")
    print(f"Wrote {len(df)} rows to {out_path}")
    print(in_study["Study Group"].value_counts(), "\n")

    stats = in_study.groupby("Study Group")["Days Before Deadline"].agg(["mean", "median", "count"])
    print(stats, "\n")

    return df


def main():
    group1_emails, group2_emails = load_groups()

    all_dfs = []
    for a in ASSIGNMENTS:
        df = process_assignment(a["name"], a["path"], a["deadline"], group1_emails, group2_emails)
        all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True)
    combined_path = f"{OUTPUT_DIR}/combined_timing.csv"
    combined.to_csv(combined_path, index=False)
    print(f"=== Combined across {len(ASSIGNMENTS)} assignments ===")
    print(f"Wrote {len(combined)} rows to {combined_path}\n")

    in_study = combined[combined["Study Group"].isin(STUDY_GROUPS_FOR_ANALYSIS)]

    print("Average days before deadline, by Study Group (all assignments pooled):")
    print(in_study.groupby("Study Group")["Days Before Deadline"].agg(["mean", "median", "count"]), "\n")

    print("Average days before deadline, by Assignment x Study Group:")
    print(in_study.groupby(["Assignment", "Study Group"])["Days Before Deadline"].agg(["mean", "median", "count"]))


if __name__ == "__main__":
    main()
