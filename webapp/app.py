"""
Flask web application for the H2GV UX Questionnaire.

Flow:
  1. /                  - Purpose page
  2. /start             - Enter name + date/time (Section 0); detect returning participant
  3. /section-a         - Participant characterisation (skipped for returning participants)
  4. /section-b         - Water heater performance (Sections B + C + D)
  5. /submit            - Save to DB, show confirmation
  6. /operator          - Operator panel: add/update test metadata (Section 0.1)
  7. /export            - Download full CSV
"""

import io
import csv
from datetime import date, datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, flash
)

import db

app = Flask(__name__)
app.secret_key = "h2gv-ux-secret-2026"  # change in production

# Password required to reach the operator panel
OPERATOR_PASSWORD = "H2TheMoon"

# Initialise database on startup
db.init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Page 0 – Role selection (landing)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Landing page: choose Participant or Operator."""
    return render_template("role.html")


# ---------------------------------------------------------------------------
# Page 1 – Purpose (participant entry point)
# ---------------------------------------------------------------------------

@app.route("/purpose")
def purpose():
    """Purpose of the questionnaire — shown to participants before they begin."""
    return render_template("purpose.html")


# ---------------------------------------------------------------------------
# Page 2 – Name + Section 0 (date/time/operator)
# ---------------------------------------------------------------------------

@app.route("/start", methods=["GET", "POST"])
def start():
    """Collect participant name, test date/time and operator name."""
    if request.method == "POST":
        full_name   = request.form.get("full_name", "").strip()
        test_date   = request.form.get("test_date", str(date.today()))
        shower_time = request.form.get("shower_time", "").strip()

        if not full_name:
            flash("Please enter your full name.", "error")
            return redirect(url_for("start"))

        # Check if participant already exists
        participant = db.get_participant_by_name(full_name)

        # Store session data. The participant tells us the time of their shower;
        # this is what links their answers to the operator's logged session (the
        # one with the nearest start_time on the same date). Fall back to "now"
        # only if they left it blank, so matching always has something to work with.
        session["full_name"]   = full_name
        session["test_date"]   = test_date
        session["shower_time"] = shower_time or datetime.now().strftime("%H:%M")

        if participant:
            session["participant_id"] = participant["participant_id"]
            is_stub = bool(participant.get("is_stub", 0))
            if is_stub:
                # Operator pre-registered this person but Section A was never filled.
                # Treat like a new participant: collect demographics first.
                session["returning"] = False
                session["is_stub"]   = True
                return redirect(url_for("section_a"))
            else:
                # Fully returning participant: skip Section A.
                session["returning"] = True
                session["is_stub"]   = False
                return redirect(url_for("section_b"))
        else:
            # Brand new participant: collect demographics.
            session["returning"] = False
            session["is_stub"]   = False
            return redirect(url_for("section_a"))

    # Pre-fill today's date (participant only enters name + date)
    return render_template("start.html", today=str(date.today()))


# ---------------------------------------------------------------------------
# Page 3 – Section A (new participants only)
# ---------------------------------------------------------------------------

@app.route("/section-a", methods=["GET", "POST"])
def section_a():
    """Participant characterisation – only for first-time participants."""
    # If the session was lost (e.g. server restart, or page opened directly),
    # there is no name to attach demographics to — send them back to the start.
    if "full_name" not in session:
        return redirect(url_for("start"))

    if session.get("returning"):
        return redirect(url_for("section_b"))

    if request.method == "POST":
        # Validate required fields
        errors = []
        age    = request.form.get("age", "").strip()
        gender = request.form.get("gender", "").strip()

        if not age:
            errors.append("Age is required.")
        if not gender:
            errors.append("Gender is required.")
        if not request.form.get("prev_gas_heater"):
            errors.append("Question A.4 is required.")
        if not request.form.get("home_heating"):
            errors.append("Question A.5 is required.")
        if not request.form.get("showers_per_day"):
            errors.append("Question A.7 is required.")
        if not request.form.get("shower_duration"):
            errors.append("Question A.8 is required.")
        if not request.form.get("h2_familiarity"):
            errors.append("Question A.9 is required.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("section_a.html", form=request.form)

        # Build participant data
        home_heating = request.form.get("home_heating")
        if home_heating == "Other":
            home_heating = request.form.get("home_heating_other", "Other").strip() or "Other"

        gas_fuel = request.form.get("gas_fuel", "")
        if gas_fuel == "Other":
            gas_fuel = request.form.get("gas_fuel_other", "Other").strip() or "Other"

        gender_val = gender
        if gender_val == "Other":
            gender_val = request.form.get("gender_other", "Other").strip() or "Other"

        participant_data = {
            "full_name":       session["full_name"],
            "age":             _int_or_none(age),
            "gender":          gender_val,
            "prev_gas_heater": request.form.get("prev_gas_heater"),
            "home_heating":    home_heating,
            "gas_fuel":        gas_fuel,
            "showers_per_day": request.form.get("showers_per_day"),
            "shower_duration": request.form.get("shower_duration"),
            "h2_familiarity":  _int_or_none(request.form.get("h2_familiarity")),
        }

        if session.get("is_stub") and session.get("participant_id"):
            # Participant was pre-registered as a stub — fill in their demographics.
            db.complete_participant(session["participant_id"], participant_data)
            session["is_stub"] = False
        else:
            # Completely new participant — create the full record.
            pid = db.create_participant(participant_data)
            session["participant_id"] = pid

        return redirect(url_for("section_b"))

    return render_template("section_a.html", form={})


# ---------------------------------------------------------------------------
# Page 4 – Sections B + C + D
# ---------------------------------------------------------------------------

@app.route("/section-b", methods=["GET", "POST"])
def section_b():
    """Water heater performance, safety/confidence and optional comments."""
    if "participant_id" not in session:
        return redirect(url_for("start"))

    if request.method == "POST":
        # Validate required fields
        errors = []
        required_b = ["b2_hot_water_speed", "b3_temp_control", "b4_temp_stability",
                      "b6_overall_satisfaction", "b7_comparison", "b8_daily_use"]
        required_c = ["c1_comfort", "c2_met_expectations", "c3_reliability",
                      "c4_confidence", "c5_would_install"]

        for field in required_b + required_c:
            if not request.form.get(field):
                # field names look like "b2_hot_water_speed" -> label "B2"
                label = field.split("_", 1)[0].upper()
                errors.append(f"Question {label} is required.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("section_b.html", form=request.form,
                                   returning=session.get("returning"))

        # Link this submission to the operator's logged session for the day by
        # matching on the closest start_time, or create a pending row if the
        # operator hasn't logged it yet (see db.match_or_create_test).
        # We pass only the shower time — operator-owned fields (temp_setting,
        # operator_name, end_time) are never written by the participant.
        test_data = {
            "participant_id": session["participant_id"],
            "test_date":      session["test_date"],
            "start_time":     session.get("shower_time"),
        }
        test_id = db.match_or_create_test(test_data)
        session["test_id"] = test_id

        # Create response record
        response_data = {
            "test_id":                test_id,
            "b1_temp_setting":        _float_or_none(request.form.get("b1_temp_setting")),
            "b2_hot_water_speed":     _int_or_none(request.form.get("b2_hot_water_speed")),
            "b3_temp_control":        _int_or_none(request.form.get("b3_temp_control")),
            "b4_temp_stability":      _int_or_none(request.form.get("b4_temp_stability")),
            "b5_temp_after_pause":    _int_or_none(request.form.get("b5_temp_after_pause")),
            "b5_not_applicable":      request.form.get("b5_not_applicable") == "1",
            "b6_overall_satisfaction": _int_or_none(request.form.get("b6_overall_satisfaction")),
            "b7_comparison":          _int_or_none(request.form.get("b7_comparison")),
            "b8_daily_use":           _int_or_none(request.form.get("b8_daily_use")),
            "c1_comfort":             _int_or_none(request.form.get("c1_comfort")),
            "c2_met_expectations":    _int_or_none(request.form.get("c2_met_expectations")),
            "c3_reliability":         _int_or_none(request.form.get("c3_reliability")),
            "c4_confidence":          _int_or_none(request.form.get("c4_confidence")),
            "c5_would_install":       _int_or_none(request.form.get("c5_would_install")),
            "d1_liked_most":          request.form.get("d1_liked_most", "").strip() or None,
            "d2_improvements":        request.form.get("d2_improvements", "").strip() or None,
            "d3_comments":            request.form.get("d3_comments", "").strip() or None,
        }
        db.create_response(response_data)

        return redirect(url_for("confirmation"))

    return render_template("section_b.html", form={}, returning=session.get("returning"))


# ---------------------------------------------------------------------------
# Confirmation page
# ---------------------------------------------------------------------------

@app.route("/confirmation")
def confirmation():
    """Thank-you page shown after successful submission."""
    test_id        = session.get("test_id", "—")
    participant_id = session.get("participant_id", "—")
    full_name      = session.get("full_name", "")
    # Clear questionnaire session data
    for key in ["full_name", "test_date", "shower_time", "is_stub",
                "returning", "participant_id", "test_id"]:
        session.pop(key, None)
    return render_template("confirmation.html",
                           test_id=test_id,
                           participant_id=participant_id,
                           full_name=full_name)


# ---------------------------------------------------------------------------
# Operator login (password gate)
# ---------------------------------------------------------------------------

@app.route("/operator-login", methods=["GET", "POST"])
def operator_login():
    """Password gate for the operator panel."""
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == OPERATOR_PASSWORD:
            session["operator_authed"] = True
            return redirect(url_for("operator"))
        flash("Incorrect password.", "error")
        return redirect(url_for("operator_login"))
    return render_template("operator_login.html")


@app.route("/operator-logout")
def operator_logout():
    """Clear operator authentication."""
    session.pop("operator_authed", None)
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Operator panel – Section 0.1
# ---------------------------------------------------------------------------

@app.route("/operator")
def operator():
    """
    Operator-only panel. Search, registration and test edits are all handled
    client-side via the AJAX endpoints below (/api/check-participant,
    /api/participant-tests, /operator/create-participant, /operator/manual,
    /operator/update-test), so this route only renders the page.
    """
    if not session.get("operator_authed"):
        return redirect(url_for("operator_login"))
    return render_template("operator.html", today=str(date.today()))


# ---------------------------------------------------------------------------
# Operator – manual test entry (AJAX POST, returns JSON)
# ---------------------------------------------------------------------------

@app.route("/operator/create-participant", methods=["POST"])
def operator_create_participant():
    """Create a name-only participant stub from the operator panel."""
    if not session.get("operator_authed"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Invalid request body"}), 400

    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"ok": False, "error": "Name is required"}), 400

    # Don't create a duplicate if the name already exists
    existing = db.get_participant_by_name(full_name)
    if existing:
        return jsonify({
            "ok": True,
            "participant_id": existing["participant_id"],
            "already_existed": True,
            "is_stub": bool(existing.get("is_stub", 0))
        })

    try:
        pid = db.create_participant_stub(full_name)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "participant_id": pid, "already_existed": False, "is_stub": True})


@app.route("/operator/manual", methods=["POST"])
def operator_manual():
    """Create a test record from operator JSON without a participant form session."""
    if not session.get("operator_authed"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Invalid request body"}), 400

    pid       = (data.get("participant_id") or "").strip()
    test_date = data.get("test_date") or ""

    if not pid or not test_date:
        return jsonify({"ok": False, "error": "participant_id and test_date are required"})

    # Verify participant exists
    participant = db.get_participant_by_id(pid)
    if not participant:
        return jsonify({"ok": False, "error": f"Participant {pid} not found in database"})

    test_data = {
        "participant_id": pid,
        "test_date":      test_date,
        "start_time":     data.get("start_time") or None,
        "end_time":       data.get("end_time") or None,
        "temp_setting":   data.get("temp_setting"),
        "operator_name":  data.get("operator_name") or None,
        "comments":       data.get("comments") or None,
    }
    try:
        test_id = db.create_test(test_data)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})

    return jsonify({"ok": True, "test_id": test_id})


# ---------------------------------------------------------------------------
# AJAX helpers
# ---------------------------------------------------------------------------

@app.route("/api/check-participant")
def api_check_participant():
    """Return JSON {exists: bool, participant_id: str|null} for a given name."""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"exists": False, "participant_id": None})
    participant = db.get_participant_by_name(name)
    if participant:
        return jsonify({
            "exists": True,
            "participant_id": participant["participant_id"],
            "is_stub": bool(participant.get("is_stub", 0))
        })
    return jsonify({"exists": False, "participant_id": None, "is_stub": False})


@app.route("/api/participant-tests")
def api_participant_tests():
    """Return JSON list of test rows for a participant ID (operator panel)."""
    if not session.get("operator_authed"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 403
    pid = request.args.get("id", "").strip()
    if not pid:
        return jsonify({"tests": []})
    tests = db.list_tests_for_participant(pid)
    # Convert non-serialisable types (date, time, datetime) to strings
    serialisable = []
    for t in tests:
        row = {}
        for k, v in t.items():
            row[k] = str(v) if v is not None and not isinstance(v, (int, float, bool, str)) else v
        serialisable.append(row)
    return jsonify({"tests": serialisable})


@app.route("/operator/update-test", methods=["POST"])
def operator_update_test():
    """AJAX: update mutable fields on an existing test row."""
    if not session.get("operator_authed"):
        return jsonify({"ok": False, "error": "Not authenticated"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Invalid request body"}), 400

    test_id = (data.get("test_id") or "").strip()
    if not test_id:
        return jsonify({"ok": False, "error": "test_id is required"}), 400

    if not db.test_exists(test_id):
        return jsonify({"ok": False, "error": f"Test {test_id} not found"}), 404

    update_data = {
        "start_time":    data.get("start_time"),
        "end_time":      data.get("end_time"),
        "temp_setting":  data.get("temp_setting"),
        "operator_name": data.get("operator_name"),
        "comments":      data.get("comments"),
    }
    try:
        db.update_test(test_id, update_data)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@app.route("/export")
def export_csv():
    """Download all data as a UTF-8 CSV file (operator only)."""
    if not session.get("operator_authed"):
        return redirect(url_for("operator_login"))

    rows = db.export_all_to_csv()
    if not rows:
        flash("No data to export yet.", "info")
        return redirect(url_for("operator"))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)

    filename = f"H2GV_UX_Data_{date.today().strftime('%Y%m%d')}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),  # utf-8-sig = Excel-friendly BOM
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
