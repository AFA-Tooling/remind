# Get the data from the sample_data folder
import os
import pandas as pd
import re
from datetime import datetime

def process_assignment_file(file_name, deadlines_df, notification_frequency_df):
    # ------------------------------
    # Step 1: Get the Files
    # ------------------------------

    files_in_current_directory = os.listdir('.')
    print(files_in_current_directory)

    # Read the data from the sample_data folder and convert to a dataframe
    def get_data(file_name):
        # Get the path to the sample_data folder
        folder = 'output/'
        file_path = os.path.join(folder, file_name)

        # Read the data from the CSV file
        df = pd.read_csv(file_path)

        return df

    assignment_df = get_data(file_name)
    # Print the first 5 rows of the dataframe
    print(assignment_df.head())


    # ------------------------------
    # Step 2: Integrate with Deadlines
    # ------------------------------

    # Iterate through the assignment_filtered_df, and for each row, add on the due date based on joining the project3_filtered_df and the deadlines_df
    def get_due_date(row):
        # Get the project name from the row
        project_name = row['assignment']
    
        # Get the due date from the deadlines_df
        if project_name not in deadlines_df['assignment'].values:
            due_date = pd.NaT
        else:
            due_date = deadlines_df.loc[deadlines_df['assignment'] == project_name, 'due'].values[0]
        return due_date

    assignment_df['due date'] = assignment_df.apply(get_due_date, axis=1)
    print(assignment_df.head())

    # Convert the due date and submission time to datetime objects, in order to compare the dates for the date difference
    assignment_df['submission time'] = pd.to_datetime(assignment_df['submission time'], errors='coerce', utc=True)
    assignment_df['due date'] = pd.to_datetime(assignment_df['due date'], errors='coerce')
    print(assignment_df.head())


    # ------------------------------
    # Step 3: Integrate with Notification Frequency
    # ------------------------------

    # Match the first and last name column from the assignment_filtered_df with the first name and last name column from the notification_frequency_df 
    def get_notification_frequency(row):
        first_name = row['name']

        # Correct structure: [ROW CONDITION, COLUMN NAME]
        match = notification_frequency_df.loc[
            (notification_frequency_df['name'] == first_name), 
            'notification_frequency' 
        ]

        # If there is a match, return the notification frequency
        if not match.empty:
            return match.values[0]
        else:
            # Make the default reminder frequency = 3 days before the due date
            return 3

    assignment_df['notification_frequency'] = assignment_df.apply(get_notification_frequency, axis=1)
    print("Merged DataFrame with Notification Frequency:")
    print(assignment_df.head())

    # Convert the notification_frequency column in assignment_filtered_df to a datetime object
    assignment_df['notification_frequency'] = assignment_df['notification_frequency'].apply(lambda x: pd.Timedelta(days=x))
    print("Converted notification_frequency to timedelta:")
    print(assignment_df.head())


    # ------------------------------
    # Step 4: Date Comparison Logic
    # ------------------------------

    # Get the difference between the due date and the current date
    TODAY_DATE = pd.to_datetime(datetime.now()).normalize()
    assignment_df['date_diff'] = assignment_df['due date'] - TODAY_DATE
    
    assignment_df.head()

    notification_days = pd.to_timedelta(assignment_df['notification_frequency']).dt.days
    date_diff_days = pd.to_timedelta(assignment_df['date_diff']).dt.days
    
    assignment_df['is_equal'] = notification_days == date_diff_days
    print("Successfully compared the notification frequency and the difference with today's date:")
    print(assignment_df.head())

    # ------------------------------
    # Step 5: Create Missing Students DataFrame
    # ------------------------------
    """
    What will the code do:			
    1. Iterate through every single row in this table			
    2. Student SID has not submitted assignment, status = 'missing' from student_data_one_assignment AND today_date == due_date - notification_freq			
    3. Append that student, row, assignment to the message_requests temporary dataframe			
    4. Continue iterating through every single one			
    """

    # See which rows where row['Status'] == 'missing' and row['is_equal'] == True:
    missing_students_df = assignment_df[(assignment_df['status'] == 'Missing') & (assignment_df['is_equal'] == True)]
    missing_students_df.head()

    # Now create a message_requests column in the merged_df dataframe with the f_string message
    def create_message(row):
        # Get the project name from the row
        assignment_name = row['assignment']

        notification_frequency = row['notification_frequency']

        first_name = row["name"]

        # Create the message
        message = f"Dear {first_name}, your {assignment_name} assignment is missing and it is due in {notification_frequency}. Please submit it as soon as possible."

        return message

    # Create the message_requests column in the merged_df dataframe
    message_requests_df = missing_students_df.copy()
    message_requests_df['message_requests'] = message_requests_df.apply(create_message, axis=1)
    print("Message Requests DataFrame:")
    print(message_requests_df.head())


    # ------------------------------
    # Step 6: Export missing students to csv
    # ------------------------------

    # Simplify this down to the information that is necessary
    message_requests_df_condensed = message_requests_df[['name', 'sid', 'email', 'assignment', 'message_requests']]
    print("Condensed Message Requests DataFrame:")
    print(message_requests_df_condensed.head())

    if message_requests_df_condensed.empty:
        print("No students matched the notification criteria. Skipping CSV generation.")
        return 

    def _safe_filename_basic(name: str) -> str:
       """
       Return a Windows-safe filename by replacing ':' and runs of '*' with ' - ', etc
       """
       cleaned = name.replace(":", " - ")
       cleaned = re.sub(r'\*+', ' - ', cleaned)
       cleaned = re.sub(r'\s+', ' ', cleaned).strip().rstrip(' .')
       return cleaned
    
    raw_assignment_title = message_requests_df_condensed['assignment'].iloc[0]
    safe_assignment_title = _safe_filename_basic(raw_assignment_title)

    # Save the message requests to a CSV file
    csv_file_name = f"message_requests_{safe_assignment_title}.csv"
    print(f"Saving message requests to {csv_file_name}")

    # Save the dataframe to the message_requests/ folder
    message_requests_folder = 'message_requests/'
    if not os.path.exists(message_requests_folder):
        os.makedirs(message_requests_folder)
    message_requests_df_condensed.to_csv(os.path.join(message_requests_folder, csv_file_name), index=False)
    print(f"Message requests saved to {os.path.join(message_requests_folder, csv_file_name)}")