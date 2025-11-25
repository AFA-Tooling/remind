import os
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file in the same directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

# --- connection settings ---
# Get database URI from environment variable
DB_URI = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URI")

if not DB_URI:
    print("❌ Error: DATABASE_URL or SUPABASE_DB_URI environment variable not set")
    print("Please set the database connection string in your .env file")
    exit(1)

# --- connect to database ---
try:
    conn = psycopg2.connect(DB_URI)
    print("✅ Connected to Supabase database!")
except Exception as e:
    print("❌ Connection error:", e)
    exit()

# --- query data ---
query = """
SELECT
    course_code,
    assignment_code,
    assignment_name,
    resource_type,
    resource_name,
    link,
    deadline
FROM assignment_resources
ORDER BY course_code, assignment_code;
"""

# --- load into pandas DataFrame ---
df = pd.read_sql(query, conn)

# --- close connection ---
conn.close()

# --- show the data ---
print(df)
