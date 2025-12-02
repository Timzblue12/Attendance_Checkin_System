import csv
import io
import math
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import json
import os
import sys
import types
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, abort
from datetime import datetime
import pytz
from collections import defaultdict
from werkzeug.exceptions import BadRequestKeyError

# ---------------------------------------------------------------------------
# Compatibility shim for Flask 3.x environments where flask.debughelpers
# was removed but Werkzeug still attempts to import it.
# ---------------------------------------------------------------------------
try:
    import flask.debughelpers  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - only hit on newer Flask
    debughelpers = types.ModuleType("flask.debughelpers")

    class DebugFilesKeyError(BadRequestKeyError):
        """Minimal stand-in that mirrors the old helper."""

        def __init__(self, request, key):
            super().__init__(key)
            self.request = request
            self.key = key

        def get_description(self, environ=None):
            base = super().get_description(environ)
            hint = (
                "Ensure your form uses enctype=\"multipart/form-data\" and that the "
                f"file input name matches '{self.key}'."
            )
            return f"{base} {hint}"

    debughelpers.DebugFilesKeyError = DebugFilesKeyError
    sys.modules["flask.debughelpers"] = debughelpers

import sync_queue

# Check if running in local development mode
USE_LOCAL_DB = os.getenv('LOCAL_DEV', 'false').lower() == 'true'

# Import local database helpers if in dev mode
if USE_LOCAL_DB:
    import db_helper
    from database import init_database
    print("=" * 60)
    print("🔧 RUNNING IN LOCAL DEVELOPMENT MODE (SQLite)")
    print("=" * 60)
    # Ensure database is initialized
    if not os.path.exists(os.path.join(os.path.dirname(__file__), 'attendance_local.db')):
        print("Initializing local database...")
        init_database()
else:
    print("=" * 60)
    print("☁️  RUNNING IN PRODUCTION MODE (Google Sheets)")
    print("=" * 60)

# Ensure local SQLite store (used for offline queue) exists in all environments
sync_queue.ensure_database_ready()

# --- App Initialization and Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-me'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.jinja_env.cache = {}
NIGERIA_TZ = pytz.timezone('Africa/Lagos')

SPREADSHEET_NAME = "RBC25 Database_Child Care Registration"
INSTRUCTORS_SHEET = "Instructors"
CHILDREN_SHEET = "Form responses 1"
ATTENDANCE_SHEET = "AttendanceLog"

CHILDREN_PER_PAGE = 20
ATTENDANCE_PER_PAGE = 20
REPORTS_PER_PAGE = 20

ATTENDANCE_HEADERS = [
    "Date",
    "Child Name",
    "Event Name",
    "Event ID",
    "Session Label",
    "Session Period",
    "Session ID",
    "State",
    "Church Location",
    "Camp Group",
    "Service",
    "Day Tag",
    "Check-in Time",
    "Check-out Time",
    "Status",
    "Notes"
]

HEADER_TO_RECORD_KEY = {
    "Date": "date",
    "Child Name": "child_name",
    "Event Name": "event_name",
    "Event ID": "event_id",
    "Session Label": "session_label",
    "Session Period": "session_period",
    "Session ID": "session_id",
    "State": "state",
    "Church Location": "church_location",
    "Camp Group": "camp_group",
    "Service": "service",
    "Day Tag": "day_tag",
    "Check-in Time": "check_in_time",
    "Check-out Time": "check_out_time",
    "Status": "status",
    "Notes": "notes"
}

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "rebootcamp_config.json")


def load_rebootcamp_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
            data.setdefault("events", [])
            return data
    except FileNotFoundError:
        print("⚠️  RebootCamp config not found. Continuing without camp metadata.")
        return {"events": [], "default_event_id": None}


REBOOT_CONFIG = load_rebootcamp_config()

DEFAULT_EVENT_ID = "church-service"
DEFAULT_EVENT_OPTION = {
    "id": DEFAULT_EVENT_ID,
    "name": "Church Service",
    "sessions": [],
    "states": [],
    "church_locations": [],
    "camp_groups": [],
}

DEFAULT_CHURCH_LOCATIONS = [
    "Visitor",
    "CCI Ikeja, Lagos",
    "CCI Utako, Abuja",
    "CCI Port Harcourt",
    "CCI Toronto, ON",
    "CCI Lagos Island, Lagos",
    "CCI Ibadan",
    "CCI West London, UK",
    "CCI Ile-Ife",
    "CCI Yaba, Lagos",
    "CCI Ago, Lagos",
    "CCI Birmingham West",
    "CCI Uyo",
    "CCI Mararaba, Abuja",
    "CCI Lokogoma, Abuja",
    "CCI Dallas",
    "CCI Ajah, Lagos",
    "CCI Abeokuta, Ogun",
    "CCI Manchester, UK",
    "CCI Glasgow, UK",
    "CCI Ottawa, ON",
    "CCI Akure, Ondo",
    "CCI Ilorin",
    "CCI Benin",
    "CCI DMV",
    "CCI South East London, UK",
    "CCI Dublin",
    "CCI Egbeda, Lagos",
    "CCI Ikorodu, Lagos",
    "CCI Winnipeg, MB",
    "CCI East London, UK",
    "CCI Enugu",
    "CCI Hamilton, ON",
    "CCI Oshawa, ON",
    "CCI Barrie, ON",
    "CCI Birmingham Central, UK",
    "CCI Warri",
    "CCI Osogbo",
    "CCI Mgbuoba",
    "CCI Kaduna",
    "CCI Calgary, AB",
    "CCI Boston",
    "CCI Bolton, UK",
    "CCI Austin",
]


def get_event_options():
    options = [DEFAULT_EVENT_OPTION.copy()]
    options.extend(REBOOT_CONFIG.get("events", []))
    return options


def get_event(event_id=None):
    """Return event dict by id, falling back to default."""
    options = get_event_options()
    candidate_ids = [event_id, REBOOT_CONFIG.get("default_event_id"), DEFAULT_EVENT_ID]
    for candidate in candidate_ids:
        if not candidate:
            continue
        for event in options:
            if event.get("id") == candidate:
                return event

    return options[0] if options else None


def get_event_dates(event_id=None):
    event = get_event(event_id)
    if not event:
        return []
    dates = sorted({session.get("date") for session in event.get("sessions", [])})
    return [date for date in dates if date]


def get_sessions_for_date(event_id, session_date):
    event = get_event(event_id)
    if not event:
        return []
    return [session for session in event.get("sessions", []) if session.get("date") == session_date]


def find_session(event_id, session_id):
    if not session_id:
        return None
    event = get_event(event_id)
    if not event:
        return None
    for session in event.get("sessions", []):
        if session.get("id") == session_id:
            return session
    return None


