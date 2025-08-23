import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime

# --- App Initialization and Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-me'

# --- Google Sheets Connection ---
def get_sheets_client():
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    return client


# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
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
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/', methods=['GET', 'POST'])
def attendance_log():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")

    today_date_str = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        action = request.form.get('action')

        all_logs = log_sheet.get_all_records()
        todays_log_records = [record for record in all_logs if record['Date'] == today_date_str]

        if action == 'check_in':
            child_name = request.form['child_name']
            service_type = request.form['service_type']
            day_tag = request.form['day_tag']
            current_time = datetime.now().strftime("%I:%M %p")

            # ✅ allow same tag for multiple children
            new_row = [today_date_str, child_name, service_type, day_tag, current_time, "", "Checked-In"]
            log_sheet.append_row(new_row, value_input_option='USER_ENTERED')
            flash(f"{child_name} has been successfully checked in with tag #{day_tag}.", "success")

        elif action == 'checkout_by_tag':
            checkout_tag = request.form['checkout_tag']
            current_time = datetime.now().strftime("%I:%M %p")

            full_sheet_values = log_sheet.get_all_values()
            headers = full_sheet_values[0]
            try:
                tag_col_index = headers.index('Day Tag')
                date_col_index = headers.index('Date')
                status_col_index = headers.index('Status')

                for i, row in enumerate(full_sheet_values[1:]):
                    if (row[date_col_index] == today_date_str and
                        row[tag_col_index] == checkout_tag and
                        row[status_col_index] == 'Checked-In'):

                        target_row_index = i + 2
                        child_checked_out = row[headers.index('Child Name')]

                        checkout_col = headers.index("Check-out Time") + 1
                        status_col = headers.index("Status") + 1
                        log_sheet.update_cell(target_row_index, checkout_col, current_time)
                        log_sheet.update_cell(target_row_index, status_col, "Checked-Out")

                        flash(f"{child_checked_out} (Tag #{checkout_tag}) has been successfully checked out.", "success")
                        break
                else:
                    flash(f"Error: Could not find an active check-in for tag number '{checkout_tag}'.", "error")

            except ValueError:
                flash("Error: A required column is missing from AttendanceLog.", "error")
                return redirect(url_for('attendance_log'))

        return redirect(url_for('attendance_log'))

    children_names = [record['Child Full Name'] for record in children_sheet.get_all_records()]
    log_values_with_header = log_sheet.get_all_values()
    log_headers = log_values_with_header[0]
    log_records = log_values_with_header[1:]

    attendance_today = []
    for i, row in enumerate(log_records):
        record = dict(zip(log_headers, row))
        if record['Date'] == today_date_str:
            record['row_id'] = i + 2
            attendance_today.append(record)

    return render_template('attendance.html',
                           children_names=children_names,
                           attendance_today=attendance_today,
                           today_date=datetime.now().strftime("%B %d, %Y"))


@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")

    all_children = children_sheet.get_all_records()
    total_children = len(all_children)

    child_to_class_map = {child['Child Full Name']: child['Class Type'] for child in all_children}

    all_logs = log_sheet.get_all_records()
    today_date_str = datetime.now().strftime("%Y-%m-%d")
    attendance_today = [record for record in all_logs if record['Date'] == today_date_str]
    checked_in_today = len(attendance_today)

    class_breakdown = {"Tenderfoots": 0, "Light Troopers": 0, "Tribe of Truth": 0}
    service_breakdown = {"1st Service": 0, "2nd Service": 0}

    for record in attendance_today:
        if record['Service'] in service_breakdown:
            service_breakdown[record['Service']] += 1

        child_name = record['Child Name']
        if child_name in child_to_class_map:
            child_class = child_to_class_map[child_name]
            if child_class in class_breakdown:
                class_breakdown[child_class] += 1

    return render_template('dashboard.html',
                           instructor_name=session.get('full_name', 'Instructor'),
                           today_date=datetime.now().strftime("%B %d, %Y"),
                           total_children=total_children,
                           checked_in_today=checked_in_today,
                           class_breakdown=class_breakdown,
                           service_breakdown=service_breakdown)


@app.route('/children')
def children_list():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    all_children = children_sheet.get_all_records()

    return render_template('children.html', children_list=all_children)


@app.route('/child/<int:row_id>')
def child_details(row_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    child_record = children_sheet.get_all_records()[row_id - 2]

    return render_template('child_details.html', child=child_record)


@app.route('/reports')
def reports():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    client = get_sheets_client()
    children_sheet = client.open("Attendance System DB").worksheet("Sheet1")
    log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")

    today_date_str = datetime.now().strftime("%Y-%m-%d")
    selected_date = request.args.get('date', default=today_date_str)
    selected_service = request.args.get('service', default='All')
    selected_class = request.args.get('class_type', default='All')
    selected_tag = request.args.get('day_tag', default='')

    all_children = children_sheet.get_all_records()
    child_to_class_map = {child['Child Full Name']: child['Class Type'] for child in all_children}

    log_values_with_header = log_sheet.get_all_values()
    log_headers = log_values_with_header[0]
    all_log_records_raw = log_values_with_header[1:]

    all_logs = []
    for i, row in enumerate(all_log_records_raw):
        record = dict(zip(log_headers, row))
        record['row_id'] = i + 2
        all_logs.append(record)

    filtered_records = all_logs
    if selected_date:
        filtered_records = [rec for rec in filtered_records if rec['Date'] == selected_date]

    if selected_service != 'All':
        filtered_records = [rec for rec in filtered_records if rec['Service'] == selected_service]

    if selected_class != 'All':
        filtered_records = [rec for rec in filtered_records
                            if rec['Child Name'] in child_to_class_map and
                               child_to_class_map[rec['Child Name']] == selected_class]

    if selected_tag:
        filtered_records = [rec for rec in filtered_records if str(rec.get('Day Tag')) == selected_tag]

    for record in filtered_records:
        record['class_type'] = child_to_class_map.get(record['Child Name'], 'N/A')

    # ✅ Group by (date, tag)
    grouped_records = {}
    for rec in filtered_records:
        group_key = (rec['Date'], rec.get('Day Tag', ''))
        if group_key not in grouped_records:
            grouped_records[group_key] = []
        grouped_records[group_key].append(rec)

    selected_filters = {
        'date': selected_date,
        'service': selected_service,
        'class_type': selected_class,
        'day_tag': selected_tag
    }

    return render_template('reports.html',
                           grouped_records=grouped_records,
                           record_count=len(filtered_records),
                           selected_filters=selected_filters)


@app.route('/delete_log/<int:row_id>', methods=['POST'])
def delete_log(row_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    try:
        client = get_sheets_client()
        log_sheet = client.open("Attendance System DB").worksheet("AttendanceLog")
        log_sheet.delete_rows(row_id)
        flash(f"Record in row {row_id} has been successfully deleted.", "success")
    except Exception as e:
        flash(f"An error occurred while trying to delete the record: {e}", "error")

    return redirect(request.referrer or url_for('dashboard'))