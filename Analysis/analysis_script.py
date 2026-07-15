import pandas as pd

LAB3_PATH = r"C:\Users\cathe\Downloads\Lab 3 - 2026-07-02 Comma delimited CSV.csv"
GROUP1_PATH = r"C:\Users\cathe\Downloads\study_group_1.csv"
GROUP2_PATH = r"C:\Users\cathe\Downloads\study_group_2.csv"
OUTPUT_PATH = r"C:\Users\cathe\Documents\Github\remind\Analysis\Lab 3 - 2026-07-02 with study group.csv"


def normalize_email(email):
    return str(email).strip().lower()


def main():
    lab3 = pd.read_csv(LAB3_PATH)
    group1_emails = set(pd.read_csv(GROUP1_PATH)["email"].map(normalize_email))
    group2_emails = set(pd.read_csv(GROUP2_PATH)["email"].map(normalize_email))

    def assign_group(email):
        email = normalize_email(email)
        in_group1 = email in group1_emails
        in_group2 = email in group2_emails
        if in_group1 and in_group2:
            return "Both"
        if in_group1:
            return "Group 1"
        if in_group2:
            return "Group 2"
        return "None"

    lab3["Study Group"] = lab3["Email"].map(assign_group)
    lab3.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(lab3)} rows to {OUTPUT_PATH}")
    print(lab3["Study Group"].value_counts())


if __name__ == "__main__":
    main()
