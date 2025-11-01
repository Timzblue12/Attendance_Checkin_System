import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from database import DB_PATH, get_connection, init_database


_DB_READY = False


def ensure_database_ready() -> None:
    """Ensure the SQLite database exists and has the latest schema."""
    global _DB_READY
    if _DB_READY:
        return

    init_database()
    _DB_READY = True


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def add_pending_check_in(date: str, child_name: str, service: str, day_tag: str,
                         check_in_time: str, details: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, str]:
    """Persist a check-in locally and enqueue it for remote sync."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()

    details = details or {}
    event_id = details.get("event_id")
    event_name = details.get("event_name")
    session_id = details.get("session_id")
    session_label = details.get("session_label") or service
    session_period = details.get("session_period")
    state = details.get("state")
    church_location = details.get("church_location")
    camp_group = details.get("camp_group", "")
    notes = details.get("notes")

    sync_uuid = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO attendance_log
        (date, child_name, service, day_tag, check_in_time, check_out_time, status,
         event_id, event_name, session_id, session_label, session_period,
         state, church_location, camp_group, notes,
         sync_status, synced_at, sync_uuid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (date, child_name, service, day_tag, check_in_time, "", "Checked-In",
         event_id, event_name, session_id, session_label, session_period,
         state, church_location, camp_group, notes,
         "pending", None, sync_uuid)
    )

    attendance_id = cursor.lastrowid
    payload = {
        "attendance_id": attendance_id,
        "date": date,
        "child_name": child_name,
        "service": service,
        "day_tag": day_tag,
        "check_in_time": check_in_time,
        "sync_uuid": sync_uuid,
        "event_id": event_id,
        "event_name": event_name,
        "session_id": session_id,
        "session_label": session_label,
        "session_period": session_period,
        "state": state,
        "church_location": church_location,
        "camp_group": camp_group,
        "notes": notes,
    }

    now = _utc_now()
    cursor.execute(
        """
        INSERT INTO sync_queue
        (record_type, record_id, operation, payload, status, attempts, last_error,
         last_attempt_at, sync_uuid, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'pending', 0, NULL, NULL, ?, ?, ?)
        """,
        ("attendance_log", attendance_id, "check_in", json.dumps(payload), sync_uuid, now, now)
    )

    queue_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "id": attendance_id,
        "Date": date,
        "Child Name": child_name,
        "Service": service,
        "Day Tag": day_tag,
        "Check-in Time": check_in_time,
        "Check-out Time": "",
        "Status": "Checked-In",
        "row_id": attendance_id,
        "sync_status": "pending",
        "sync_uuid": sync_uuid,
        "queue_id": queue_id,
        "Event ID": event_id,
        "Event Name": event_name,
        "Session ID": session_id,
        "Session Label": session_label,
        "Session Period": session_period,
        "State": state,
        "Church Location": church_location,
        "Camp Group": camp_group,
        "Notes": notes,
    }


def record_shadow_check_in(date: str, child_name: str, service: str, day_tag: str,
                           check_in_time: str, *, sync_uuid: Optional[str] = None,
                           details: Optional[Dict[str, Optional[str]]] = None) -> int:
    """Persist a copy of a remotely-synced check-in for offline visibility."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()

    sync_uuid = sync_uuid or str(uuid.uuid4())
    details = details or {}
    event_id = details.get("event_id")
    event_name = details.get("event_name")
    session_id = details.get("session_id")
    session_label = details.get("session_label") or service
    session_period = details.get("session_period")
    state = details.get("state")
    church_location = details.get("church_location")
    camp_group = details.get("camp_group", "")
    notes = details.get("notes")
    cursor.execute(
        """
        INSERT INTO attendance_log
        (date, child_name, service, day_tag, check_in_time, check_out_time, status,
         event_id, event_name, session_id, session_label, session_period,
         state, church_location, camp_group, notes,
         sync_status, synced_at, sync_uuid)
        VALUES (?, ?, ?, ?, ?, ?, 'Checked-In', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced', ?, ?)
        """,
        (date, child_name, service, day_tag, check_in_time, "",
         event_id, event_name, session_id, session_label, session_period,
         state, church_location, camp_group, notes,
         _utc_now(), sync_uuid)
    )

    attendance_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return attendance_id


