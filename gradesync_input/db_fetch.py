"""Utility script to fetch data from Supabase using .env credentials."""

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from supabase import Client, create_client


# Default to the students table so running without flags shows roster data.
DEFAULT_TABLE = "students"


def mask_secret(secret: str) -> str:
    """Return a masked version of a secret for logging."""

    if not secret:
        return "(empty)"
    if len(secret) <= 8:
        return "***masked***"
    return f"{secret[:4]}...{secret[-4:]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch rows from a Supabase table defined in .env"
    )
    parser.add_argument(
        "--table",
        default=os.getenv("SUPABASE_TABLE", DEFAULT_TABLE),
        help=f"Supabase table to query (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of returned rows",
    )
    return parser.parse_args()


def load_supabase_env() -> Dict[str, str]:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    required_vars = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return {
        "url": os.environ["SUPABASE_URL"],
        "service_role_key": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    }


def fetch_table_rows(supabase: Client, table_name: str, limit: int | None) -> List[Dict[str, Any]]:
    query = supabase.table(table_name).select("*")
    if limit:
        query = query.limit(limit)

    response = query.execute()

    if getattr(response, "error", None):
        raise RuntimeError(f"Supabase error: {response.error}")

    return response.data or []


def main() -> None:
    args = parse_args()

    config = load_supabase_env()

    print("Connecting to Supabase...")
    print(f"Project URL: {config['url']}")
    print(f"Service role key: {mask_secret(config['service_role_key'])}")

    supabase: Client = create_client(config["url"], config["service_role_key"])

    print(f"Fetching data from table '{args.table}'")
    rows = fetch_table_rows(supabase, args.table, args.limit)

    print(f"Retrieved {len(rows)} rows.")
    for idx, row in enumerate(rows, start=1):
        print(f"Row {idx}: {row}")


if __name__ == "__main__":
    main()


"""
next steps:
want to add:
read from students and fetch deadline from deadlines.csv
find column with assingmetn from student (offset) and calculate their personal deadline

ie if deadline is 11/1/2025
and offset for student is +1 then studetn personal deadline is 11/2/2025 etc 

and then we could get student notification frequency and if student personal assingmetn deadline
is within notifciation frequnecy then we send them a message ...?


so we draft the message like:

msg = 
"hey student name
u have the following uocoming assingments due

upcoming assignmetn list ... 
due date: 
"

so we fetch the students contact info/ whatever we have (check if theyve opted in for email service/ phone service/ discord etc)
and if so then we 

if enrolled in text service:
    send_tetx(message)
 simialr for email and discrod etc ..
this functionality isnt made yet but lets abstract away? assume we can pass the message
on to the func etc ?


next step part 2:

for the upcoming assignment for whcih the student has a deadline coming up,
ex: PROJ01, 
we search that assignmetn up in the 
"assignment_resources" table and find the assignment full name and resources for it

so like for proj02
assignment_name is Project 2: spelling bee

resource_type, resource_name, link
Reading
Proj 1 Walkthrough Slides
https://drive.google.com/file/d/1


so we can add that to the message we send like
u have upcomign assignmetn proj2  spelling bee

u migh tfind these resources helpful ...
links to walkthough etc
if ur facing issues etc 

"""