def apply_report_filters(event_id, selected_date, selected_service, selected_session_id,
                         selected_class, selected_state, selected_location, selected_tag):
    """Return filtered attendance records and supporting metadata for reports/export."""
    def _normalize_service(value):
        if value is None:
            return ''
        text = str(value).strip().lower()
        # Strip leading day labels like "day 1" to keep only the period portion
        text = text.replace('day 1', '').replace('day 2', '').replace('day 3', '').replace('day 4', '').replace('day 5', '')
        if text.endswith('session'):
            text = text[:-7].strip()
        return text.strip()

    def _matches_service(record, target):
        if target == 'All':
            return True
        normalized_target = _normalize_service(target)
        candidates = [
            record.get('Service'),
            record.get('Session Period'),
            record.get('Session Label'),
        ]
        for candidate in candidates:
            normalized_candidate = _normalize_service(candidate)
            if normalized_candidate == normalized_target:
                return True
            # Handle cases like "Day 1 Morning Session" vs "Morning"
            if normalized_target and normalized_target in normalized_candidate:
                return True
        return False

    child_to_class_map = get_child_class_map()
    children_records = get_all_children()
    all_logs = get_all_attendance_logs()

    filtered_records = all_logs
    if event_id:
        filtered_records = [rec for rec in filtered_records if rec.get('Event ID') in (event_id, '', None)]
    if selected_date:
        filtered_records = [rec for rec in filtered_records if rec.get('Date') == selected_date]
    if selected_service != 'All':
        filtered_records = [rec for rec in filtered_records if _matches_service(rec, selected_service)]
    if selected_session_id != 'All':
        filtered_records = [rec for rec in filtered_records if rec.get('Session ID') == selected_session_id]
    if selected_class != 'All':
        filtered_records = [rec for rec in filtered_records
                            if child_to_class_map.get(rec.get('Child Name')) == selected_class]
    if selected_state != 'All':
        filtered_records = [rec for rec in filtered_records if rec.get('State') == selected_state]
    if selected_location != 'All':
        filtered_records = [rec for rec in filtered_records if rec.get('Church Location') == selected_location]
    if selected_tag:
        filtered_records = [rec for rec in filtered_records if str(rec.get('Day Tag', '')) == selected_tag]

    for record in filtered_records:
        record['class_type'] = child_to_class_map.get(record.get('Child Name'), 'N/A')
        if 'row_id' not in record and 'id' in record:
            record['row_id'] = record['id']
        elif 'row_id' not in record:
            try:
                original_index = all_logs.index(record)
                record['row_id'] = original_index + 2
            except ValueError:
                record['row_id'] = None

    return {
        'filtered_records': filtered_records,
        'child_to_class_map': child_to_class_map,
        'children_records': children_records,
        'all_logs': all_logs,
    }

# --- Google Sheets Connection (Production Only) ---
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


def get_workbook(client=None):
    client = client or get_sheets_client()
    return client.open(SPREADSHEET_NAME)


def get_attendance_sheet(client=None):
    workbook = get_workbook(client)
    return workbook.worksheet(ATTENDANCE_SHEET)


def ensure_attendance_headers(log_sheet):
    """Ensure the Google Sheet has all expected columns."""
    header = log_sheet.row_values(1)
    if not header:
        log_sheet.insert_row(ATTENDANCE_HEADERS, 1)
        return ATTENDANCE_HEADERS

    normalized = [col.strip() for col in header]
    updated_header = list(header)
    changed = False

    for expected in ATTENDANCE_HEADERS:
        if expected not in normalized:
            updated_header.append(expected)
            normalized.append(expected)
            changed = True

    if changed:
        log_sheet.update('1:1', [updated_header])
        return updated_header

    return header


def append_attendance_row(log_sheet, record):
    """Append a new check-in row to the Google Sheet."""
    header = ensure_attendance_headers(log_sheet)
    row_data = []

    for column in header:
        key = HEADER_TO_RECORD_KEY.get(column)
        value = record.get(key, "") if key else ""
        row_data.append(value)

    log_sheet.append_row(row_data, value_input_option='USER_ENTERED')


def perform_remote_checkout(log_sheet, date, day_tag, checkout_time):
    """Update Google Sheet rows for a checkout event."""
    ensure_attendance_headers(log_sheet)
    full_sheet_values = log_sheet.get_all_values()
    if not full_sheet_values:
        return []

    headers = full_sheet_values[0]
    try:
        tag_col_index = headers.index('Day Tag')
        date_col_index = headers.index('Date')
        status_col_index = headers.index('Status')
        checkout_col_index = headers.index('Check-out Time')
        child_name_col_index = headers.index('Child Name')
    except ValueError as exc:
        raise ValueError(f"Missing required column: {exc}")

    updated_children = []
    for i, row in enumerate(full_sheet_values[1:]):
        if (row[date_col_index] == date and
                row[tag_col_index] == str(day_tag) and
                row[status_col_index] == 'Checked-In'):
            row_index_in_sheet = i + 2  # account for header row
            child_checked_out = row[child_name_col_index]
            log_sheet.update_cell(row_index_in_sheet, checkout_col_index + 1, checkout_time)
            log_sheet.update_cell(row_index_in_sheet, status_col_index + 1, "Checked-Out")
            updated_children.append(child_checked_out)

    return updated_children


def get_checked_in_children(date, day_tag):
    """Return list of currently checked-in children for the tag/date."""
    if USE_LOCAL_DB:
        return db_helper.get_checked_in_by_tag(date, day_tag)

    try:
        log_sheet = get_attendance_sheet()
    except Exception:
        return []

    ensure_attendance_headers(log_sheet)
    values = log_sheet.get_all_values()
    if not values:
        return []

    headers = values[0]
    try:
        tag_col_index = headers.index('Day Tag')
        date_col_index = headers.index('Date')
        status_col_index = headers.index('Status')
        child_name_col_index = headers.index('Child Name')
    except ValueError:
        return []

    children = []
    for row in values[1:]:
        if (row[date_col_index] == date and
                row[tag_col_index] == str(day_tag) and
                row[status_col_index] == 'Checked-In'):
            children.append(row[child_name_col_index])

    return children


def process_pending_queue(client=None, limit=20):
    """Try to flush pending offline entries to Google Sheets."""
    if USE_LOCAL_DB:
        return {"processed": 0, "failed": 0}

    try:
        client = client or get_sheets_client()
        log_sheet = get_attendance_sheet(client)
    except Exception as exc:
        return {"processed": 0, "failed": 0, "error": str(exc)}

    queue_items = sync_queue.fetch_pending_queue(limit=limit)
    processed = failed = 0

    for item in queue_items:
        payload = json.loads(item['payload'])
        sync_queue.record_sync_attempt(item['id'])

        try:
            if item['operation'] == 'check_in':
                record = {
                    "date": payload.get('date'),
                    "child_name": payload.get('child_name'),
                    "event_name": payload.get('event_name'),
                    "event_id": payload.get('event_id'),
                    "session_label": payload.get('session_label') or payload.get('service'),
                    "session_period": payload.get('session_period'),
                    "session_id": payload.get('session_id'),
                    "state": payload.get('state'),
                    "church_location": payload.get('church_location'),
                    "camp_group": payload.get('camp_group'),
                    "service": payload.get('service'),
                    "day_tag": payload.get('day_tag'),
                    "check_in_time": payload.get('check_in_time'),
                    "check_out_time": payload.get('check_out_time', ""),
                    "status": payload.get('status', 'Checked-In'),
                    "notes": payload.get('notes')
                }
                append_attendance_row(log_sheet, record)
                sync_queue.mark_attendance_synced(payload['attendance_id'])
            elif item['operation'] == 'checkout':
                perform_remote_checkout(
                    log_sheet,
                    payload['date'],
                    payload['day_tag'],
                    payload['checkout_time']
                )
                for attendance_id in payload.get('attendance_ids', []):
                    sync_queue.mark_attendance_synced(attendance_id)
            else:
                raise ValueError(f"Unsupported operation type: {item['operation']}")

            sync_queue.mark_queue_item_synced(item['id'])
            processed += 1
        except Exception as exc:
            sync_queue.update_queue_error(item['id'], str(exc))
            failed += 1

    return {"processed": processed, "failed": failed}

