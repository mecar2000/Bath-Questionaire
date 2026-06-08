# H2 Green Valley – User Experience Questionnaire

Flask web application for collecting participant experience data from the hydrogen-powered water heater demonstrator at HyLab Safety Laboratory.

---

## Requirements

- Python 3.10+
- SQL Server instance (local or networked) with Windows Authentication
- ODBC Driver 17 for SQL Server (or later)

---

## Setup

```bash
cd webapp
pip install -r requirements.txt
python app.py
```

Or double-click `webapp/run.bat` on Windows.

The app runs at **http://localhost:5000** by default.

On first launch `init_db()` creates the `H2GV_UX` database and all tables automatically if they do not exist.

---

## Project structure

```
webapp/
  app.py            # Flask routes
  db.py             # Database layer (pyodbc / SQL Server)
  requirements.txt
  run.bat           # Windows launcher
  static/
    style.css       # NewHTML design system
    layout.js       # Form interactions (scale buttons, radio state, legend toggle)
    hylab-logo.png
    hylab-circle.png
    h2greenvalley.webp
  templates/
    base.html       # Shared header / footer / progress bar
    role.html       # Landing – Participant or Operator
    purpose.html    # Study information
    start.html      # Session info (name, date, shower time)
    section_a.html  # Participant characterisation (once per participant)
    section_b.html  # Performance, safety & comments (Sections B, C, D)
    confirmation.html
    operator_login.html
    operator.html   # Operator panel (search, register, log session, export)
NewHTML/            # Reference static HTML design files
```

---

## Participant flow

1. **Role selection** → Participant
2. **Purpose** page (study information)
3. **Start** – enter name, date, approximate shower time
   - Returning participants skip Section A
4. **Section A** – demographics & background (first visit only)
5. **Sections B / C / D** – performance ratings & comments
6. **Confirmation** – displays Participant ID and Test ID

---

## Operator flow

1. Log in with operator password
2. **Search** participant by name
   - Found → view test sessions, edit metadata
   - Not found → register as new participant (generates ID)
3. **Log test session** (Section 0.1) – record start/end time, temperature setting
4. **Export** all data to CSV (anonymised – no names)

---

## Database

SQL Server database `H2GV_UX`, Windows Authentication, `TrustServerCertificate=yes`.

Tables: `participants`, `tests`, `responses`.

Test IDs follow the format `P001_20260608_01` (participant · date · daily sequence).

---

## Notes

- Exported CSV contains only anonymised identifiers (participant ID, test ID) — no names.
- Participants may complete multiple sessions; each generates a new sequenced test row.
- The operator logs session metadata; the participant's shower time is used to match their submission to the nearest operator-logged session on the same date.
