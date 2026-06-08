"""
Database connection and schema initialisation for the H2GV UX Questionnaire web app.
Uses pyodbc to connect to a local SQL Server instance.
"""

import pyodbc
import os

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

SERVER   = os.environ.get("DB_SERVER", "localhost")
DATABASE = os.environ.get("DB_NAME", "H2GV_UX")
DRIVER   = "{ODBC Driver 17 for SQL Server}"


def get_connection(database: str = DATABASE) -> pyodbc.Connection:
    """Return a new autocommit pyodbc connection to the given database."""
    conn_str = (
        f"DRIVER={DRIVER};"
        f"SERVER={SERVER};"
        f"DATABASE={database};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, autocommit=True)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

# Each schema statement is sent to SQL Server individually (no fragile
# splitting on ";", which broke when statement bodies contained commas).
SCHEMA_STATEMENTS = [
    # Participants table: one row per unique person
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'participants')
    CREATE TABLE participants (
        participant_id   NVARCHAR(10)  PRIMARY KEY,   -- e.g. P001
        full_name        NVARCHAR(200) NOT NULL,
        is_stub          BIT NOT NULL DEFAULT 1,      -- 1 = name-only; 0 = Section A complete
        age              INT,
        gender           NVARCHAR(50),
        prev_gas_heater  NVARCHAR(20),                -- Yes / No / Do not know
        home_heating     NVARCHAR(100),
        gas_fuel         NVARCHAR(50),
        showers_per_day  NVARCHAR(50),
        shower_duration  NVARCHAR(50),
        h2_familiarity   INT                          -- 1-5
    )
    """,
    # Tests table: one row per test session
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'tests')
    CREATE TABLE tests (
        test_id          NVARCHAR(20)  PRIMARY KEY,   -- auto: P001_20260607_143000
        participant_id   NVARCHAR(10)  NOT NULL REFERENCES participants(participant_id),
        test_date        DATE          NOT NULL,
        start_time       TIME,
        end_time         TIME,
        temp_setting     FLOAT,
        operator_name    NVARCHAR(100),
        comments         NVARCHAR(MAX),
        created_at       DATETIME2 DEFAULT GETDATE()
    )
    """,
    # Responses table: one row per test session (B + C + D sections)
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'responses')
    CREATE TABLE responses (
        response_id      INT IDENTITY(1,1) PRIMARY KEY,
        test_id          NVARCHAR(20)  NOT NULL REFERENCES tests(test_id),
        -- Section B
        b1_temp_setting  FLOAT,
        b2_hot_water_speed      INT,
        b3_temp_control         INT,
        b4_temp_stability       INT,
        b5_temp_after_pause     INT,
        b5_not_applicable       BIT DEFAULT 0,
        b6_overall_satisfaction INT,
        b7_comparison           INT,
        b8_daily_use            INT,
        -- Section C
        c1_comfort              INT,
        c2_met_expectations     INT,
        c3_reliability          INT,
        c4_confidence           INT,
        c5_would_install        INT,
        -- Section D (optional)
        d1_liked_most    NVARCHAR(MAX),
        d2_improvements  NVARCHAR(MAX),
        d3_comments      NVARCHAR(MAX),
        submitted_at     DATETIME2 DEFAULT GETDATE()
    )
    """,
    # Migration: add is_stub to participants tables that predate this column
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('participants') AND name = 'is_stub'
    )
    ALTER TABLE participants ADD is_stub BIT NOT NULL DEFAULT 0
    """,
]


def init_db():
    """Create the database and tables if they do not exist yet."""
    # Connect to master to create the database if needed
    conn = get_connection(database="master")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sys.databases WHERE name = ?", (DATABASE,))
    if cursor.fetchone() is None:
        cursor.execute(f"CREATE DATABASE [{DATABASE}]")
    conn.close()

    # Now create tables inside the target database, one statement at a time.
    conn = get_connection()
    cursor = conn.cursor()
    for stmt in SCHEMA_STATEMENTS:
        cursor.execute(stmt)
    conn.close()