# --- Data Access Layer (switches between Local DB and Google Sheets) ---

def get_all_instructors():
    """Get all instructors."""
    if USE_LOCAL_DB:
        return db_helper.get_all_instructors()
    else:
        workbook = get_workbook()
        instructors_sheet = workbook.worksheet(INSTRUCTORS_SHEET)
        records = instructors_sheet.get_all_records()
        for record in records:
            record.setdefault('PhoneNumber', '')
            record.setdefault('ChurchBranch', record.get('Church Branch', ''))
            record.setdefault('FullName', record.get('Full Name') or record.get('FullName'))
        return records

def get_all_children():
    """Get all children."""
    if USE_LOCAL_DB:
        return db_helper.get_all_children()
    else:
        workbook = get_workbook()
        children_sheet = workbook.worksheet(CHILDREN_SHEET)
        records = children_sheet.get_all_records()
        for idx, record in enumerate(records, start=2):
            record.setdefault('State', '')
            record.setdefault('Church Location', '')
            record.setdefault('Camp Group', '')
            record.setdefault('Guardian Phone', record.get('Guardian Phone', ''))
            record.setdefault('Notes', record.get('Notes', ''))
            record['row_id'] = idx
        return records

def get_children_names():
    """Get list of children names."""
    if USE_LOCAL_DB:
        return db_helper.get_children_names()
    else:
        children = get_all_children()
        return [child['Child Full Name'] for child in children]


def get_child_details(child_name):
    for child in get_all_children():
        if child.get('Child Full Name') == child_name:
            return child
    return {}

def get_all_attendance_logs():
    """Get all attendance logs."""
    if USE_LOCAL_DB:
        return db_helper.get_all_logs()
    else:
        try:
            log_sheet = get_attendance_sheet()
            ensure_attendance_headers(log_sheet)
            records = log_sheet.get_all_records()
        except Exception:
            records = []

        for record in records:
            record.setdefault('Status', record.get('Status', ''))
            record['sync_status'] = 'synced'
            record['data_source'] = 'remote'
            record.setdefault('Event Name', record.get('Event Name', ''))
            record.setdefault('Event ID', record.get('Event ID', ''))
            record.setdefault('Session Label', record.get('Session Label', record.get('Service', '')))
            record.setdefault('Session Period', record.get('Session Period', ''))
            record.setdefault('Session ID', record.get('Session ID', ''))
            record.setdefault('State', record.get('State', ''))
            record.setdefault('Church Location', record.get('Church Location', ''))
            record.setdefault('Camp Group', record.get('Camp Group', ''))
            record.setdefault('Notes', record.get('Notes', ''))
            # row_id will be set when fetching by date; ensure compatibility elsewhere if needed.

        pending = sync_queue.get_pending_attendance()
        for record in pending:
            record['data_source'] = 'local'
        return records + pending

def get_attendance_logs_by_date(date):
    """Get attendance logs for a specific date."""
    if USE_LOCAL_DB:
        return db_helper.get_logs_by_date(date)
    else:
        try:
            log_sheet = get_attendance_sheet()
            ensure_attendance_headers(log_sheet)
            all_logs = log_sheet.get_all_records()
        except Exception:
            all_logs = []

        filtered = []
        for i, record in enumerate(all_logs):
            if record.get('Date') == date:
                record['row_id'] = i + 2  # +1 for header, +1 for 0-based
                record['sync_status'] = 'synced'
                record['data_source'] = 'remote'
                record.setdefault('Event Name', record.get('Event Name', ''))
                record.setdefault('Event ID', record.get('Event ID', ''))
                record.setdefault('Session Label', record.get('Session Label', record.get('Service', '')))
                record.setdefault('Session Period', record.get('Session Period', ''))
                record.setdefault('Session ID', record.get('Session ID', ''))
                record.setdefault('State', record.get('State', ''))
                record.setdefault('Church Location', record.get('Church Location', ''))
                record.setdefault('Camp Group', record.get('Camp Group', ''))
                record.setdefault('Notes', record.get('Notes', ''))
                filtered.append(record)

        pending = sync_queue.get_pending_attendance(date)
        for record in pending:
            record['data_source'] = 'local'
            record['row_id'] = record.get('row_id', record.get('id'))

        return filtered + pending

def add_check_in(date, child_name, session_label, day_tag, check_in_time, *, details=None):
    """Add a check-in record."""
    details = details or {}
    event_id = details.get('event_id')
    event_name = details.get('event_name')
    session_id = details.get('session_id')
    session_period = details.get('session_period')
    state = details.get('state')
    church_location = details.get('church_location')
    camp_group = details.get('camp_group', '')
    notes = details.get('notes')
    service_value = details.get('service') or session_period or session_label

    existing_records = get_attendance_logs_by_date(date)
    for record in existing_records:
        if (record.get('Child Name') == child_name and
                record.get('Status') == 'Checked-In'):
            return {
                "synced": False,
                "pending": False,
                "error": f"{child_name} is already checked in.",
                "duplicate": True,
            }

    if USE_LOCAL_DB:
        db_helper.add_attendance_log(
            date,
            child_name,
            service_value,
            day_tag,
            check_in_time,
            "Checked-In",
            event_id=event_id,
            event_name=event_name,
            session_id=session_id,
            session_label=session_label,
            session_period=session_period,
            state=state,
            church_location=church_location,
            camp_group=camp_group,
            notes=notes,
        )
        return {"synced": True, "pending": False}
    else:
        payload_details = {
            "event_id": event_id,
            "event_name": event_name,
            "session_id": session_id,
            "session_label": session_label,
            "session_period": session_period,
            "state": state,
            "church_location": church_location,
            "camp_group": camp_group,
            "notes": notes,
            "service": service_value,
        }

        queued_record = sync_queue.add_pending_check_in(
            date,
            child_name,
            service_value,
            day_tag,
            check_in_time,
            details=payload_details,
        )

        try:
            client = get_sheets_client()
            log_sheet = get_attendance_sheet(client)
            record = {
                "date": date,
                "child_name": child_name,
                "event_name": event_name,
                "event_id": event_id,
                "session_label": session_label,
                "session_period": session_period,
                "session_id": session_id,
                "state": state,
                "church_location": church_location,
                "camp_group": camp_group,
                "service": service_value,
                "day_tag": day_tag,
                "check_in_time": check_in_time,
                "check_out_time": "",
                "status": "Checked-In",
                "notes": notes,
            }
            append_attendance_row(log_sheet, record)
            sync_queue.mark_attendance_synced(queued_record['id'])
            sync_queue.mark_queue_item_synced(queued_record['queue_id'])
            process_pending_queue(client)
            return {"synced": True, "pending": False, "record": queued_record}
        except Exception as exc:
            sync_queue.update_queue_error(queued_record['queue_id'], str(exc))
            return {
                "synced": False,
                "pending": True,
                "error": str(exc),
                "record": queued_record,
            }

