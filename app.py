import os
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import pytz # Import pytz for timezone handling
from collections import defaultdict # Import defaultdict for grouping records

# --- App Initialization and Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-me'
# Define the correct timezone
NIGERIA_TZ = pytz.timezone('Africa/Lagos')

# --- Google Sheets Connection ---
def get_sheets_client():
    """Establishes a connection with the Google Sheets API and returns a client object."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=scope)
    client = gspread.authorize(creds)
    return client


# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    error = None
    if request.method == 'POST':
        submitted_username = request.form['username']
        submitted_password = request.form['password']

        try:
            client = get_sheets_client()
            instructors_sheet = client.open("Attendance System DB").worksheet("Instructors")
            all_instructors = instructors_sheet.get_all_records()

            user_found = False
            for instructor in all_instructors:
                if instructor['Username'] == submitted_username and instructor['Password'] == submitted_password:
                    session['logged_in'] = True
                    session['full_name'] = instructor['FullName']
                    user_found = True
                    break

            if user_found:
                return redirect(url_for('dashboard'))
            else:
                error = 'Invalid credentials. Please try again.'

        except gspread.exceptions.WorksheetNotFound:
            error = "Error: 'Instructors' sheet not found. Please create it."
        except Exception as e:
            error = f"An error occurred: {e}"

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Logs the user out by clearing the session."""
    session.pop('logged_in', None)
    session.pop('full_name', None)
    return redirect(url_for('login'))


@app.route('/', methods=['GET', 'POST'])
def attendance_log():
    """Handles the main attendance check-in and check-out page."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")

    # Use timezone-aware datetime
    today_date_str = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'check_in':
            child_name = request.form['child_name']
            service_type = request.form['service_type']
            day_tag = request.form['day_tag']
            # Use timezone-aware datetime
            current_time = datetime.now(NIGERIA_TZ).strftime("%I:%M %p")

            new_row = [today_date_str, child_name, service_type, day_tag, current_time, "", "Checked-In"]
            log_sheet.append_row(new_row, value_input_option='USER_ENTERED')
            flash(f"{child_name} has been successfully checked in with tag #{day_tag}.", "success")

        elif action == 'checkout_by_tag':
            checkout_tag = request.form['checkout_tag']
            # Use timezone-aware datetime
            current_time = datetime.now(NIGERIA_TZ).strftime("%I:%M %p")

            full_sheet_values = log_sheet.get_all_values()
            headers = full_sheet_values[0]
            updated_children = []

            try:
                tag_col_index = headers.index('Day Tag')
                date_col_index = headers.index('Date')
                status_col_index = headers.index('Status')
                checkout_col_index = headers.index("Check-out Time")
                child_name_col_index = headers.index('Child Name')

                for i, row in enumerate(full_sheet_values[1:]):
                    if (row[date_col_index] == today_date_str and
                        row[tag_col_index] == checkout_tag and
                        row[status_col_index] == 'Checked-In'):
                        
                        row_index_in_sheet = i + 2 # +1 for header, +1 for 0-based index
                        child_checked_out = row[child_name_col_index]

                        log_sheet.update_cell(row_index_in_sheet, checkout_col_index + 1, current_time)
                        log_sheet.update_cell(row_index_in_sheet, status_col_index + 1, "Checked-Out")
                        updated_children.append(child_checked_out)

            except ValueError as e:
                flash(f"Error: A required column is missing in the AttendanceLog sheet. Details: {e}", "error")
                return redirect(url_for('attendance_log'))

            if updated_children:
                flash(f"Checked out {', '.join(updated_children)} (Tag #{checkout_tag}).", "success")
            else:
                flash(f"No active check-ins found for tag #{checkout_tag} today.", "error")

        return redirect(url_for('attendance_log'))

    children_names = [record['Child Full Name'] for record in children_sheet.get_all_records()]
    log_values_with_header = log_sheet.get_all_values()
    log_headers = log_values_with_header[0]
    log_records = log_values_with_header[1:]

    attendance_today = []
    for i, row in enumerate(log_records):
        record = dict(zip(log_headers, row))
        if record.get('Date') == today_date_str:
            record['row_id'] = i + 2
            attendance_today.append(record)

    return render_template('attendance.html', 
                           children_names=children_names, 
                           attendance_today=attendance_today,
                           # Use timezone-aware datetime
                           today_date=datetime.now(NIGERIA_TZ).strftime("%B %d, %Y"))


@app.route('/dashboard')
def dashboard():
    """Displays the main dashboard with summary statistics."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")
    
    all_children = children_sheet.get_all_records()
    total_children = len(all_children)
    child_to_class_map = {child['Child Full Name']: child['Class Type'] for child in all_children}

    all_logs = log_sheet.get_all_records()
    # Use timezone-aware datetime
    today_date_str = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")
    attendance_today = [record for record in all_logs if record.get('Date') == today_date_str]
    checked_in_today = len(attendance_today)

    class_breakdown = {"Tenderfoots": 0, "Light Troopers": 0, "Tribe of Truth": 0}
    service_breakdown = {"1st Service": 0, "2nd Service": 0}

    for record in attendance_today:
        if record.get('Service') == "1st Service":
            service_breakdown["1st Service"] += 1
        elif record.get('Service') == "2nd Service":
            service_breakdown["2nd Service"] += 1

        child_name = record.get('Child Name')
        if child_name in child_to_class_map:
            child_class = child_to_class_map[child_name]
            if child_class in class_breakdown:
                class_breakdown[child_class] += 1

    return render_template('dashboard.html', 
                           instructor_name=session.get('full_name', 'Instructor'),
                           # Use timezone-aware datetime
                           today_date=datetime.now(NIGERIA_TZ).strftime("%B %d, %Y"),
                           total_children=total_children,
                           checked_in_today=checked_in_today,
                           class_breakdown=class_breakdown,
                           service_breakdown=service_breakdown)