# ---------------------------------------------------------------------------
# Participant helpers
# ---------------------------------------------------------------------------

def get_participant_by_name(full_name: str):
    """Return participant row dict if name exists, else None."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM participants WHERE LOWER(full_name) = LOWER(?)",
        (full_name.strip(),)
    )
    row = cursor.fetchone()
    cols = [d[0] for d in cursor.description] if row else []
    conn.close()
    return dict(zip(cols, row)) if row else None


def get_participant_by_id(participant_id: str):
    """Return participant row dict by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM participants WHERE participant_id = ?", (participant_id,))
    row = cursor.fetchone()
    cols = [d[0] for d in cursor.description] if row else []
    conn.close()
    return dict(zip(cols, row)) if row else None


def generate_participant_id() -> str:
    """
    Generate the next sequential participant ID (P001, P002, …).

    Derives the next number from the MAX existing numeric suffix rather than a
    row count, so deleting a participant in the middle never causes the next ID
    to collide with an ID that is still in use.
    """
    conn = get_connection()
    cursor = conn.cursor()
    # Strip the leading 'P', cast the rest to int, take the max. NULL if table empty.
    cursor.execute(
        "SELECT MAX(CAST(SUBSTRING(participant_id, 2, 10) AS INT)) FROM participants"
    )
    max_num = cursor.fetchone()[0]
    conn.close()
    next_num = (max_num or 0) + 1
    return f"P{next_num:03d}"


def create_participant_stub(full_name: str) -> str:
    """
    Create a name-only participant stub (operator pre-registration).
    is_stub=1 signals that Section A demographics have not yet been collected.
    Returns the new participant_id.
    """
    pid = generate_participant_id()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO participants (participant_id, full_name, is_stub) VALUES (?,?,1)",
        (pid, full_name.strip())
    )
    conn.close()
    return pid


def create_participant(data: dict) -> str:
    """
    Insert a fully-complete participant row (participant fills Section A themselves).
    is_stub=0 because demographics are included.
    Returns the new participant_id.
    """
    pid = generate_participant_id()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO participants
           (participant_id, full_name, is_stub, age, gender, prev_gas_heater,
            home_heating, gas_fuel, showers_per_day, shower_duration, h2_familiarity)
           VALUES (?,?,0,?,?,?,?,?,?,?,?)""",
        (pid,
         data.get("full_name"),
         data.get("age"),
         data.get("gender"),
         data.get("prev_gas_heater"),
         data.get("home_heating"),
         data.get("gas_fuel"),
         data.get("showers_per_day"),
         data.get("shower_duration"),
         data.get("h2_familiarity"))
    )
    conn.close()
    return pid


def complete_participant(participant_id: str, data: dict):
    """
    Fill in Section A demographics on a stub participant and clear the stub flag.
    Called when a participant whose record was operator-created now fills Section A.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE participants SET
            is_stub         = 0,
            age             = ?,
            gender          = ?,
            prev_gas_heater = ?,
            home_heating    = ?,
            gas_fuel        = ?,
            showers_per_day = ?,
            shower_duration = ?,
            h2_familiarity  = ?
           WHERE participant_id = ?""",
        (data.get("age"),
         data.get("gender"),
         data.get("prev_gas_heater"),
         data.get("home_heating"),
         data.get("gas_fuel"),
         data.get("showers_per_day"),
         data.get("shower_duration"),
         data.get("h2_familiarity"),
         participant_id)
    )
    conn.close()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _time_to_minutes(value) -> int | None:
    """
    Convert a 'HH:MM' string or a datetime.time to minutes since midnight.
    Returns None if the value is missing or unparseable. Used to measure how
    close two session times are when matching a participant to an operator log.
    """
    if value is None:
        return None
    text = str(value)
    parts = text.split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        return hours * 60 + minutes
    except (ValueError, IndexError):
        return None


def generate_test_id(participant_id: str, test_date: str, seq: int) -> str:
    """
    Build a test_id from participant + date + per-day sequence.
    e.g. P001_20260607_01. Time is deliberately NOT part of the id, because the
    participant and the operator never agree on an exact time — the link between
    them is made by closest start_time instead (see match_or_create_test).
    """
    date_part = test_date.replace("-", "")
    return f"{participant_id}_{date_part}_{seq:02d}"


def _next_test_seq(cursor, participant_id: str, test_date: str) -> int:
    """Return the next free per-day sequence number for this participant+date."""
    prefix = f"{participant_id}_{test_date.replace('-', '')}_"
    cursor.execute(
        "SELECT MAX(CAST(SUBSTRING(test_id, LEN(?) + 1, 10) AS INT)) "
        "FROM tests WHERE test_id LIKE ?",
        (prefix, prefix + "%")
    )
    max_seq = cursor.fetchone()[0]
    return (max_seq or 0) + 1


def test_exists(test_id: str) -> bool:
    """Return True if a test row with this test_id already exists."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM tests WHERE test_id = ?", (test_id,))
    found = cursor.fetchone() is not None
    conn.close()
    return found