def checkout_by_tag(date, tag, checkout_time):
    """Check out all children with a specific tag."""
    if USE_LOCAL_DB:
        updated_children = db_helper.checkout_by_tag(date, tag, checkout_time)
        return {
            "children": updated_children,
            "synced": True,
            "pending": False,
        }
    else:
        queued = sync_queue.add_pending_checkout(date, tag, checkout_time)

        try:
            client = get_sheets_client()
            log_sheet = get_attendance_sheet(client)
            updated_children = perform_remote_checkout(log_sheet, date, tag, checkout_time)

            if not updated_children and queued['child_names']:
                updated_children = queued['child_names']

            sync_queue.mark_queue_item_synced(queued['queue_id'])
            for attendance_id in queued['attendance_ids']:
                sync_queue.mark_attendance_synced(attendance_id)

            process_pending_queue(client)

            return {
                "children": updated_children,
                "synced": True,
                "pending": False,
            }
        except ValueError as exc:
            # Bubble up column mismatches so caller can report appropriately.
            raise exc
        except Exception as exc:
            sync_queue.update_queue_error(queued['queue_id'], str(exc))
            return {
                "children": queued['child_names'],
                "synced": False,
                "pending": True,
                "error": str(exc),
            }

def delete_attendance_log(row_id, data_source=None):
    """Delete an attendance log entry."""
    if USE_LOCAL_DB:
        db_helper.delete_log_by_id(row_id)
    else:
        if data_source == 'local':
            sync_queue.delete_local_attendance(row_id)
            return

        client = get_sheets_client()
        log_sheet = get_attendance_sheet(client)
        log_sheet.delete_rows(row_id)

def get_child_class_map():
    """Get a map of child names to their class types."""
    if USE_LOCAL_DB:
        return db_helper.get_child_class_map()
    else:
        all_children = get_all_children()
        return {child['Child Full Name']: child['Class Type'] for child in all_children}


def add_child_record(child_full_name, guardian_name, class_type,
                     state='', church_location='', guardian_phone='', notes=''):
    """Persist a child record in the current data store."""
    if not (child_full_name and guardian_name and class_type and guardian_phone):
        return False

    if USE_LOCAL_DB:
        return db_helper.add_child(
            child_full_name.strip(),
            guardian_name.strip(),
            class_type.strip(),
            state.strip() if state else None,
            church_location.strip() if church_location else None,
            guardian_phone.strip(),
            notes.strip() if notes else None,
        )

    workbook = get_workbook()
    sheet = workbook.worksheet(CHILDREN_SHEET)
    new_row = [
        child_full_name,
        guardian_name,
        class_type,
        state or '',
        church_location or '',
        '',  # Camp Group placeholder for legacy sheet structure
        guardian_phone,
        notes or '',
    ]
    sheet.append_row(new_row, value_input_option='USER_ENTERED')
    return True


def add_instructor_record(full_name, username, password, phone_number='', church_branch=''):
    """Persist instructor credentials for login access."""
    if not (full_name and username and password):
        return False

    existing_usernames = {inst.get('Username', '').strip().lower()
                          for inst in get_all_instructors()
                          if inst.get('Username')}
    if username.strip().lower() in existing_usernames:
        return False

    if USE_LOCAL_DB:
        return db_helper.add_instructor(username.strip(), password.strip(), full_name.strip(),
                                        phone_number=phone_number.strip() or None,
                                        church_branch=church_branch.strip() or None)

    workbook = get_workbook()
    sheet = workbook.worksheet(INSTRUCTORS_SHEET)
    new_row = [
        username,
        password,
        full_name,
        phone_number or '',
        church_branch or '',
    ]
    sheet.append_row(new_row, value_input_option='USER_ENTERED')
    return True


def update_child_record(row_id, child_full_name, guardian_name, class_type,
                        state='', church_location='', guardian_phone='', notes=''):
    """Update an existing child record identified by row_id."""
    if not row_id:
        raise ValueError("Row identifier is required to update a child.")

    if USE_LOCAL_DB:
        actual_id = int(row_id) - 1
        if actual_id < 1:
            raise ValueError("Invalid row identifier.")
        return db_helper.update_child(
            actual_id,
            child_full_name,
            guardian_name,
            class_type,
            state=state or None,
            church_location=church_location or None,
            guardian_phone=guardian_phone or None,
            notes=notes or None,
        )

    workbook = get_workbook()
    sheet = workbook.worksheet(CHILDREN_SHEET)
    values = [
        child_full_name,
        guardian_name,
        class_type,
        state or '',
        church_location or '',
        '',  # Camp Group placeholder
        guardian_phone or '',
        notes or '',
    ]
    sheet.update(f"A{row_id}:H{row_id}", [values])
    return True


def class_type_from_age(age_value):
    try:
        age = int(age_value)
    except (TypeError, ValueError):
        raise ValueError('Age must be a whole number.')

    if 1 <= age <= 4:
        return 'Tenderfoots'
    if 5 <= age <= 8:
        return 'Light Troopers'
    if 9 <= age <= 12:
        return 'Tribe of Truth'
    raise ValueError('Age must be between 1 and 12 to determine class type.')


def _column_name(index):
    name = ''
    while index >= 0:
        index, remainder = divmod(index, 26)
        name = chr(65 + remainder) + name
        index -= 1
    return name


def _build_children_template_xlsx(headers):
    sheet_cells = []
    for idx, header in enumerate(headers):
        col = _column_name(idx)
        cell = (
            f'<c r="{col}1" t="inlineStr">'
            f'<is><t>{escape(header)}</t></is>'
            f'</c>'
        )
        sheet_cells.append(cell)

    sheet_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<sheetData><row r=\"1\">"
        + ''.join(sheet_cells) +
        "</row></sheetData></worksheet>"
    )

    workbook_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<sheets><sheet name=\"Template\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
        "</workbook>"
    )

    workbook_rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>"
        "</Relationships>"
    )

    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        "</Types>"
    )

    root_rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "</Relationships>"
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', root_rels)
        zf.writestr('xl/workbook.xml', workbook_xml)
        zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        zf.writestr('xl/worksheets/sheet1.xml', sheet_xml)

    output.seek(0)
    return output.read()


def _parse_xlsx_children(bytes_data):
    try:
        with zipfile.ZipFile(io.BytesIO(bytes_data)) as zf:
            sheet_xml = zf.read('xl/worksheets/sheet1.xml')
    except Exception as exc:
        raise ValueError('Invalid Excel file uploaded.') from exc

    ns = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    try:
        root = ET.fromstring(sheet_xml)
    except ET.ParseError as exc:
        raise ValueError('Unable to parse worksheet data.') from exc

    rows = []
    for row_elem in root.findall('a:sheetData/a:row', ns):
        cells = []
        for cell in row_elem.findall('a:c', ns):
            text = ''
            cell_type = cell.attrib.get('t')
            if cell_type == 'inlineStr':
                t_elem = cell.find('a:is/a:t', ns)
                text = t_elem.text if t_elem is not None else ''
            else:
                v_elem = cell.find('a:v', ns)
                text = v_elem.text if v_elem is not None else ''
            cells.append((text or '').strip())
        rows.append(cells)

    if not rows:
        return [], []

    headers = [header.strip() for header in rows[0]]
    data_rows = []
    for values in rows[1:]:
        row_dict = {headers[idx]: values[idx].strip() if idx < len(values) else ''
                    for idx in range(len(headers))}
        data_rows.append(row_dict)

    return headers, data_rows


def _parse_csv_children(bytes_data):
    try:
        decoded = bytes_data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Unable to decode the uploaded CSV. Please save as UTF-8.') from exc

    stream = io.StringIO(decoded)
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        return [], []

    headers = [header.strip() for header in reader.fieldnames]
    data_rows = []
    for row in reader:
        cleaned = {header.strip(): (value.strip() if value else '') for header, value in row.items()}
        data_rows.append(cleaned)

    return headers, data_rows