@app.route('/children')
def children_list():
    """Displays a list of all children."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    all_children = children_sheet.get_all_records()
    
    return render_template('children.html', children_list=all_children)


@app.route('/child/<int:row_id>')
def child_details(row_id):
    """Displays details for a single child."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    # This is fragile; a better method would be to fetch by a unique ID
    child_record = children_sheet.get_all_records()[row_id - 2]

    return render_template('child_details.html', child=child_record)


@app.route('/reports')
def reports():
    """Handles the reports page with filtering capabilities."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")

    # Use timezone-aware datetime for the default date
    today_date_str = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")
    selected_date = request.args.get('date', default=today_date_str)
    selected_service = request.args.get('service', default='All')
    selected_class = request.args.get('class_type', default='All')
    selected_tag = request.args.get('day_tag', default='')

    all_children = children_sheet.get_all_records()
    child_to_class_map = {child['Child Full Name']: child['Class Type'] for child in all_children}

    all_logs = log_sheet.get_all_records()

    # --- Filtering Logic ---
    filtered_records = all_logs
    if selected_date:
        filtered_records = [rec for rec in filtered_records if rec.get('Date') == selected_date]
    if selected_service != 'All':
        filtered_records = [rec for rec in filtered_records if rec.get('Service') == selected_service]
    if selected_class != 'All':
        filtered_records = [rec for rec in filtered_records 
                            if child_to_class_map.get(rec.get('Child Name')) == selected_class]
    if selected_tag:
        # Ensure comparison is between strings
        filtered_records = [rec for rec in filtered_records if str(rec.get('Day Tag', '')) == selected_tag]

    # Add class_type to each record for easy access in the template
    for record in filtered_records:
        record['class_type'] = child_to_class_map.get(record.get('Child Name'), 'N/A')
        # Add a row_id for the delete function to work
        # This is inefficient, a better way is to find the row index during initial fetch
        try:
            # Find the row in the original data to get a correct row_id
            original_index = all_logs.index(record)
            record['row_id'] = original_index + 2 # +1 for header, +1 for 0-based index
        except ValueError:
            record['row_id'] = None # Should not happen if record is from all_logs

    # --- *** NEW: Grouping Logic *** ---
    # Group the filtered records by Date and Day Tag for the template
    grouped_records = defaultdict(list)
    for record in filtered_records:
        # Use a placeholder like 'N/A' if a Day Tag is missing or empty
        tag = record.get('Day Tag') or 'N/A'
        grouped_records[(record.get('Date'), tag)].append(record)
    
    # Convert defaultdict to a regular dict to pass to the template
    grouped_records = dict(sorted(grouped_records.items()))

    selected_filters = {
        'date': selected_date,
        'service': selected_service,
        'class_type': selected_class,
        'day_tag': selected_tag
    }

    return render_template('reports.html', 
                           grouped_records=grouped_records, # Pass the new grouped data
                           record_count=len(filtered_records),
                           selected_filters=selected_filters)


@app.route('/delete_log/<int:row_id>', methods=['POST'])
def delete_log(row_id):
    """Deletes a specific row from the AttendanceLog sheet."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        client = get_sheets_client()
        log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")
        log_sheet.delete_rows(row_id)
        flash(f"Record in row {row_id} deleted successfully.", "success")
    except Exception as e:
        flash(f"Error while deleting record: {e}", "error")

    # Redirect back to the previous page (likely the reports page)
    return redirect(request.referrer or url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
