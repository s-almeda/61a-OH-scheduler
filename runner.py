import config_read
import calendar_time
import utils
import State
import os, sys
import numpy as np
from datetime import datetime
from datetime import timedelta
import csv
# #from google.cloud import storage
from google.api_core.exceptions import Forbidden, NotFound
import validation
import algorithm
import pandas as pd


# The range of both spreadsheet. This should not change unless the forms/the demand spreadsheet has been edited.


os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"



def main():
    print("\n\033[1m[---- Welcome to the Office Hours Scheduler! ---- ]\033[0m\n")

    # Ask the user to select the class
    print("Please select the class you're scheduling for:")
    print("[1] CS61A")
    print("[2] DATAC88C")

    choice = input("Enter your choice (1 or 2): ").strip()

    # Determine the correct config file based on the user's choice
    if choice == '1':
        config_file = "61a_config.json"
    elif choice == '2':
        config_file = "88c_config.json"
    else:
        print("Invalid choice. Please restart and choose 1 for 61A or 2 for 88C.")
        return
    
    # Read the config file
    config = config_read.read_config(config_file)

    # Which functionality?
    print("\033[1m [ Do you want to run the OH scheduler (generate CSV file) or send calendar events?: ]\033[0m")
    print("[1] Run the OH scheduler (generate CSV file)")
    print("[2] Send calendar events (CSV file to calendar event invites)")
    choice = input("Enter your choice (1 or 2): ").strip()
    # Determine the correct config file based on the user's choice
    if choice == '2':
        week_num = int(input("Enter the week number you'd like to send emails for. \n(e.g., enter 5 for week 5 of the semester): ").strip())
        calendar_events_from_csv(config, week_num)
        sys.exit(0)
    elif choice!= '1':
        print("Invalid choice. Please restart")
        return



    # -- Continue with OH scheduling! -- #

    # Print links and ranges for user approval
    print("\033[1m[ ---- Current Settings: ---- ]\033[0m\n")
    print(f"Availabilities Sheet Link: \n{config['availabilities_link']}\n")
    print(f"Demand Sheet Link: \n{config['demand_link']}")
    print("\nRelevant Sheet Ranges:")
    print(f"- AVAILABILITIES_RANGE = '{config['AVAILABILITIES_RANGE']}")
    print(f"- DEMAND_RANGE = '{config['DEMAND_RANGE']}'")

    # Ask for user approval
    approval = input("\n\033[1mDoes everything look correct? (y/n): \033[0m").strip().lower()
    if approval != 'y':
        print("Please edit config.json, then re-run the program.")
        sys.exit(1)

    AVAILABILITIES_RANGE = config["AVAILABILITIES_RANGE"]
    DEMAND_RANGE = config["DEMAND_RANGE"]

    # Step 3: Fetch and validate availabilities data
    availabilities_id = config_read.get_google_sheets_id(config["availabilities_link"])
    availabilities = utils.get_availabilities(availabilities_id, AVAILABILITIES_RANGE)
    validation.validate_availabilities(availabilities)

    # Step 4: Fetch and validate demand data
    demand_id = config_read.get_google_sheets_id(config["demand_link"])
    demand = utils.get_demand(demand_id, DEMAND_RANGE, config["weeks"])

    # Step 5: Validate the entire config
    validation.validate_config(config)

    run_scheduler(config, demand, availabilities)

