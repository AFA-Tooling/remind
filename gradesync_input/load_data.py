import pandas as pd
import psycopg2

# --- connection settings ---
DB_URI = "postgresql://postgres:LWOj2GLk72BAsoH5@db.dvtmavnxogjaezfuqnqo.supabase.co:5432/postgres"

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
