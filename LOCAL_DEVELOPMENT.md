# Local Development Guide

This app now supports **two modes**:
- 🔧 **Local Development Mode** (SQLite database)
- ☁️ **Production Mode** (Google Sheets)

It also ships with a RebootCamp configuration so you can rehearse multi-session camp check-ins without touching production.

## Quick Start: Local Development

### 1. Seed the Database (First Time Only)
```bash
source venv/bin/activate
python seed_data.py
```

### 2. Run in Local Mode
```bash
source venv/bin/activate
LOCAL_DEV=true python app.py
```

### 3. Access the App
Open browser: **http://127.0.0.1:5000**

### 4. Login with Test Credentials
- **Username**: `admin`
- **Password**: `admin123`

Other test accounts:
- `teacher1` / `pass123`
- `teacher2` / `pass456`

---

## Running in Production Mode (Google Sheets)

```bash
source venv/bin/activate
python app.py
```
*No environment variable needed - defaults to Google Sheets*

---

## Environment Variable

The app checks the `LOCAL_DEV` environment variable:
- `LOCAL_DEV=true` → Uses SQLite (local development)
- `LOCAL_DEV=false` or not set → Uses Google Sheets (production)

---

## Test Data Included

When you seed the database, you get:
- ✅ 3 instructors
- ✅ 10 children with state, church location, and guardian phone metadata
- ✅ RebootCamp sample sessions (Morning/Afternoon) tied to `rebootcamp`
- ✅ 5 sample attendance records mapped to the morning/afternoon sessions

---

## Resetting Local Database

To start fresh:
```bash
python seed_data.py
```
This will drop all tables and recreate them with fresh test data.

---

## Files Created

- `database.py` - Database schema and initialization
- `db_helper.py` - Database helper functions (mirrors Google Sheets interface)
- `seed_data.py` - Script to populate test data
- `rebootcamp_config.json` - Event/session catalog for RebootCamp (edit to match your schedule)
- `attendance_local.db` - Local SQLite database file (gitignored)
- `app.py` - Modified to support both modes

---

## RebootCamp Configuration

Edit `rebootcamp_config.json` to customise the camp:

- **events** → add/update event blocks (`id`, `name`, `start_date`, `end_date`, `location`).
- **sessions** → list every session with `id`, `label`, `date`, `period`, `start_time`, `end_time`.
- **states / church_locations** → control the dropdowns surfaced during check-in.

Reload the Flask app after editing the file so the new sessions and dropdown options appear.

---

## Using the RebootCamp Flow Locally

1. Choose the event + session context at the top of the Attendance page.
2. Pick a child — their state, church location, guardian name/phone, and saved notes populate automatically.
3. Confirm/override the metadata, assign a tag, optionally add notes, then submit.
4. Checkout by tag uses the same event/session context so you can clear the exact bus or session you’re supervising.

All check-ins save the camp metadata into SQLite immediately. When you run in production mode the same data is queued locally and synced to Google Sheets once the network is back.

---

## Reports & Dashboard Refresh

- Dashboard now shows session (Morning/Afternoon/Evening) counts and can be filtered by event.
- Reports page adds filters for event, session, session period, state, church location, class, and tag. Results group by date + session so you can print roll calls for each block.

---

## Offline Sync Tips

- If the Google Sheets call fails, the check-in/out is stored locally with a “Pending Sync” badge.
- Returning to the Attendance page (or any successful sync) flushes the queue automatically.
- Use the yellow flash messages as a prompt to reconnect before the queue grows too large.

---

## Benefits of Local Development

✅ **No API calls** - Faster than Google Sheets
✅ **Safe testing** - Won't affect production data
✅ **Easy reset** - Run seed script anytime
✅ **Offline work** - No internet needed
✅ **Same code** - Production code works identically

---

## Production Deployment

For **PythonAnywhere** or other platforms:
1. Don't set `LOCAL_DEV` environment variable
2. Ensure `credentials.json` is uploaded
3. App will automatically use Google Sheets

---

## Troubleshooting

**Q: Login not working in local mode?**
A: Run `python seed_data.py` to ensure database is seeded.

**Q: Want to switch back to Google Sheets locally?**
A: Just run without the environment variable: `python app.py`

**Q: Need to add more test data?**
A: Edit `seed_data.py` and run it again.