def run_scheduler(config, demand, availabilities):

    # Step 5: Prompt user to enter the current week
    while True:
        try:
            week_num = int(input("Enter the week number you'd like to run the algo on.\n(e.g., enter 5 to schedule for week 5 of the semester): ").strip())
            if week_num <= 0:
                raise ValueError
            latest_week = week_num - 1
            break
        except ValueError:
            print("Invalid input, please enter a positive integer for the week number.")



    if (latest_week- config["weeks_skipped"]) > 0:
         print("looking for state for previous week: ", latest_week)
         last_state = utils.deserialize(latest_week, config["weeks_skipped"])
    else:
        last_state = None
    
    if last_state and last_state.week_num == config["weeks"]:
        print(f"ERROR: The algorithm has already been run for all weeks. The last state was for week {config['weeks']}. Exiting.")
        return
    if latest_week == config['weeks']:
        raise RuntimeError("Allotted # of weeks have already passed. Exiting.")

    # Create new state object
    state = State.State(last_state, 
                        demand, 
                        availabilities, 
                        config["class"], 
                        config["semester"], 
                        config["weeks"], 
                        config["weekly_hour_multiplier"], 
                        config["weeks_skipped"])
    
    # Run algorithm
    inputs = state.get_algo_inputs()
    assignments = algorithm.run_algorithm(inputs)
    # \assignments = np.load("assignments.npy")[:, 0, :, :]

    np.save('demand.npy', demand)

    state.set_assignments(assignments)

    # Create CSV export of the next week's assignments
    export_dict = {"email": [], "sum_assignments": []}
    for i in range(assignments.shape[0]):
        if assignments[i].sum() != 0:

            export_dict['email'].append(state.bi_mappings.inverse[i])
            export_dict['sum_assignments'].append(assignments[i].sum())

    export_df = pd.DataFrame(data=export_dict)
    export_df.to_csv(f"outputs/{config['class']}sum_assignments_week{week_num}.csv", index=False)
    

    # Create a dictionary to store the data for the detailed CSV
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    hours_of_day = [f"{hour}:00" for hour in range(9, 21)]  # 9 AM to 9 PM
    export_dict_weekly = {day: [""] * 12 for day in days_of_week}  # Initialize dictionary for each day

    # Iterate over the days of the week
    for day_index in range(assignments.shape[1]):
        # Iterate over the hours of the day
        for hour_index in range(assignments.shape[2]):
            assigned_staff = []
            # Iterate over each staff member to find those assigned to this time slot
            for staff_index in range(assignments.shape[0]):
                if assignments[staff_index, day_index, hour_index] == 1:  # If the staff member is assigned
                    staff_email = state.bi_mappings.inverse[staff_index]  # Get staff email from mapping
                    assigned_staff.append(staff_email)  # Add email to the list for this time slot

            # Join the emails into a single string, separated by commas
            export_dict_weekly[days_of_week[day_index]][hour_index] = ", ".join(assigned_staff)

    # Create a DataFrame from the dictionary and export it as a CSV
    export_df_weekly = pd.DataFrame(data=export_dict_weekly, index=hours_of_day)
    export_df_weekly.to_csv(f"outputs/weekly_assignments/{config['class']}assignments_week{week_num}.csv", index=True, index_label="Hour")

    state.serialize() #save the current state as a pickle
    print("\n\033[1m[ ---- Done! ---- ]\033[0m\n") 
    print(f"Saved as 'outputs/weekly_assignments/{config['class']}assignments_week{week_num}.csv'")


    # Ask for user approval to go to schedule calendar events
    approval = input("\n\033[1mDo you want to send Google Calendar events? (y/n): \033[0m").strip().lower()
    if approval == 'y':
        calendar_events_from_csv(config, week_num)
    # Ask for user approval to run scheduler again
    approval = input("\n\033[1mDo you want to schedule another week? (y/n): \033[0m").strip().lower()
    if approval == 'y':
        run_scheduler(config, demand, availabilities)
    else:
        "ok byeee!!"
        sys.exit(0)


