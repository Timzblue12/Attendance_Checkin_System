"""
Seed the local database with test data for development.
"""

from database import init_database, drop_all_tables
from db_helper import add_instructor, add_child, add_attendance_log
from datetime import datetime
import pytz

def seed_database():
    """Populate the database with test data."""

    print("=" * 60)
    print("SEEDING LOCAL DATABASE WITH TEST DATA")
    print("=" * 60)

    # Reset database
    print("\n[1] Dropping existing tables...")
    drop_all_tables()

    print("[2] Initializing fresh database...")
    init_database()

    # Add instructors
    print("\n[3] Adding instructors...")
    instructors = [
        ("admin", "admin123", "Pastor John Doe"),
        ("teacher1", "pass123", "Sister Mary Grace"),
        ("teacher2", "pass456", "Brother Samuel"),
    ]

    for username, password, full_name in instructors:
        if add_instructor(username, password, full_name):
            print(f"  ✓ Added instructor: {full_name} (username: {username})")
        else:
            print(f"  ✗ Failed to add: {full_name}")

    # Add children
    print("\n[4] Adding children...")
    children = [
        ("Emmanuel Adeyemi", "Mr. David Adeyemi", "Tenderfoots", "Lagos", "HQ Ikeja", "Alpha", "+234-803-000-1001"),
        ("Grace Okonkwo", "Mrs. Joy Okonkwo", "Light Troopers", "Abuja", "Abuja Central", "Beta", "+234-803-000-1002"),
        ("Samuel Oluwaseun", "Pastor Michael Oluwaseun", "Tribe of Truth", "Oyo", "Ibadan South", "Gamma", "+234-803-000-1003"),
        ("Blessing Chioma", "Mrs. Faith Chioma", "Tenderfoots", "Rivers", "Port Harcourt", "Delta", "+234-803-000-1004"),
        ("Daniel Afolabi", "Mr. John Afolabi", "Light Troopers", "Ogun", "Abeokuta", "Alpha", "+234-803-000-1005"),
        ("Ruth Adeola", "Mrs. Esther Adeola", "Tribe of Truth", "Kaduna", "Kaduna North", "Beta", "+234-803-000-1006"),
        ("Joseph Okeke", "Mr. Peter Okeke", "Tenderfoots", "Lagos", "HQ Ikeja", "Gamma", "+234-803-000-1007"),
        ("Deborah Nnamdi", "Mrs. Grace Nnamdi", "Light Troopers", "Abuja", "Abuja Central", "Delta", "+234-803-000-1008"),
        ("Joshua Benson", "Mr. Benson Eze", "Tribe of Truth", "Rivers", "Port Harcourt", "Alpha", "+234-803-000-1009"),
        ("Sarah Williams", "Mrs. Helen Williams", "Tenderfoots", "Oyo", "Ibadan South", "Beta", "+234-803-000-1010"),
    ]

    for child_name, guardian, class_type, state, church_location, camp_group, guardian_phone in children:
        if add_child(child_name, guardian, class_type,
                     state=state,
                     church_location=church_location,
                     camp_group=camp_group,
                     guardian_phone=guardian_phone):
            print(f"  ✓ Added child: {child_name} ({class_type})")
        else:
            print(f"  ✗ Failed to add: {child_name}")

    # Add sample attendance logs
    print("\n[5] Adding sample attendance logs...")
    NIGERIA_TZ = pytz.timezone('Africa/Lagos')
    today = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d")

    event_id = "rebootcamp"
    event_name = "RebootCamp"
    sample_logs = [
        (today, "Emmanuel Adeyemi", "Day 1 Morning Session", "Morning", "day1-morning", "1", "08:05 AM", "Lagos", "HQ Ikeja", "Alpha"),
        (today, "Grace Okonkwo", "Day 1 Morning Session", "Morning", "day1-morning", "2", "08:15 AM", "Abuja", "Abuja Central", "Beta"),
        (today, "Samuel Oluwaseun", "Day 1 Morning Session", "Morning", "day1-morning", "3", "08:20 AM", "Oyo", "Ibadan South", "Gamma"),
        (today, "Blessing Chioma", "Day 1 Afternoon Session", "Afternoon", "day1-afternoon", "4", "13:05 PM", "Rivers", "Port Harcourt", "Delta"),
        (today, "Daniel Afolabi", "Day 1 Afternoon Session", "Afternoon", "day1-afternoon", "5", "13:15 PM", "Ogun", "Abeokuta", "Alpha"),
    ]

    for date, child, session_label, session_period, session_id, tag, time, state, church_location, camp_group in sample_logs:
        add_attendance_log(
            date,
            child,
            session_label,
            tag,
            time,
            event_id=event_id,
            event_name=event_name,
            session_id=session_id,
            session_label=session_label,
            session_period=session_period,
            state=state,
            church_location=church_location,
            camp_group=camp_group,
        )
        print(f"  ✓ Logged: {child} - Tag #{tag} - {session_label} at {time}")

    print("\n" + "=" * 60)
    print("DATABASE SEEDING COMPLETE!")
    print("=" * 60)
    print("\nTest Login Credentials:")
    print("  Username: admin")
    print("  Password: admin123")
    print("\nOther test accounts:")
    print("  teacher1 / pass123")
    print("  teacher2 / pass456")
    print("=" * 60)

if __name__ == "__main__":
    seed_database()