def add_pending_checkout(date: str, day_tag: str, checkout_time: str) -> Dict[str, List[str]]:
    """Persist a checkout event locally and enqueue it for remote sync."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, child_name FROM attendance_log
        WHERE date = ? AND day_tag = ? AND status = 'Checked-In'
        """,
        (date, day_tag)
    )
    rows = cursor.fetchall()
    attendance_ids = [row["id"] for row in rows]
    child_names = [row["child_name"] for row in rows]

    # Update local records to reflect checkout even if sync is pending.
    if attendance_ids:
        cursor.execute(
            """
            UPDATE attendance_log
            SET check_out_time = ?, status = 'Checked-Out', sync_status = 'pending', synced_at = NULL
            WHERE id IN ({})
            """.format(
                ",".join("?" for _ in attendance_ids)
            ),
            [checkout_time, *attendance_ids]
        )

    payload = {
        "attendance_ids": attendance_ids,
        "date": date,
        "day_tag": day_tag,
        "checkout_time": checkout_time,
        "child_names": child_names,
    }

    sync_uuid = str(uuid.uuid4())
    now = _utc_now()
    cursor.execute(
        """
        INSERT INTO sync_queue
        (record_type, record_id, operation, payload, status, attempts, last_error,
         last_attempt_at, sync_uuid, created_at, updated_at)
        VALUES (?, NULL, ?, ?, 'pending', 0, NULL, NULL, ?, ?, ?)
        """,
        ("attendance_log", "checkout", json.dumps(payload), sync_uuid, now, now)
    )

    queue_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "attendance_ids": attendance_ids,
        "child_names": child_names,
        "sync_uuid": sync_uuid,
        "queue_id": queue_id,
    }


def record_shadow_checkout(date: str, day_tag: str, checkout_time: str) -> None:
    """Update local copies when a checkout succeeds remotely."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE attendance_log
        SET check_out_time = ?, status = 'Checked-Out', sync_status = 'synced', synced_at = ?
        WHERE date = ? AND day_tag = ? AND status = 'Checked-In'
        """,
        (checkout_time, _utc_now(), date, day_tag)
    )
    conn.commit()
    conn.close()


def get_pending_attendance(date: Optional[str] = None) -> List[Dict[str, str]]:
    """Return unsynced attendance rows for display while offline."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()

    base_query = (
        """
        SELECT id, date, child_name, service, day_tag, check_in_time, check_out_time,
               status, sync_status, sync_uuid,
               event_id, event_name, session_id, session_label, session_period,
               state, church_location, camp_group, notes
        FROM attendance_log
        WHERE sync_status != 'synced'
        """
    )
    params: List[str] = []
    if date:
        base_query += " AND date = ?"
        params.append(date)

    base_query += " ORDER BY date DESC, check_in_time DESC"
    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    conn.close()

    pending_records: List[Dict[str, str]] = []
    for row in rows:
        record = {
            "id": row["id"],
            "Date": row["date"],
            "Child Name": row["child_name"],
            "Service": row["service"],
            "Day Tag": row["day_tag"],
            "Check-in Time": row["check_in_time"],
            "Check-out Time": row["check_out_time"],
            "Status": row["status"],
            "row_id": row["id"],
            "sync_status": row["sync_status"],
            "sync_uuid": row["sync_uuid"],
            "data_source": "local",
            "Event ID": row["event_id"],
            "Event Name": row["event_name"],
            "Session ID": row["session_id"],
            "Session Label": row["session_label"],
            "Session Period": row["session_period"],
            "State": row["state"],
            "Church Location": row["church_location"],
            "Camp Group": row["camp_group"],
            "Notes": row["notes"],
        }
        pending_records.append(record)

    return pending_records


def fetch_pending_queue(limit: int = 10) -> List[Dict[str, str]]:
    """Fetch pending sync jobs ordered by creation time."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, record_type, record_id, operation, payload, status, attempts,
               last_error, last_attempt_at, sync_uuid
        FROM sync_queue
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "record_type": row["record_type"],
            "record_id": row["record_id"],
            "operation": row["operation"],
            "payload": row["payload"],
            "status": row["status"],
            "attempts": row["attempts"],
            "last_error": row["last_error"],
            "last_attempt_at": row["last_attempt_at"],
            "sync_uuid": row["sync_uuid"],
        })

    return result