def calendar_events_from_csv(config, week_num):
    """
    Creates Google Calendar events based on assignments from a CSV file.

    Parameters:
    ----------
    config : dict 
        the output of running config_read.read_config("config_file.json") ie 61A_config.json)
    
    week_num : int
        Week of the semester for which the events are scheduled.

    Process:
    --------
    - Loads assignments from the CSV file for the given week.
    - Verifies with the user that the details are correct (dates, number of TAs, etc.).
    - Fetches the calendar name to confirm the correct calendar.
    - Creates calendar events for each assignment

    Notes:
    ------
    - Ensure the CSV is correctly formatted (one row per hour, TA emails in columns for each day).
    - OAuth authentication must be handled by `calendar_time.authenticate()` in the calendar_time.py file
    - Google Calendar is picky about datetime format, so watch out for that.
    """

    # Construct the CSV file path based on the selected class and week number
    csv_name = f"outputs/weekly_assignments/{config['class']}assignments_week{week_num}.csv"
    
    # Check if the CSV file exists
    if not os.path.exists(csv_name):
        print(f"ERROR: CSV file {csv_name} not found. Please generate the CSV file and try again.")
        sys.exit(1)
    


    assignments = parse_assignments_from_csv(csv_name, config, week_num)
    num_assignments = len(assignments)

    # ---- Check 1: Double-check with the user that this all looks correct ... ---#
    # Get the start and end dates of all assignments so we can check we're doing this for the correct week
    start_date = min((datetime.strptime(a['start_time'], '%Y-%m-%dT%H:%M') for a in assignments if a['attendees']), default=None)
    end_date =  max((datetime.strptime(a['end_time'], '%Y-%m-%dT%H:%M') for a in assignments if a['attendees']), default=None)
    
    # Get unique TA emails and a list of TAs 
    all_tas = set()
    for assignment in assignments:
        all_tas.update(assignment['attendees'])
    
    tas_list = list(all_tas)
    num_tas = len(tas_list)
    tas_sample = ", ".join(tas_list[:5]) if num_tas > 0 else "No TAs found"

    
    # Print the summary to the user
    print(f"\nFound \033[1m{num_assignments} assignments\033[0m in CSV file: \033[1m{csv_name}\033[0m\n")
    print(f"\033[1mSpanning dates:\033[0m\n{start_date.strftime('%A, %B %d, %Y')} - {end_date.strftime('%A, %B %d, %Y')}\n")
    print(f"\033[1mFor {num_tas} different TAs, including:\033[0m\n{tas_sample}")

    # Ask the user if they want to proceed
    approval = input("Enter 'y' to continue or 'n' to quit: ").strip().lower()
    if approval != 'y':
        print("Good-bye!")
        sys.exit(1)

    # --- Check 2: one more check that the config settings are correct --#

    print("\n\033[1mEvent Details:\033[0m")
    print(f"Events will be named: {config['calendar_event_name']}")
    print(f"Location: {config['calendar_event_location']}")
    print(f"Description: {config['calendar_event_description']}")
    print(f"Calendar ID: {config['calendar_id']}")

    # Fetch the calendar name from the Google Calendar API
    service = calendar_time.authenticate()  # Assuming authenticate() is already defined
    try:
        calendar = service.calendars().get(calendarId=config['calendar_id']).execute()
        calendar_name = calendar['summary']
        print(f"Calendar Name: {calendar_name}")
    except HttpError as error:
        print(f"An error occurred while fetching calendar information: {error}")
        sys.exit(1)

    final_approval = input(f"\n\033[1mProceed with creating {num_assignments} events on this calendar? (y/n): \033[0m").strip().lower()
    if final_approval != 'y':
        print("Please edit config.json if the above values need to be corrected, then re-run the program. \n(You can find the appropriate calendar ID under 'Settings and Sharing > Integrate Calendar' on Google Calendar)")
        sys.exit(1)

    # --- Event Creation Section --- #
    service = calendar_time.authenticate()  # Assuming authenticate() is already defined
    print("Proceeding with calendar event creation...")

    errors_occurred = False

    # Iterate through each assignment and create a calendar event
    for assignment in assignments:
        # Get the start time, end time, and attendees for the current assignment
        start_time = assignment['start_time']
        end_time = assignment['end_time']
        attendees = [email for email in assignment['attendees'] if email.strip()]  # Ensure non-empty emails

        # Ensure there are attendees before creating the event
        if not attendees:
            print(f"Skipping event for {start_time} - {end_time}: No valid attendees.")
            errors_occurred = True
            continue

        # Convert start and end times to the required format: YYYY-MM-DDTHH:MM:SS.MMMZ
        start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%dT%H:%M:00-07:00")
        end_time = datetime.strptime(end_time, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%dT%H:%M:00-07:00")
        
        # Set up event details
        summary = config['calendar_event_name']
        location = config['calendar_event_location']
        description = config['calendar_event_description']
        
        # Define the reminders for the event
        reminders = {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},
                {'method': 'popup', 'minutes': 10},
            ],
        }
        
        # Call the create_event function from calendar_time.py
        try:
            calendar_time.create_event(
                service=service,
                calendar_id=config['calendar_id'],
                summary=summary,
                location=location,
                description=description,
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,  # Passing list of email strings directly
                reminders=reminders
            )
            print(f"Event created for {start_time} to {end_time} with attendees: {', '.join(attendees)}\n...\n")
        except HttpError as error:
            print(f"An error occurred while creating the event for {start_time} - {end_time}: {error}")
            errors_occurred = True

    # Print success message only if no errors occurred
    if not errors_occurred:
        print("\nAll events created successfully!")
    else:
        print("Some events could not be created due to errors.")




