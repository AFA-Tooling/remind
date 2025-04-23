import os
import pandas as pd
from df_to_message_requests import process_assignment_file 

# Load shared data
deadlines_df = pd.read_csv('shared_data/deadlines.csv')
notification_frequency_df = pd.read_csv('shared_data/notification_frequency.csv')

# List all assignment files in output/
assignment_files = [
    f for f in os.listdir('output')
    if f.endswith('.csv') and f not in ['deadlines.csv', 'notification_frequency.csv']
]

# Run the processing for each assignment file
for file_name in assignment_files:
    print(f"\n📄 Processing: {file_name}")
    try:
        process_assignment_file(file_name, deadlines_df, notification_frequency_df)
    except Exception as e:
        print(f"❌ Error processing {file_name}: {e}")