def record_sync_attempt(queue_id: int) -> None:
    ensure_database_ready()
    now = _utc_now()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sync_queue
        SET attempts = attempts + 1, last_attempt_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, queue_id)
    )
    conn.commit()
    conn.close()


def mark_queue_item_synced(queue_id: int) -> None:
    ensure_database_ready()
    now = _utc_now()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sync_queue
        SET status = 'synced', updated_at = ?, last_error = NULL
        WHERE id = ?
        """,
        (now, queue_id)
    )
    conn.commit()
    conn.close()


def mark_queue_item_failed(queue_id: int, error_message: str) -> None:
    ensure_database_ready()
    now = _utc_now()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sync_queue
        SET status = 'failed', last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (error_message[:500], now, queue_id)
    )
    conn.commit()
    conn.close()


def update_queue_error(queue_id: int, error_message: str) -> None:
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sync_queue
        SET last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (error_message[:500], _utc_now(), queue_id)
    )
    conn.commit()
    conn.close()


def mark_attendance_synced(attendance_id: int) -> None:
    ensure_database_ready()
    now = _utc_now()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE attendance_log
        SET sync_status = 'synced', synced_at = ?
        WHERE id = ?
        """,
        (now, attendance_id)
    )
    conn.commit()
    conn.close()


def mark_attendance_failed(attendance_id: int) -> None:
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE attendance_log
        SET sync_status = 'failed', synced_at = NULL
        WHERE id = ?
        """,
        (attendance_id,)
    )
    conn.commit()
    conn.close()


def reset_failed_queue_items() -> None:
    """Move failed items back to pending for another retry."""
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sync_queue
        SET status = 'pending', updated_at = ?, last_error = NULL
        WHERE status = 'failed'
        """,
        (_utc_now(),)
    )
    conn.commit()
    conn.close()


def get_queue_item_by_uuid(sync_uuid: str) -> Optional[Dict[str, str]]:
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, record_type, record_id, operation, payload, status, attempts,
               last_error, last_attempt_at, sync_uuid
        FROM sync_queue
        WHERE sync_uuid = ?
        """,
        (sync_uuid,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "record_type": row["record_type"],
        "record_id": row["record_id"],
        "operation": row["operation"],
        "payload": row["payload"],
        "status": row["status"],
        "attempts": row["attempts"],
        "last_error": row["last_error"],
        "last_attempt_at": row["last_attempt_at"],
        "sync_uuid": row["sync_uuid"],
    }


def get_attendance_record(attendance_id: int) -> Optional[Dict[str, str]]:
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, date, child_name, service, day_tag, check_in_time, check_out_time,
               status, sync_status, sync_uuid,
               event_id, event_name, session_id, session_label, session_period,
               state, church_location, camp_group, notes
        FROM attendance_log
        WHERE id = ?
        """,
        (attendance_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "date": row["date"],
        "child_name": row["child_name"],
        "service": row["service"],
        "day_tag": row["day_tag"],
        "check_in_time": row["check_in_time"],
        "check_out_time": row["check_out_time"],
        "status": row["status"],
        "sync_status": row["sync_status"],
        "sync_uuid": row["sync_uuid"],
        "event_id": row["event_id"],
        "event_name": row["event_name"],
        "session_id": row["session_id"],
        "session_label": row["session_label"],
        "session_period": row["session_period"],
        "state": row["state"],
        "church_location": row["church_location"],
        "camp_group": row["camp_group"],
        "notes": row["notes"],
    }


def delete_local_attendance(attendance_id: int) -> None:
    ensure_database_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sync_queue WHERE record_id = ? AND status != 'synced'", (attendance_id,))
    cursor.execute("DELETE FROM attendance_log WHERE id = ? AND sync_status != 'synced'", (attendance_id,))
    conn.commit()
    conn.close()
