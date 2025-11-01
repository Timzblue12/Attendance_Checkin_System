# 📚 CelebKids Egbeda Attendance System

A simple, elegant, and reliable **attendance tracking system** built with **Flask + Google Sheets**.  
Designed for sunday to sunday use, this project makes it easy to **check in, check out, tagging of kids every sunday at CCI Egbeda branch, and manage attendance** while keeping all data safe in Google Sheets.

---

## 🎯 Aim of the Project
The goal of this project is to:
- ✅ Simplify attendance logging for CCI celebkids **and camp events like RebootCamp**.
- ✅ Assign and track **daily tag numbers** for each child or group.
- ✅ Capture state, church location, and guardian contact for every attendee.
- ✅ Provide a **real-time dashboard** with session-level insights.
- ✅ Make reports easy to generate and filter (by date, session, state, class, tag).
- ✅ Keep everything cloud-based with **Google Sheets** while buffering offline entries locally.

---

## ⚡ Features
- 🔑 Secure instructor login system.
- 👧👦 Register and manage children with expanded details (guardian, class, state, church location, notes).
- 🏷️ **Daily tag assignment** for quick check-ins and check-outs.
- ⏰ Logs check-in and check-out times automatically.
- 📊 Dashboard showing attendance breakdown by:
  - Session period (Morning / Afternoon / Evening)
  - Class type (Tenderfoots, Light Troopers, Tribe of Truth)
- 📑 Reports with flexible filters (event, date, session, period, state, church location, class, tag).
- 🗑️ Ability to delete incorrect log entries.
- ☁️ Powered by **Google Sheets** (no extra database required) **with an offline-first queue** so check-ins are never lost.
- 🔁 Automatic background sync pushes pending check-ins once internet returns.

---

## 🛠️ Technologies Used
- **[Python 3](https://www.python.org/)** – backend logic
- **[Flask](https://flask.palletsprojects.com/)** – web framework
- **[gspread](https://github.com/burnash/gspread)** – Google Sheets API client
- **[google-auth](https://google-auth.readthedocs.io/)** – secure Google API authentication
- **HTML5 + Jinja2** – templating
- **CSS** – simple, responsive design

---

## 🚀 How It Works
1. Instructors **log in** to the system.
2. Children are **checked in** using their daily tag number.
3. Attendance data is stored in **Google Sheets**.
4. Instructors can **check out children** using the same tag.
5. Dashboard + reports give instant insights into attendance.

---

## 📷 Screenshots
**

---

## 📦 Installation & Setup
1. Clone this repository.
2. Create a virtual environment and activate it.
3. Install dependencies: `pip install -r requirements.txt`
4. Seed the local SQLite database (optional but recommended): `python seed_data.py`
5. Run locally with SQLite cache: `LOCAL_DEV=true python app.py`
   - Omit `LOCAL_DEV=true` to talk directly to Google Sheets.
6. Browse to `http://127.0.0.1:5000` and log in with `admin / admin123` (see `LOCAL_DEVELOPMENT.md` for more test users).