def parse_children_file(bytes_data, filename):
    filename = (filename or '').lower()
    if filename.endswith('.csv'):
        return _parse_csv_children(bytes_data)
    if filename.endswith('.xlsx'):
        return _parse_xlsx_children(bytes_data)
    raise ValueError('Unsupported file type. Please upload the provided .xlsx template or a CSV file.')


def parse_page_param(value, default=1):
    try:
        page = int(value)
    except (TypeError, ValueError):
        page = default
    return page if page > 0 else default


def _generate_page_numbers(current_page, total_pages, window=2):
    if total_pages <= (window * 2) + 3:
        return list(range(1, total_pages + 1))

    pages = []
    start = max(1, current_page - window)
    end = min(total_pages, current_page + window)

    if start > 1:
        pages.append(1)
        if start > 2:
            pages.append(None)

    pages.extend(range(start, end + 1))

    if end < total_pages:
        if end < total_pages - 1:
            pages.append(None)
        pages.append(total_pages)

    return pages


def paginate_collection(items, page, per_page, endpoint, args):
    if hasattr(args, 'to_dict'):
        base_args = args.to_dict()
    else:
        base_args = dict(args)
    base_args.pop('page', None)

    total = len(items)
    total_pages = max(1, math.ceil(total / per_page)) if total else 1
    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'has_prev': False,
        'has_next': False,
    }

    if total == 0:
        pagination['pages'] = []
        pagination['show'] = False
        pagination['page'] = 1
        pagination['total_pages'] = 1
        return items, pagination

    page = min(max(page, 1), total_pages)
    pagination['page'] = page
    pagination['has_prev'] = page > 1
    pagination['has_next'] = page < total_pages

    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]

    def build_url(target_page):
        params = dict(base_args)
        params['page'] = target_page
        return url_for(endpoint, **params)

    pagination['pages'] = []
    for num in _generate_page_numbers(page, total_pages):
        if num is None:
            pagination['pages'].append({'ellipsis': True})
        else:
            pagination['pages'].append({
                'number': num,
                'url': build_url(num),
                'current': num == page,
            })

    pagination['show'] = total > per_page
    if pagination['has_prev']:
        pagination['prev_url'] = build_url(page - 1)
    if pagination['has_next']:
        pagination['next_url'] = build_url(page + 1)

    return page_items, pagination

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    error = None
    if request.method == 'POST':
        submitted_username = request.form['username']
        submitted_password = request.form['password']

        try:
            all_instructors = get_all_instructors()

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

    if not USE_LOCAL_DB:
        process_pending_queue(limit=10)

    now = datetime.now(NIGERIA_TZ)
    today_date_str = now.strftime("%Y-%m-%d")

    event_options = get_event_options()

    default_event = get_event()
    default_event_id = default_event.get('id') if default_event else DEFAULT_EVENT_ID

    selected_event_id = request.values.get('event_id') or default_event_id
    if selected_event_id == DEFAULT_EVENT_ID:
        available_dates = sorted({record.get('Date') for record in get_all_attendance_logs() if record.get('Date')})
    else:
        available_dates = get_event_dates(selected_event_id)

    user_supplied_date = bool(request.values.get('session_day') or request.values.get('date'))
    selected_session_date = request.values.get('session_day') or request.values.get('date') or today_date_str

    session_options = get_sessions_for_date(selected_event_id, selected_session_date)
    selected_session_id = request.values.get('session_id')
    if session_options:
        session_ids = {session['id'] for session in session_options}
        if selected_session_id not in session_ids:
            selected_session_id = session_options[0]['id']
    else:
        selected_session_id = None

    if selected_event_id != DEFAULT_EVENT_ID and not session_options and not user_supplied_date:
        event_dates = get_event_dates(selected_event_id)
        preferred_date = None
        if today_date_str in event_dates:
            preferred_date = today_date_str
        elif event_dates:
            preferred_date = max(event_dates)
        if preferred_date:
            selected_session_date = preferred_date
            session_options = get_sessions_for_date(selected_event_id, selected_session_date)
            if session_options:
                selected_session_id = session_options[0]['id']

    selected_event = get_event(selected_event_id)

    page = parse_page_param(request.values.get('page', request.args.get('page', 1)))

    checkout_preview = None
    checkout_tag_value = ''

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'check_in':
            current_page = parse_page_param(request.form.get('page', page))
            child_names = request.form.getlist('child_names') or []
            if not child_names:
                fallback_child = request.form.get('child_name')
                if fallback_child:
                    child_names = [fallback_child]
            child_names = [name for name in child_names if name]
            if not child_names:
                flash("Select at least one child to check in.", "error")
                return redirect(url_for('attendance_log', event_id=selected_event_id,
                                        date=selected_session_date, page=current_page))
            day_tag = request.form['day_tag']
            session_data = find_session(selected_event_id, selected_session_id)
            service_type = request.form.get('service_type') if selected_event_id == DEFAULT_EVENT_ID else None

            if session_data:
                session_label = session_data.get('label')
                session_period = session_data.get('period')
                session_date = session_data.get('date')
            else:
                session_label = service_type or (selected_event.get('name') if selected_event else 'Church Service')
                session_period = ''
                session_date = selected_session_date
            service_value = service_type or session_period or session_label
            current_time = datetime.now(NIGERIA_TZ).strftime("%I:%M %p")

            manual_state = request.form.get('state')
            manual_church_location = request.form.get('church_location')
            notes = request.form.get('notes') or ''

            success_children = []
            warning_children = []
            duplicate_children = []

            for child_name in child_names:
                child_details = get_child_details(child_name) or {}
                state = manual_state or child_details.get('State') or ''
                church_location = manual_church_location or child_details.get('Church Location') or ''

                details = {
                    'event_id': selected_event_id,
                    'event_name': selected_event.get('name') if selected_event else '',
                    'session_id': session_data.get('id') if session_data else selected_session_id,
                    'session_label': session_label,
                    'session_period': session_period,
                    'state': state,
                    'church_location': church_location,
                    'notes': notes,
                    'service': service_value,
                }

                result = add_check_in(session_date, child_name, session_label, day_tag, current_time, details=details)

                if result.get('duplicate'):
                    duplicate_children.append(child_name)
                elif result.get('synced'):
                    success_children.append(child_name)
                else:
                    warning_children.append(child_name)

            if success_children:
                flash(
                    f"{', '.join(success_children)} checked in for {session_label} (Tag #{day_tag}).",
                    "success"
                )
            if warning_children:
                flash(
                    f"{', '.join(warning_children)} saved locally for {session_label} (Tag #{day_tag}). We'll sync once you're back online.",
                    "warning"
                )
            if duplicate_children:
                flash(
                    f"{', '.join(duplicate_children)} already have check-ins for {session_label}.",
                    "error"
                )

            redirect_params = {
                'event_id': selected_event_id,
                'date': session_date,
            }
            if selected_session_id:
                redirect_params['session_id'] = selected_session_id
            if selected_event_id == DEFAULT_EVENT_ID:
                redirect_params['service_type'] = service_type or '1st Service'
            if current_page > 1:
                redirect_params['page'] = current_page

            return redirect(url_for('attendance_log', **redirect_params))

        elif action == 'find_tag':
            current_page = parse_page_param(request.form.get('page', page))
            page = current_page

            checkout_tag = request.form['checkout_tag']
            checkout_tag_value = checkout_tag

            children = get_checked_in_children(selected_session_date, checkout_tag)
            if children:
                checkout_preview = {
                    'tag': checkout_tag,
                    'children': children,
                }
            else:
                flash(f"No active check-ins found for tag #{checkout_tag} on {selected_session_date}.", "error")

        elif action == 'checkout_confirm':
            current_page = parse_page_param(request.form.get('page', page))
            checkout_tag = request.form['checkout_tag']
            current_time = datetime.now(NIGERIA_TZ).strftime("%I:%M %p")

            try:
                result = checkout_by_tag(selected_session_date, checkout_tag, current_time)
                updated_children = result.get('children', [])

                if updated_children:
                    message = f"Checked out {', '.join(updated_children)} (Tag #{checkout_tag})."
                    if result.get('pending'):
                        message += " Stored locally and will sync once online."
                        flash(message, "warning")
                    else:
                        flash(message, "success")
                else:
                    flash(f"No active check-ins found for tag #{checkout_tag} on {selected_session_date}.", "error")
            except ValueError as e:
                flash(f"Error: A required column is missing. Details: {e}", "error")

            redirect_params = {
                'event_id': selected_event_id,
                'date': selected_session_date,
            }
            if selected_session_id:
                redirect_params['session_id'] = selected_session_id
            if selected_event_id == DEFAULT_EVENT_ID:
                redirect_params['service_type'] = request.form.get('service_type') or '1st Service'
            if current_page > 1:
                redirect_params['page'] = current_page

            return redirect(url_for('attendance_log', **redirect_params))

    children_records = get_all_children()
    children_names = [child['Child Full Name'] for child in children_records]
    children_meta = {}
    for child in children_records:
        children_meta[child['Child Full Name']] = {
            'guardian_name': child.get('Guardian Name'),
            'class_type': child.get('Class Type'),
            'state': child.get('State') or '',
            'church_location': child.get('Church Location') or '',
            'guardian_phone': child.get('Guardian Phone') or '',
            'notes': child.get('Notes') or '',
        }

    if checkout_preview and checkout_preview.get('children'):
        preview_details = []
        for child_name in checkout_preview['children']:
            meta = children_meta.get(child_name, {})
            preview_details.append({
                'child': child_name,
                'guardian': meta.get('guardian_name') or 'N/A',
                'class_type': meta.get('class_type') or 'N/A',
            })
        checkout_preview['details'] = preview_details

    state_options = selected_event.get('states', []) if selected_event else []
    if not state_options:
        state_options = sorted({meta['state'] for meta in children_meta.values() if meta['state']})

    event_locations = selected_event.get('church_locations', []) if selected_event else []
    fallback_locations = {meta['church_location'] for meta in children_meta.values() if meta['church_location']}
    church_locations = list(DEFAULT_CHURCH_LOCATIONS)
    for loc in event_locations:
        if loc and loc not in church_locations:
            church_locations.append(loc)
    for loc in sorted(fallback_locations):
        if loc and loc not in church_locations:
            church_locations.append(loc)

    attendance_records = get_attendance_logs_by_date(selected_session_date)
    child_to_class_map = get_child_class_map()
    for record in attendance_records:
        child_name = record.get('Child Name')
        record['class_type'] = child_to_class_map.get(child_name, 'N/A')

    service_type_default = request.args.get('service_type', '')
    if not service_type_default and request.method == 'POST':
        service_type_default = request.form.get('service_type', '')
    if not service_type_default and selected_event_id == DEFAULT_EVENT_ID:
        service_type_default = '1st Service'
    if selected_event_id != DEFAULT_EVENT_ID:
        service_type_default = ''

    attendance_query_args = {
        'event_id': selected_event_id,
        'date': selected_session_date,
    }
    if selected_session_id:
        attendance_query_args['session_id'] = selected_session_id
    if selected_event_id == DEFAULT_EVENT_ID and service_type_default:
        attendance_query_args['service_type'] = service_type_default

    attendance_today, attendance_pagination = paginate_collection(
        attendance_records,
        page,
        ATTENDANCE_PER_PAGE,
        'attendance_log',
        attendance_query_args
    )

    display_date = datetime.strptime(selected_session_date, "%Y-%m-%d").strftime("%B %d, %Y") if selected_session_date else now.strftime("%B %d, %Y")

    return render_template(
        'attendance.html',
        children_names=children_names,
        attendance_today=attendance_today,
        today_date=display_date,
        event_options=event_options,
        selected_event_id=selected_event_id,
        session_dates=available_dates,
        selected_session_date=selected_session_date,
        session_options=session_options,
        selected_session_id=selected_session_id,
        state_options=state_options,
        church_locations=church_locations,
        children_meta=children_meta,
        selected_event=selected_event,
        service_type_default=service_type_default,
        checkout_preview=checkout_preview,
        checkout_tag_value=checkout_tag_value,
        attendance_pagination=attendance_pagination,
    )

