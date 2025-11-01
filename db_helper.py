"""
Database helper functions that mirror Google Sheets interface.
This allows seamless switching between local SQLite and production Google Sheets.
"""

import sqlite3
from database import get_connection

# ============= INSTRUCTORS =============

def get_all_instructors():
    """Get all instructors as a list of dictionaries (mimics gspread.get_all_records())."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username as Username, password as Password, full_name as FullName FROM instructors")

    rows = cursor.fetchall()
    conn.close()

    # Convert to list of dicts (matching Google Sheets format)
    return [dict(row) for row in rows]

def add_instructor(username, password, full_name):
    """Add a new instructor."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO instructors (username, password, full_name) VALUES (?, ?, ?)",
            (username, password, full_name)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Username already exists
    finally:
        conn.close()

# ============= CHILDREN =============

def get_all_children():
    """Get all children as a list of dictionaries."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            child_full_name as 'Child Full Name',
            guardian_name as 'Guardian Name',
            class_type as 'Class Type',
            state as 'State',
            church_location as 'Church Location',
            camp_group as 'Camp Group',
            guardian_phone as 'Guardian Phone',
            notes as 'Notes'
        FROM children
        ORDER BY child_full_name
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def get_children_names():
    """Get list of all children names."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT child_full_name FROM children ORDER BY child_full_name")

    rows = cursor.fetchall()
    conn.close()

    return [row['child_full_name'] for row in rows]

def add_child(child_full_name, guardian_name, class_type,
              state=None, church_location=None, camp_group=None,
              guardian_phone=None, notes=None):
    """Add a new child."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO children (child_full_name, guardian_name, class_type, state,
                                  church_location, camp_group, guardian_phone, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (child_full_name, guardian_name, class_type, state, church_location, camp_group, guardian_phone, notes)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Child already exists
    finally:
        conn.close()

def get_child_class_map():
    """Get a dictionary mapping child names to their class types."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT child_full_name, class_type FROM children")

    rows = cursor.fetchall()
    conn.close()

    return {row['child_full_name']: row['class_type'] for row in rows}

# ============= ATTENDANCE LOG =============

def get_all_logs():
    """Get all attendance logs as a list of dictionaries."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            id,
            date as 'Date',
            child_name as 'Child Name',
            service as 'Service',
            day_tag as 'Day Tag',
            check_in_time as 'Check-in Time',
            check_out_time as 'Check-out Time',
            status as 'Status',
            event_id as 'Event ID',
            event_name as 'Event Name',
            session_id as 'Session ID',
            session_label as 'Session Label',
            session_period as 'Session Period',
            state as 'State',
            church_location as 'Church Location',
            camp_group as 'Camp Group',
            notes as 'Notes'
        FROM attendance_log
        ORDER BY date DESC, check_in_time DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def get_logs_by_date(date):
    """Get attendance logs for a specific date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            id,
            date as 'Date',
            child_name as 'Child Name',
            service as 'Service',
            day_tag as 'Day Tag',
            check_in_time as 'Check-in Time',
            check_out_time as 'Check-out Time',
            status as 'Status',
            event_id as 'Event ID',
            event_name as 'Event Name',
            session_id as 'Session ID',
            session_label as 'Session Label',
            session_period as 'Session Period',
            state as 'State',
            church_location as 'Church Location',
            camp_group as 'Camp Group',
            notes as 'Notes'
        FROM attendance_log
        WHERE date = ?
        ORDER BY check_in_time
    """, (date,))

    rows = cursor.fetchall()
    conn.close()

    # Add row_id for delete functionality
    result = []
    for row in rows:
        record = dict(row)
        record['row_id'] = record['id']
        result.append(record)

    return result

def add_attendance_log(date, child_name, service, day_tag, check_in_time,
                       status="Checked-In", event_id=None, event_name=None,
                       session_id=None, session_label=None, session_period=None,
                       state=None, church_location=None, camp_group=None, notes=None):
    """Add a new attendance log entry."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO attendance_log
        (date, child_name, service, day_tag, check_in_time, check_out_time, status,
         event_id, event_name, session_id, session_label, session_period,
         state, church_location, camp_group, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (date, child_name, service, day_tag, check_in_time, "", status,
     event_id, event_name, session_id, session_label, session_period,
     state, church_location, camp_group, notes))

    conn.commit()
    conn.close()

def checkout_by_tag(date, tag, checkout_time):
    """Check out all children with a specific tag on a specific date."""
    conn = get_connection()
    cursor = conn.cursor()

    # Find all checked-in children with this tag today
    cursor.execute("""
        SELECT id, child_name FROM attendance_log
        WHERE date = ? AND day_tag = ? AND status = 'Checked-In'
    """, (date, tag))

    rows = cursor.fetchall()
    updated_children = [row['child_name'] for row in rows]

    if rows:
        # Update all matching records
        cursor.execute("""
            UPDATE attendance_log
            SET check_out_time = ?, status = 'Checked-Out'
            WHERE date = ? AND day_tag = ? AND status = 'Checked-In'
        """, (checkout_time, date, tag))

        conn.commit()

    conn.close()
    return updated_children


def get_checked_in_by_tag(date, tag):
    """Return list of children currently checked in with the given tag."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT child_name FROM attendance_log
        WHERE date = ? AND day_tag = ? AND status = 'Checked-In'
        ORDER BY check_in_time
        """,
        (date, tag)
    )
    rows = cursor.fetchall()
    conn.close()
    return [row['child_name'] for row in rows]


def delete_log_by_id(log_id):
    """Delete an attendance log entry by ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM attendance_log WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()

def get_log_headers():
    """Get attendance log column headers (for compatibility with Google Sheets interface)."""
    return [
        'Date',
        'Child Name',
        'Event ID',
        'Event Name',
        'Session ID',
        'Session Label',
        'Session Period',
        'State',
        'Church Location',
        'Camp Group',
        'Service',
        'Day Tag',
        'Check-in Time',
        'Check-out Time',
        'Status',
        'Notes'
    ]
