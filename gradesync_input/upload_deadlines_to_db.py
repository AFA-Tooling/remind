"""
Upload deadlines from CSV file to Supabase database.

This script reads deadlines.csv and uploads it to the deadlines table in Supabase.
It handles duplicates by updating existing records based on the unique constraint.
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from supabase import Client, create_client


def load_supabase_env() -> Dict[str, str]:
    """Load Supabase credentials from .env file."""
    # Try loading from current directory first, then project root
    current_dir = Path(__file__).resolve().parent
    env_paths = [
        current_dir / ".env",
        current_dir.parent / ".env",
        current_dir.parent / "remind" / ".env",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Loaded .env from: {env_path}")
            break
    else:
        # Fallback to default dotenv behavior
        load_dotenv()
        print("⚠️  Using default .env loading (may not find file)")

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


def parse_deadline(value: str) -> Optional[datetime]:
    """Parse a deadline string into a datetime object."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_deadlines_csv(csv_path: Path) -> List[Dict[str, any]]:
    """Load deadlines from CSV file and return as list of dictionaries."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Deadlines CSV not found: {csv_path}")

    deadlines = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            row = {(key or "").strip(): (value or "") for key, value in raw_row.items()}
            
            course_code = row.get("course_code", "").strip()
            assignment_code = row.get("assignment_code", "").strip() or None
            assignment_name = row.get("assignment_name", "").strip()
            due_str = row.get("due", "").strip()
            
            if not assignment_name:
                print(f"⚠️  Skipping row with missing assignment_name: {row}")
                continue
            
            due_date = parse_deadline(due_str)
            if not due_date:
                print(f"⚠️  Skipping row with invalid due date '{due_str}': {row}")
                continue

            deadlines.append({
                "course_code": course_code or "",
                "assignment_code": assignment_code,
                "assignment_name": assignment_name,
                "due": due_date.isoformat(),
            })

    return deadlines


def upload_deadlines_to_supabase(
    supabase: Client, deadlines: List[Dict[str, any]], *, upsert: bool = True
) -> Dict[str, int]:
    """
    Upload deadlines to Supabase.
    
    Args:
        supabase: Supabase client instance
        deadlines: List of deadline dictionaries
        upsert: If True, update existing records; if False, skip duplicates
    
    Returns:
        Dictionary with counts of inserted, updated, and error records
    """
    stats = {"inserted": 0, "updated": 0, "errors": 0}
    
    for deadline in deadlines:
        try:
            if upsert:
                # Use upsert to insert or update
                result = supabase.table("deadlines").upsert(deadline).execute()
                if result.data:
                    # Check if it was an insert or update by checking if id was generated
                    if result.data[0].get("id"):
                        stats["inserted"] += 1
                    else:
                        stats["updated"] += 1
            else:
                # Try to insert, skip if duplicate
                try:
                    result = supabase.table("deadlines").insert(deadline).execute()
                    if result.data:
                        stats["inserted"] += 1
                except Exception as e:
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        stats["updated"] += 1  # Count as updated for stats
                    else:
                        raise
        except Exception as e:
            print(f"❌ Error uploading deadline {deadline.get('assignment_name', 'unknown')}: {e}")
            stats["errors"] += 1
    
    return stats


def main():
    """Main function to upload deadlines from CSV to Supabase."""
    print("=" * 60)
    print("Uploading Deadlines to Supabase")
    print("=" * 60)
    
    # 1. Setup paths
    current_dir = Path(__file__).resolve().parent
    csv_path = current_dir / "shared_data" / "deadlines.csv"
    
    # 2. Load Supabase credentials
    print("\n📋 Step 1: Loading Supabase credentials...")
    try:
        config = load_supabase_env()
        print("✅ Credentials loaded")
    except ValueError as e:
        print(f"❌ Error: {e}")
        return
    
    # 3. Connect to Supabase
    print("\n🔌 Step 2: Connecting to Supabase...")
    try:
        supabase: Client = create_client(config["url"], config["service_role_key"])
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Error connecting to Supabase: {e}")
        return
    
    # 4. Load deadlines from CSV
    print(f"\n📂 Step 3: Loading deadlines from {csv_path}...")
    try:
        deadlines = load_deadlines_csv(csv_path)
        print(f"✅ Loaded {len(deadlines)} deadline(s) from CSV")
        
        # Show preview
        if deadlines:
            print("\n📋 Preview of deadlines to upload:")
            for i, deadline in enumerate(deadlines[:5], 1):
                print(f"   {i}. {deadline['assignment_name']} ({deadline['course_code']}) - Due: {deadline['due']}")
            if len(deadlines) > 5:
                print(f"   ... and {len(deadlines) - 5} more")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        return
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")
        return
    
    # 5. Upload to Supabase
    print("\n⬆️  Step 4: Uploading deadlines to Supabase...")
    try:
        stats = upload_deadlines_to_supabase(supabase, deadlines, upsert=True)
        
        print("\n✅ Upload complete!")
        print(f"   Inserted: {stats['inserted']}")
        print(f"   Updated: {stats['updated']}")
        print(f"   Errors: {stats['errors']}")
        
        if stats["errors"] > 0:
            print("\n⚠️  Some deadlines failed to upload. Check the errors above.")
    except Exception as e:
        print(f"❌ Error uploading to Supabase: {e}")
        return
    
    print("\n" + "=" * 60)
    print("✅ Process complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