@app.route('/dashboard')
def dashboard():
    """Displays the main dashboard with summary statistics."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    event_options = get_event_options()
    default_event = get_event()
    default_event_id = default_event.get('id') if default_event else DEFAULT_EVENT_ID
    selected_event_id = request.args.get('event_id') or default_event_id
    selected_event = get_event(selected_event_id)

    all_children = get_all_children()
    total_children = len(all_children)
    child_to_class_map = get_child_class_map()

    all_logs = get_all_attendance_logs()
    today_date_str = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")
    attendance_today = [record for record in all_logs if record.get('Date') == today_date_str]
    if selected_event_id:
        attendance_today = [record for record in attendance_today if record.get('Event ID') in (selected_event_id, '', None)]
    checked_in_today = len(attendance_today)

    class_breakdown = {"Tenderfoots": 0, "Light Troopers": 0, "Tribe of Truth": 0}
    if selected_event_id == DEFAULT_EVENT_ID:
        session_breakdown = {"1st Service": 0, "2nd Service": 0, "Other": 0}
    else:
        session_breakdown = {"Morning": 0, "Afternoon": 0, "Evening": 0, "Other": 0}

    for record in attendance_today:
        if selected_event_id == DEFAULT_EVENT_ID:
            period_label = record.get('Service') or 'Other'
        else:
            period_label = record.get('Session Period') or record.get('Service') or 'Other'
        if period_label not in session_breakdown:
            session_breakdown[period_label] = 0
        session_breakdown[period_label] += 1

        child_name = record.get('Child Name')
        if child_name in child_to_class_map:
            child_class = child_to_class_map[child_name]
            if child_class in class_breakdown:
                class_breakdown[child_class] += 1

    return render_template('dashboard.html',
                           instructor_name=session.get('full_name', 'Instructor'),
                           today_date=datetime.now(NIGERIA_TZ).strftime("%B %d, %Y"),
                           total_children=total_children,
                           checked_in_today=checked_in_today,
                            class_breakdown=class_breakdown,
                           session_breakdown=session_breakdown,
                           selected_event=selected_event,
                           event_options=event_options,
                           selected_event_id=selected_event_id)

@app.route('/children')
def children_list():
    """Displays a list of all children."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    all_children = get_all_children()
    existing_locations = {child.get('Church Location') for child in all_children if child.get('Church Location')}
    extra_locations = sorted(loc for loc in existing_locations if loc not in DEFAULT_CHURCH_LOCATIONS)
    location_options = DEFAULT_CHURCH_LOCATIONS + extra_locations
    indexed_children = []
    for idx, child in enumerate(all_children, start=2):
        child_copy = dict(child)
        child_copy.setdefault('row_id', idx)
        indexed_children.append(child_copy)

    newest_first_children = sorted(indexed_children,
                                   key=lambda record: record.get('row_id', 0),
                                   reverse=True)

    page = parse_page_param(request.args.get('page', 1))
    paginated_children, pagination = paginate_collection(newest_first_children, page, CHILDREN_PER_PAGE,
                                                        'children_list', request.args)

    return render_template('children.html', children_list=paginated_children, pagination=pagination,
                           location_options=location_options)