def create_test(data: dict) -> str:
    """
    Insert a brand-new test row with the next per-day sequence number.
    Used by the operator panel (Log Test Session) to create a session that a
    participant submission will later attach to via match_or_create_test.
    Returns the new test_id.
    """
    conn = get_connection()
    cursor = conn.cursor()
    seq = _next_test_seq(cursor, data["participant_id"], data["test_date"])
    test_id = generate_test_id(data["participant_id"], data["test_date"], seq)
    cursor.execute(
        """INSERT INTO tests
           (test_id, participant_id, test_date, start_time, end_time,
            temp_setting, operator_name, comments)
           VALUES (?,?,?,?,?,?,?,?)""",
        (test_id,
         data["participant_id"],
         data["test_date"],
         data.get("start_time"),
         data.get("end_time"),
         data.get("temp_setting"),
         data.get("operator_name"),
         data.get("comments"))
    )
    conn.close()
    return test_id


def match_or_create_test(data: dict) -> str:
    """
    Find the operator-logged session this participant submission belongs to, or
    create a pending one if the operator has not logged it yet.

    Matching rule (per the study's workflow):
      * Look at the participant's tests on the same date that DON'T yet have a
        response (i.e. are still waiting to be filled in).
      * Pick the one whose start_time is CLOSEST to the participant's stated
        shower time.
      * If there are no unanswered sessions for that date, create a new pending
        test row carrying the participant's shower time as start_time, so the
        operator can complete the metadata later. Nothing is lost.

    Returns the test_id the response should be written to.
    """
    participant_id = data["participant_id"]
    test_date      = data["test_date"]
    shower_minutes = _time_to_minutes(data.get("start_time"))

    conn = get_connection()
    cursor = conn.cursor()

    # Candidate sessions: same participant + date, with no response attached yet.
    cursor.execute(
        """SELECT t.test_id, t.start_time
           FROM tests t
           WHERE t.participant_id = ?
             AND t.test_date = ?
             AND NOT EXISTS (SELECT 1 FROM responses r WHERE r.test_id = t.test_id)""",
        (participant_id, test_date)
    )
    candidates = cursor.fetchall()

    best_id = None
    if candidates:
        if shower_minutes is None:
            # Participant gave no time — just take the first unanswered session.
            best_id = candidates[0][0]
        else:
            # Pick the candidate whose start_time is nearest the shower time.
            # Sessions with no start_time sort last (treated as "infinitely far").
            def distance(row):
                cand_minutes = _time_to_minutes(row[1])
                if cand_minutes is None:
                    return (1, 0)
                return (0, abs(cand_minutes - shower_minutes))
            best_id = min(candidates, key=distance)[0]

    if best_id is not None:
        conn.close()
        return best_id

    # No unanswered session for this date — create a pending one.
    seq = _next_test_seq(cursor, participant_id, test_date)
    test_id = generate_test_id(participant_id, test_date, seq)
    cursor.execute(
        """INSERT INTO tests
           (test_id, participant_id, test_date, start_time)
           VALUES (?,?,?,?)""",
        (test_id, participant_id, test_date, data.get("start_time"))
    )
    conn.close()
    return test_id


