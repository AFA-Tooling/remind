import os
import pandas as pd
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Check if the API key is loaded correctly
api_key = os.getenv("OPENAI_API_KEY")

if api_key is None:
    raise ValueError("OPENAI_API_KEY not found in .env file. Please create a .env file in the same directory and add OPENAI_API_KEY=your_api_key")

# Now get the API key from the loaded environment variables
client = OpenAI(api_key=api_key)
# Load CSV Data with cache disabled
csv_file = "cs10_scrape/deadlines.csv"  # Adjust path if needed
df = pd.read_csv(csv_file, cache_dates=False)

# Debug info to verify we're using the latest data
file_modified_time = datetime.fromtimestamp(os.path.getmtime(csv_file))
print(f"CSV file last modified: {file_modified_time}")
print(f"Reading {len(df)} assignments from CSV")

# Convert date to a human-readable format
def human_readable_due_date(iso_date_str):
    try:
        due_date = datetime.fromisoformat(iso_date_str)  # Convert ISO string to datetime
        today = datetime.today()
        days_diff = (due_date.date() - today.date()).days  # Calculate difference in days

        # Format as "Month Day"
        formatted_date = due_date.strftime("%B %d")

        if days_diff > 0:
            return f"{formatted_date} (in {days_diff} days)", days_diff
        elif days_diff == 0:
            return f"{formatted_date} (today)", 0
        else:
            return f"{formatted_date} ({-days_diff} days ago, overdue)", days_diff
    except ValueError:
        return iso_date_str, None  # Return as-is if parsing fails

# Format data into a structured string
def format_project_data(df):
    formatted_text = "Here is a list of projects with their status:\n\n"
    
    # Track overdue assignments
    overdue_assignments = []
    upcoming_assignments = []
    
    for _, row in df.iterrows():
        due_date_human, days_diff = human_readable_due_date(row['due'])
        
        # Track overdue and incomplete assignments
        if days_diff is not None and days_diff < 0 and not row['done']:
            overdue_assignments.append((row['project'], days_diff))
        
        # Track upcoming and incomplete assignments
        if days_diff is not None and days_diff >= 0 and not row['done']:
            upcoming_assignments.append((row['project'], days_diff))
        
        formatted_text += (
            f"- **{row['project']}**\n"
            f"  - Due: {due_date_human}\n"
            f"  - Completed: {'Yes' if row['done'] else 'No'}\n"
            f"  - Submission Time: {row['time_submitted'] if pd.notna(row['time_submitted']) else 'Not submitted'}\n\n"
        )
    
    # Add summary information about overdue and upcoming assignments
    summary_text = ""
    if overdue_assignments:
        overdue_assignments.sort(key=lambda x: x[1])  # Sort by days (most overdue first)
        summary_text += "⚠️ OVERDUE ASSIGNMENTS ⚠️\n"
        for name, days in overdue_assignments:
            summary_text += f"- {name}: {abs(days)} days overdue\n"
        summary_text += "\n"
    
    if upcoming_assignments:
        upcoming_assignments.sort(key=lambda x: x[1])  # Sort by days (closest due date first)
        next_assignment = upcoming_assignments[0]
        days_text = "due today" if next_assignment[1] == 0 else f"due in {next_assignment[1]} days"
        summary_text += f"Next assignment: {next_assignment[0]} ({days_text})\n\n"
    
    return summary_text + formatted_text

formatted_data = format_project_data(df)

# Predefined Query (Choose one)
queries = {
    "next_due": "What is my next assignment that is not completed and is due soon? Also highlight any overdue assignments.",
    "checklist": "Give me an overview of all my assignments and their status. Highlight any overdue assignments.",
    "urgent": "Which assignments are overdue or close to the deadline but not done?",
}

# Select the query you want to use
selected_query = queries["next_due"]  # Change to "checklist" or "urgent" as needed

# Create a structured prompt
prompt = f"{formatted_data}\n\nUser Query: {selected_query}"

# Query OpenAI API
completion = client.chat.completions.create(
    model="gpt-3.5-turbo",  # Use a cheaper model for testing
    messages=[{"role": "user", "content": prompt}]
)

# Print the AI's response
print("\nGPT-3.5 Turbo Response:\n", completion.choices[0].message.content)