@app.route('/children/add', methods=['POST'])
def add_child():
    """Adds a single child via the Add Child modal."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    child_name = (request.form.get('child_full_name') or '').strip()
    guardian_name = (request.form.get('guardian_name') or '').strip()
    guardian_phone = (request.form.get('guardian_phone') or '').strip()
    age_value = (request.form.get('age') or '').strip()
    state = (request.form.get('state') or '').strip()
    church_location = (request.form.get('church_location') or '').strip()
    notes = (request.form.get('notes') or '').strip()

    if not child_name or not guardian_name or not guardian_phone or not age_value:
        flash('Child name, guardian name, guardian phone, and age are required.', 'error')
        return redirect(url_for('children_list'))

    try:
        class_type = class_type_from_age(age_value)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('children_list'))

    try:
        added = add_child_record(
            child_name,
            guardian_name,
            class_type,
            state=state,
            church_location=church_location,
            guardian_phone=guardian_phone,
            notes=notes,
        )
    except Exception as exc:
        flash(f"Could not add child: {exc}", 'error')
        return redirect(url_for('children_list'))

    if added:
        flash(f"{child_name} added successfully.", 'success')
    else:
        flash(f"Unable to add {child_name}. They may already exist.", 'warning')

    return redirect(url_for('children_list'))


@app.route('/instructors/add', methods=['POST'])
def add_instructor():
    """Add a new instructor account."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    full_name = (request.form.get('instructor_name') or '').strip()
    username = (request.form.get('instructor_username') or '').strip()
    phone_number = (request.form.get('instructor_phone') or '').strip()
    church_branch = (request.form.get('instructor_branch') or '').strip()
    password = (request.form.get('instructor_password') or '').strip()
    confirm_password = (request.form.get('instructor_password_confirm') or '').strip()

    if not full_name or not username or not password:
        flash('Name, username, and password are required for an instructor.', 'error')
        return redirect(request.referrer or url_for('dashboard'))
    if password != confirm_password:
        flash('Password and Confirm Password must match.', 'error')
        return redirect(request.referrer or url_for('dashboard'))

    try:
        created = add_instructor_record(
            full_name,
            username,
            password,
            phone_number=phone_number,
            church_branch=church_branch,
        )
    except Exception as exc:
        flash(f"Unable to add instructor: {exc}", 'error')
        return redirect(request.referrer or url_for('dashboard'))

    if created:
        flash(f"Instructor {full_name} added successfully.", 'success')
    else:
        flash(f"Could not add {full_name}. The username may already exist.", 'warning')

    return redirect(request.referrer or url_for('dashboard'))


@app.route('/children/template')
def download_children_template():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    headers = [
        'Child Full Name',
        'Guardian Name',
        'Age',
        'State',
        'Church Location',
        'Guardian Phone',
        'Notes',
    ]
    xlsx_bytes = _build_children_template_xlsx(headers)
    response = Response(xlsx_bytes, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response.headers['Content-Disposition'] = 'attachment; filename=children_template.xlsx'
    return response


@app.route('/children/import', methods=['POST'])
def import_children():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    upload = request.files.get('children_csv')
    if not upload or upload.filename == '':
        flash('Please choose a template file to upload.', 'error')
        return redirect(url_for('children_list'))

    file_bytes = upload.read()
    try:
        headers, data_rows = parse_children_file(file_bytes, upload.filename)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('children_list'))

    if not headers:
        flash('The uploaded file appears to be empty.', 'error')
        return redirect(url_for('children_list'))
    required_columns = ['Child Full Name', 'Guardian Name', 'Age', 'Guardian Phone']
    missing_columns = [col for col in required_columns if col not in headers]
    if missing_columns:
        flash(f"Missing required column(s): {', '.join(missing_columns)}.", 'error')
        return redirect(url_for('children_list'))

    existing_names = {child['Child Full Name'].strip().lower()
                      for child in get_all_children() if child.get('Child Full Name')}

    imported_count = 0
    skipped = []
    errors = []

    for row_number, row_dict in enumerate(data_rows, start=2):
        row_dict = {key: (value or '').strip() for key, value in row_dict.items()}

        if all(not (value or '').strip() for value in row_dict.values()):
            continue

        child_name = (row_dict.get('Child Full Name') or '').strip()
        guardian_name = (row_dict.get('Guardian Name') or '').strip()
        guardian_phone = (row_dict.get('Guardian Phone') or '').strip()
        age_value = (row_dict.get('Age') or '').strip()

        if not child_name or not guardian_name or not age_value or not guardian_phone:
            errors.append(f"Row {row_number}: Missing required values.")
            continue

        try:
            derived_class_type = class_type_from_age(age_value)
        except ValueError as exc:
            errors.append(f"Row {row_number}: {exc}")
            continue

        normalized_name = child_name.lower()
        if normalized_name in existing_names:
            skipped.append(child_name)
            continue

        state = (row_dict.get('State') or '').strip()
        church_location = (row_dict.get('Church Location') or '').strip()
        notes = (row_dict.get('Notes') or '').strip()

        try:
            if add_child_record(child_name, guardian_name, derived_class_type,
                                state=state,
                                church_location=church_location,
                                guardian_phone=guardian_phone,
                                notes=notes):
                imported_count += 1
                existing_names.add(normalized_name)
            else:
                skipped.append(child_name)
        except Exception as exc:
            errors.append(f"Row {row_number}: {exc}")

    if imported_count:
        flash(f"Imported {imported_count} child(ren) successfully.", 'success')
    if skipped:
        skipped_preview = ', '.join(skipped[:5])
        if len(skipped) > 5:
            skipped_preview += ', ...'
        flash(f"Skipped {len(skipped)} existing record(s): {skipped_preview}", 'warning')
    if errors:
        errors_preview = '; '.join(errors[:3])
        if len(errors) > 3:
            errors_preview += '; ...'
        flash(f"Some rows could not be imported: {errors_preview}", 'error')
    if not imported_count and not skipped and not errors:
        flash('No valid rows found in the uploaded file.', 'warning')

    return redirect(url_for('children_list'))

@app.route('/child/<int:row_id>')
def child_details(row_id):
    """Displays details for a single child."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    all_children = get_all_children()
    existing_locations = {child.get('Church Location') for child in all_children if child.get('Church Location')}
    extra_locations = sorted(loc for loc in existing_locations if loc not in DEFAULT_CHURCH_LOCATIONS)
    location_options = DEFAULT_CHURCH_LOCATIONS + extra_locations
    child_record = None
    for idx, child in enumerate(all_children, start=2):
        current_row_id = child.get('row_id', idx)
        if current_row_id == row_id:
            child_record = child
            break

    if not child_record:
        abort(404)

    class_options = ['Tenderfoots', 'Light Troopers', 'Tribe of Truth']

    return render_template('child_details.html', child=child_record, class_options=class_options,
                           location_options=location_options)


@app.route('/child/<int:row_id>/update', methods=['POST'])
def update_child_details(row_id):
    """Updates a child's details."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    child_name = (request.form.get('child_full_name') or '').strip()
    class_type = (request.form.get('class_type') or '').strip()
    guardian_name = (request.form.get('guardian_name') or '').strip()
    guardian_phone = (request.form.get('guardian_phone') or '').strip()
    state = (request.form.get('state') or '').strip()
    church_location = (request.form.get('church_location') or '').strip()
    notes = (request.form.get('notes') or '').strip()

    if not child_name or not class_type or not guardian_name or not guardian_phone:
        flash('Child name, class type, guardian name, and guardian phone are required.', 'error')
        return redirect(url_for('child_details', row_id=row_id))

    try:
        updated = update_child_record(
            row_id,
            child_name,
            guardian_name,
            class_type,
            state=state,
            church_location=church_location,
            guardian_phone=guardian_phone,
            notes=notes,
        )
    except Exception as exc:
        flash(f"Unable to update child: {exc}", 'error')
        return redirect(url_for('child_details', row_id=row_id))

    if updated:
        flash('Child details updated successfully.', 'success')
    else:
        flash('No changes were saved.', 'warning')

    return redirect(url_for('child_details', row_id=row_id))