def update_test(test_id: str, data: dict):
    """Update mutable fields on an existing test row (operator fills in later)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE tests SET
           start_time    = COALESCE(?, start_time),
           end_time      = COALESCE(?, end_time),
           temp_setting  = COALESCE(?, temp_setting),
           operator_name = COALESCE(?, operator_name),
           comments      = COALESCE(?, comments)
           WHERE test_id = ?""",
        (data.get("start_time"),
         data.get("end_time"),
         data.get("temp_setting"),
         data.get("operator_name"),
         data.get("comments"),
         test_id)
    )
    conn.close()


def get_test(test_id: str):
    """Return test row dict."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tests WHERE test_id = ?", (test_id,))
    row = cursor.fetchone()
    cols = [d[0] for d in cursor.description] if row else []
    conn.close()
    return dict(zip(cols, row)) if row else None


def list_tests_for_participant(participant_id: str):
    """Return list of test dicts for a given participant."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM tests WHERE participant_id = ? ORDER BY created_at DESC",
        (participant_id,)
    )
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def create_response(data: dict):
    """
    Insert or replace the response row linked to a test.

    A test session has exactly one response set. If the participant re-submits
    (e.g. browser back + resubmit, or an operator-first stub that the participant
    then completes), we overwrite the existing answers rather than creating a
    duplicate row for the same test_id.
    """
    test_id = data["test_id"]

    conn = get_connection()
    cursor = conn.cursor()

    # One response per test: clear any prior answers for this test first.
    cursor.execute("DELETE FROM responses WHERE test_id = ?", (test_id,))

    cursor.execute(
        """INSERT INTO responses
           (test_id,
            b1_temp_setting, b2_hot_water_speed, b3_temp_control, b4_temp_stability,
            b5_temp_after_pause, b5_not_applicable, b6_overall_satisfaction,
            b7_comparison, b8_daily_use,
            c1_comfort, c2_met_expectations, c3_reliability, c4_confidence, c5_would_install,
            d1_liked_most, d2_improvements, d3_comments)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (test_id,
         data.get("b1_temp_setting"),
         data.get("b2_hot_water_speed"),
         data.get("b3_temp_control"),
         data.get("b4_temp_stability"),
         data.get("b5_temp_after_pause"),
         1 if data.get("b5_not_applicable") else 0,
         data.get("b6_overall_satisfaction"),
         data.get("b7_comparison"),
         data.get("b8_daily_use"),
         data.get("c1_comfort"),
         data.get("c2_met_expectations"),
         data.get("c3_reliability"),
         data.get("c4_confidence"),
         data.get("c5_would_install"),
         data.get("d1_liked_most"),
         data.get("d2_improvements"),
         data.get("d3_comments"))
    )
    conn.close()


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_all_to_csv() -> list:
    """Return all data as a list of dicts (participants + tests + responses joined)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            t.test_id, t.participant_id,
            t.test_date, t.start_time, t.end_time,
            t.temp_setting AS operator_temp_setting,
            t.comments AS operator_comments,
            p.age, p.gender, p.prev_gas_heater, p.home_heating,
            p.gas_fuel, p.showers_per_day, p.shower_duration, p.h2_familiarity,
            r.b1_temp_setting, r.b2_hot_water_speed, r.b3_temp_control,
            r.b4_temp_stability, r.b5_temp_after_pause, r.b5_not_applicable,
            r.b6_overall_satisfaction, r.b7_comparison, r.b8_daily_use,
            r.c1_comfort, r.c2_met_expectations, r.c3_reliability,
            r.c4_confidence, r.c5_would_install,
            r.d1_liked_most, r.d2_improvements, r.d3_comments,
            r.submitted_at
        FROM tests t
        JOIN participants p ON t.participant_id = p.participant_id
        LEFT JOIN responses r ON t.test_id = r.test_id
        ORDER BY t.created_at
    """)
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]
