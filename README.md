# 📚 CelebKids Egbeda Attendance System

A simple, elegant, and reliable **attendance tracking system** built with **Flask + Google Sheets**.  
Designed for sunday to sunday use, this project makes it easy to **check in, check out, tagging of kids every sunday at CCI Egbeda branch, and manage attendance** while keeping all data safe in Google Sheets.

---

## 🎯 Aim of the Project
The goal of this project is to:
- ✅ Simplify attendance logging for CCI celebkids.
- ✅ Assign and track **daily tag numbers** for each child.
- ✅ Allow multiple children to share a tag for group check-ins.
- ✅ Provide a **real-time dashboard** for instructors.
- ✅ Make reports easy to generate and filter (by date, service, class, or tag).
- ✅ Keep everything cloud-based with **Google Sheets** as the database.

---

## ⚡ Features
- 🔑 Secure instructor login system.
- 👧👦 Register and manage children with details like **name, guardian, and class type**.
- 🏷️ **Daily tag assignment** for quick check-ins and check-outs.
- ⏰ Logs check-in and check-out times automatically.
- 📊 Dashboard showing attendance breakdown by:
  - Service (1st / 2nd)
  - Class type (Tenderfoots, Light Troopers, Tribe of Truth)
- 📑 Reports with flexible filters (date, service, class, tag).
- 🗑️ Ability to delete incorrect log entries.
- ☁️ Powered by **Google Sheets** (no extra database required).

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
1. Clone this repository