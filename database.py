import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'attendance_local.db')

def init_database():
    """Initialize the SQLite database with required tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create Instructors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS instructors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create Children table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS children (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_full_name TEXT NOT NULL,
            guardian_name TEXT NOT NULL,
            class_type TEXT NOT NULL,
            state TEXT,
            church_location TEXT,
            camp_group TEXT,
            guardian_phone TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(child_full_name)
        )
    ''')

    # Create AttendanceLog table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            child_name TEXT NOT NULL,
            service TEXT NOT NULL,
            day_tag TEXT NOT NULL,
            check_in_time TEXT NOT NULL,
            check_out_time TEXT DEFAULT '',
            status TEXT NOT NULL,
            event_id TEXT,
            event_name TEXT,
            session_id TEXT,
            session_label TEXT,
            session_period TEXT,
            state TEXT,
            church_location TEXT,
            camp_group TEXT,
            notes TEXT,
            sync_status TEXT NOT NULL DEFAULT 'synced',
            synced_at TEXT,
            sync_uuid TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            record_id INTEGER,
            operation TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempt_at TEXT,
            sync_uuid TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    _ensure_child_columns(cursor)
    _ensure_attendance_columns(cursor)

    # Create indexes for faster queries
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_log(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_tag ON attendance_log(day_tag)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_status ON attendance_log(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_sync_status ON attendance_log(sync_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_event ON attendance_log(event_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance_log(session_id)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_sync_uuid ON attendance_log(sync_uuid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status)')

    conn.commit()
    conn.close()
    print(f"✓ Database initialized at: {DB_PATH}")


def _ensure_child_columns(cursor):
    """Ensure new child metadata columns exist on older databases."""
    cursor.execute("PRAGMA table_info(children)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    child_column_statements = []
    if 'state' not in existing_columns:
        child_column_statements.append("ALTER TABLE children ADD COLUMN state TEXT")
    if 'church_location' not in existing_columns:
        child_column_statements.append("ALTER TABLE children ADD COLUMN church_location TEXT")
    if 'camp_group' not in existing_columns:
        child_column_statements.append("ALTER TABLE children ADD COLUMN camp_group TEXT")
    if 'guardian_phone' not in existing_columns:
        child_column_statements.append("ALTER TABLE children ADD COLUMN guardian_phone TEXT")
    if 'notes' not in existing_columns:
        child_column_statements.append("ALTER TABLE children ADD COLUMN notes TEXT")

    for stmt in child_column_statements:
        cursor.execute(stmt)


def _ensure_attendance_columns(cursor):
    """Ensure sync and RebootCamp columns exist on older attendance tables."""
    cursor.execute("PRAGMA table_info(attendance_log)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    statements = []
    if 'event_id' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN event_id TEXT")
    if 'event_name' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN event_name TEXT")
    if 'session_id' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN session_id TEXT")
    if 'session_label' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN session_label TEXT")
    if 'session_period' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN session_period TEXT")
    if 'state' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN state TEXT")
    if 'church_location' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN church_location TEXT")
    if 'camp_group' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN camp_group TEXT")
    if 'notes' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN notes TEXT")
    if 'sync_status' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced'")
    if 'synced_at' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN synced_at TEXT")
    if 'sync_uuid' not in existing_columns:
        statements.append("ALTER TABLE attendance_log ADD COLUMN sync_uuid TEXT")

    for stmt in statements:
        cursor.execute(stmt)

    if 'sync_status' not in existing_columns:
        cursor.execute("UPDATE attendance_log SET sync_status = 'synced' WHERE sync_status IS NULL")

def get_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

def drop_all_tables():
    """Drop all tables (useful for resetting database)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS instructors")
    cursor.execute("DROP TABLE IF EXISTS children")
    cursor.execute("DROP TABLE IF EXISTS attendance_log")
    cursor.execute("DROP TABLE IF EXISTS sync_queue")

    conn.commit()
    conn.close()
    print("✓ All tables dropped")

if __name__ == "__main__":
    # Initialize database when run directly
    print("Initializing database...")
    init_database()
    print("Database setup complete!")