def parse_assignments_from_csv(csv_name, config, week_num):
    """
    Parses TA assignments from a CSV file and returns a list of assignments.

    Parameters:
    ----------
    csv_name : str
        Path to the CSV file containing TA assignments.
    config : dict
        Configuration containing the start date of the semester.
    week_num : int
        The week number for which assignments are being parsed.

    Returns:
    --------
    list of dict
        A list where each dictionary represents an assignment with the following keys:
        - 'start_time' : str (formatted as '%Y-%m-%dT%H:%M') (note that there's no %S for seconds)
        - 'end_time' : str (formatted as '%Y-%m-%dT%H:%M')
        - 'attendees' : list of str (TA email addresses)

    Process:
    --------
    - Calculates the date for each day of the specified week.
    - Reads the CSV and extracts attendees for each hour and day.
    - Creates a list of assignments with start/end times and attendee emails.
    """

    assignments = []
    
    # Parse the start date of the semester and calculate the start date for the given week
    start_date = datetime.strptime(config["start_date"], "%Y-%m-%d")

    monday_of_week = start_date + timedelta(weeks=week_num - 1-int(config["weeks_skipped"]))

    
    # Map column headers (days of the week) to their corresponding date for this week
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    day_to_date = {day: monday_of_week + timedelta(days=i) for i, day in enumerate(days_of_week)}
    
    # Open and read the CSV file
    with open(csv_name, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        
        # Iterate over each row (hourly time slots)
        for row in reader:
            hour = row["Hour"]  # Extract the hour from the "Hour" column

            # Iterate over the days of the week
            for day in days_of_week:
                attendees_str = row[day]  # Get the list of attendees (if any) for this day and hour
                if attendees_str:  # If there are attendees listed for this time slot
                    attendees = [email.strip() for email in attendees_str.split(",")]

                    # Calculate the start and end times for the assignment
                    start_time_str = f"{day_to_date[day].strftime('%Y-%m-%d')}T{hour}:00"
                    start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")
                    end_time = start_time + timedelta(hours=1)  # Assuming each slot is 1 hour long

                    # Create an assignment dictionary and append to the list
                    assignment = {
                        "start_time": start_time.strftime('%Y-%m-%dT%H:%M'),
                        "end_time": end_time.strftime('%Y-%m-%dT%H:%M'),
                        "attendees": attendees
                    }
                    assignments.append(assignment)
    
    return assignments



if __name__ == '__main__':
    main()