@app.route('/reports')
def reports():
    """Handles the reports page with filtering capabilities."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    today_date_str = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")
    event_options = get_event_options()
    default_event = get_event()
    default_event_id = default_event.get('id') if default_event else DEFAULT_EVENT_ID
    selected_event_id = request.args.get('event_id') or default_event_id
    selected_event = get_event(selected_event_id)

    selected_date = request.args.get('date', default=today_date_str)
    selected_service = request.args.get('service', default='All')
    selected_session_id = request.args.get('session_id', default='All')
    selected_state = request.args.get('state', default='All')
    selected_location = request.args.get('church_location', default='All')
    selected_class = request.args.get('class_type', default='All')
    selected_tag = request.args.get('day_tag', default='')
    page = parse_page_param(request.args.get('page', 1))
    heading_date = selected_date or today_date_str

    report_data = apply_report_filters(selected_event_id, selected_date, selected_service,
                                       selected_session_id, selected_class, selected_state,
                                       selected_location, selected_tag)
    filtered_records = report_data['filtered_records']
    child_to_class_map = report_data['child_to_class_map']
    children_records = report_data['children_records']
    all_logs = report_data['all_logs']

    paginated_records, report_pagination = paginate_collection(
        filtered_records,
        page,
        REPORTS_PER_PAGE,
        'reports',
        request.args
    )

    # Grouping Logic
    grouped_records = defaultdict(list)
    for record in paginated_records:
        tag = record.get('Day Tag') or 'N/A'
        session_label = record.get('Session Label') or record.get('Service') or 'Session'
        grouped_records[(record.get('Date'), session_label, tag)].append(record)

    grouped_records = dict(sorted(grouped_records.items()))

    selected_filters = {
        'event_id': selected_event_id,
        'date': selected_date,
        'service': selected_service,
        'session_id': selected_session_id,
        'class_type': selected_class,
        'state': selected_state,
        'church_location': selected_location,
        'day_tag': selected_tag,
        'page': page,
    }

    export_params = dict(selected_filters)
    export_params.pop('page', None)

    session_dates = get_event_dates(selected_event_id)
    session_options = []
    if selected_date:
        session_options = get_sessions_for_date(selected_event_id, selected_date)

    state_options = selected_event.get('states', []) if selected_event else []
    if not state_options:
        state_options = sorted({child.get('State') for child in children_records if child.get('State')})

    event_locations = selected_event.get('church_locations', []) if selected_event else []
    fallback_locations = {child.get('Church Location') for child in children_records if child.get('Church Location')}
    location_options = list(DEFAULT_CHURCH_LOCATIONS)
    for loc in event_locations:
        if loc and loc not in location_options:
            location_options.append(loc)
    for loc in sorted(fallback_locations):
        if loc and loc not in location_options:
            location_options.append(loc)

    service_options: list[dict] = []

    def add_service_option(value: str, label: str | None = None) -> None:
        if not value:
            return
        if any(opt["value"] == value for opt in service_options):
            return
        service_options.append({"value": value, "label": label or value})

    if selected_event_id == DEFAULT_EVENT_ID:
        add_service_option("1st Service")
        add_service_option("2nd Service")
    elif selected_event_id == "rebootcamp":
        add_service_option("Morning", "Morning Session")
        add_service_option("Afternoon", "Afternoon Session")
        add_service_option("Evening", "Evening Session")
    else:
        periods = sorted({session.get('period') for session in selected_event.get('sessions', []) if session.get('period')})
        if not periods:
            periods = ["Morning", "Afternoon", "Evening"]
        for period in periods:
            add_service_option(period)

    log_services = [
        rec.get('Service')
        for rec in all_logs
        if rec.get('Service') and rec.get('Event ID') in (selected_event_id, '', None)
    ]
    for value in log_services:
        add_service_option(value)

    return render_template('reports.html',
                           grouped_records=grouped_records,
                           record_count=len(filtered_records),
                           selected_filters=selected_filters,
                           event_options=event_options,
                           selected_event=selected_event,
                           session_dates=session_dates,
                           session_options=session_options,
                           state_options=state_options,
                           location_options=location_options,
                           service_options=service_options,
                           report_pagination=report_pagination,
                           export_params=export_params)


@app.route('/reports/export')
def export_reports():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    today_date_str = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")
    default_event = get_event()
    default_event_id = default_event.get('id') if default_event else DEFAULT_EVENT_ID

    selected_event_id = request.args.get('event_id') or default_event_id
    selected_date = request.args.get('date', default=today_date_str)
    selected_service = request.args.get('service', default='All')
    selected_session_id = request.args.get('session_id', default='All')
    selected_class = request.args.get('class_type', default='All')
    selected_state = request.args.get('state', default='All')
    selected_location = request.args.get('church_location', default='All')
    selected_tag = request.args.get('day_tag', default='')

    report_data = apply_report_filters(selected_event_id, selected_date, selected_service,
                                       selected_session_id, selected_class, selected_state,
                                       selected_location, selected_tag)
    filtered_records = report_data['filtered_records']

    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        'Date', 'Event Name', 'Event ID', 'Session Label', 'Session Period', 'Service',
        'Child Name', 'Class Type', 'State', 'Church Location', 'Day Tag',
        'Check-in Time', 'Check-out Time', 'Status', 'Notes', 'Sync Status', 'Data Source'
    ]
    writer.writerow(headers)

    for record in filtered_records:
        writer.writerow([
            record.get('Date', ''),
            record.get('Event Name', ''),
            record.get('Event ID', ''),
            record.get('Session Label', '') or record.get('Service', ''),
            record.get('Session Period', ''),
            record.get('Service', ''),
            record.get('Child Name', ''),
            record.get('class_type', ''),
            record.get('State', ''),
            record.get('Church Location', ''),
            record.get('Day Tag', ''),
            record.get('Check-in Time', ''),
            record.get('Check-out Time', ''),
            record.get('Status', ''),
            record.get('Notes', ''),
            record.get('sync_status', ''),
            record.get('data_source', ''),
        ])

    csv_data = output.getvalue()
    output.close()

    filename = f"attendance_report_{datetime.now(NIGERIA_TZ).strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(csv_data, mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/delete_log/<int:row_id>', methods=['POST'])
def delete_log(row_id):
    """Deletes a specific row from the AttendanceLog."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    try:
        data_source = request.form.get('data_source')
        delete_attendance_log(row_id, data_source=data_source)
        flash(f"Record deleted successfully.", "success")
    except Exception as e:
        flash(f"Error while deleting record: {e}", "error")

    return redirect(request.referrer or url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
