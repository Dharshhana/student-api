import os
import re
import sys
import json
import html as html_lib
import pandas as pd
from flask import Flask, jsonify, request

app = Flask(__name__)
app.json.compact = False


HTML_VIEWER = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Student API</title>
<style>
body{background:#1e1e1e;color:#d4d4d4;font-family:Consolas,'Courier New',monospace;padding:20px;margin:0;font-size:14px;line-height:1.6;}
pre{white-space:pre-wrap;word-wrap:break-word;}
.k{color:#9cdcfe;}
.s{color:#ce9178;}
.n{color:#b5cea8;}
.b{color:#569cd6;}
.nl{color:#808080;font-style:italic;}
</style>
</head>
<body>
<pre id="j">__BODY__</pre>
<script>
var el=document.getElementById('j');
el.innerHTML=el.innerHTML
.replace(/(&quot;(?:\\\\.|[^&]|&(?!quot;))*?&quot;)(\\s*:)/g,'<span class="k">$1</span>$2')
.replace(/:(\\s*)(&quot;(?:\\\\.|[^&]|&(?!quot;))*?&quot;)/g,':$1<span class="s">$2</span>')
.replace(/(\\[|,)(\\s*)(&quot;(?:\\\\.|[^&]|&(?!quot;))*?&quot;)/g,'$1$2<span class="s">$3</span>')
.replace(/:(\\s*)(-?\\d+\\.?\\d*)/g,':$1<span class="n">$2</span>')
.replace(/:(\\s*)(true|false)/g,':$1<span class="b">$2</span>')
.replace(/:(\\s*)(null)/g,':$1<span class="nl">$2</span>');
</script>
</body>
</html>"""


@app.after_request
def beautify_for_browser(response):
    """If a browser requested this endpoint, render JSON as a styled HTML page."""
    ct = response.headers.get("Content-Type", "") or ""
    if not ct.startswith("application/json"):
        return response
    if "text/html" not in request.headers.get("Accept", ""):
        return response
    try:
        data = response.get_json()
        pretty = json.dumps(data, indent=4, ensure_ascii=False)
        body = html_lib.escape(pretty)
        response.set_data(HTML_VIEWER.replace("__BODY__", body))
        response.headers["Content-Type"] = "text/html; charset=utf-8"
    except Exception:
        pass
    return response

CSV_FILE = "Student Details.csv"
EXPECTED_COLUMNS = ["Name", "Department", "Blood Group", "Native"]
ID_PATTERN = re.compile(r"^[A-Za-z]{2}\d{3}$")
ID_PREFIX = "ST"


def read_file():
    if not os.path.exists(CSV_FILE):
        return None, "CSV file not found"
    try:
        df = pd.read_csv(CSV_FILE)
        df.columns = df.columns.str.strip()
        return df, None
    except Exception as e:
        return None, str(e)


def save_file(df):
    df.to_csv(CSV_FILE, index=False)


def generate_next_id(df):
    """Generate next sequential ID like ST001, ST002 — based on max existing number."""
    if "ID" not in df.columns:
        return f"{ID_PREFIX}001"
    nums = []
    for val in df["ID"].dropna().astype(str):
        m = re.match(r"^[A-Za-z]{2}(\d{3})$", val.strip())
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"{ID_PREFIX}{next_num:03d}"


def ensure_id_column(df):
    """Add ID column if missing, fill any empty ID cells with auto-generated IDs."""
    if "ID" not in df.columns:
        df.insert(0, "ID", "")
    for idx in df.index:
        cell = df.at[idx, "ID"]
        if pd.isna(cell) or str(cell).strip() == "":
            df.at[idx, "ID"] = generate_next_id(df)
    return df


def validate(df):
    """Return list of validation messages: missing fields + changed columns."""
    issues = []

    changed = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    for col in changed:
        issues.append(f"{col} column changed or deleted in CSV sheet")
    if changed:
        return issues

    for index, row in df.iterrows():
        missing = []
        for field in EXPECTED_COLUMNS:
            try:
                if pd.isna(row[field]) or str(row[field]).strip() == "":
                    missing.append(field)
            except Exception:
                missing.append(field)

        if missing:
            name = row.get("Name", "")
            if pd.isna(name) or str(name).strip() == "":
                identifier = f"Row {index + 2}"
            else:
                identifier = str(name).strip()
            issues.append(f"{identifier} -> Missing: {', '.join(missing)}")

    return issues


def df_to_records(df):
    """Convert dataframe to list of dicts, replacing NaN with empty string."""
    return df.fillna("").to_dict(orient="records")


def find_student_index(df, identifier):
    """Match by ID first, then by Name (case-insensitive, trimmed)."""
    target = identifier.strip().lower()
    if "ID" in df.columns:
        for idx, row in df.iterrows():
            cell = row["ID"]
            if pd.isna(cell):
                continue
            if str(cell).strip().lower() == target:
                return idx
    if "Name" not in df.columns:
        return None
    for idx, row in df.iterrows():
        cell = row["Name"]
        if pd.isna(cell):
            continue
        if str(cell).strip().lower() == target:
            return idx
    return None


# ---------- GET: read all students ----------_
@app.route("/students", methods=["GET"])
def get_students():
    df, err = read_file()
    if err:
        return jsonify({"error": err}), 500

    issues = validate(df)
    filters = {k: v for k, v in request.args.items() if v.strip()}
    applied = {}

    for key, value in filters.items():
        matched_col = next(
            (c for c in df.columns if c.lower().replace(" ", "") == key.lower().replace(" ", "")),
            None,
        )
        if matched_col is None:
            return jsonify({
                "error": f"Unknown filter field '{key}'",
                "available_fields": list(df.columns),
            }), 400

        df = df[df[matched_col].astype(str).str.contains(value.strip(), case=False, na=False)]
        applied[matched_col] = value.strip()

    return jsonify({
        "count": len(df),
        "filters": applied,
        "students": df_to_records(df),
        "issues": issues,
    }), 200


# ---------- POST: create a new student ----------
@app.route("/students", methods=["POST"])
def create_student():
    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload, dict):
        return jsonify({"error": "JSON body required"}), 400

    df, err = read_file()
    if err:
        return jsonify({"error": err}), 500

    df = ensure_id_column(df)

    user_id = str(payload.get("ID", "")).strip()
    if user_id:
        if not ID_PATTERN.match(user_id):
            return jsonify({
                "error": "ID must be 2 letters followed by 3 digits (e.g. ST001, CS042)",
            }), 400
        existing_ids = df["ID"].dropna().astype(str).str.strip().str.lower().tolist()
        if user_id.lower() in existing_ids:
            return jsonify({"error": f"ID '{user_id}' already exists"}), 409
        payload["ID"] = user_id
    else:
        payload["ID"] = generate_next_id(df)

    new_row = {col: payload.get(col, "") for col in df.columns}
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_file(df)

    issues = validate(df)
    return jsonify({
        "message": "Student created",
        "student": new_row,
        "issues": issues,
    }), 201


# ---------- PUT: update an existing student by name ----------
@app.route("/students/<name>", methods=["PUT"])
def update_student(name):
    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload, dict):
        return jsonify({"error": "JSON body required"}), 400

    df, err = read_file()
    if err:
        return jsonify({"error": err}), 500

    idx = find_student_index(df, name)
    if idx is None:
        return jsonify({"error": f"Student '{name}' not found"}), 404

    for key, value in payload.items():
        if key in df.columns:
            try:
                df.at[idx, key] = value
            except (ValueError, TypeError):
                df[key] = df[key].astype(object)
                df.at[idx, key] = value

    save_file(df)
    updated = df.iloc[idx].fillna("").to_dict()

    return jsonify({
        "message": f"Student '{name}' updated",
        "student": updated,
        "issues": validate(df),
    }), 200


# ---------- DELETE: remove a student by name ----------
@app.route("/students/<name>", methods=["DELETE"])
def delete_student(name):
    df, err = read_file()
    if err:
        return jsonify({"error": err}), 500

    idx = find_student_index(df, name)
    if idx is None:
        return jsonify({"error": f"Student '{name}' not found"}), 404

    df = df.drop(idx).reset_index(drop=True)
    save_file(df)

    return jsonify({
        "message": f"Student '{name}' deleted",
        "count": len(df),
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """Lightweight health check for uptime monitoring / cron jobs."""
    df, err = read_file()
    if err or df is None:
        return jsonify({
            "status": "unhealthy",
            "csv": "unavailable",
            "detail": err or "CSV file not found",
        }), 503
    return jsonify({
        "status": "ok",
        "csv": "available",
        "students": len(df),
    }), 200


@app.route("/", methods=["GET","POST", "PUT", "DELETE"])
def home():
    if request.method in ["POST", "PUT", "DELETE"]:
        return jsonify({
            "message": f"{request.method} is not allowed on '/'",
            "hint": "Use proper endpoints like /students for CRUD operations.",
            "available_endpoints": {
                "GET /students": "Read students",
                "POST /students": "Create student",
                "PUT /students/<name>": "Update student",
                "DELETE /students/<name>": "Delete student ",
                "GET /health": "Health check"
            }
        }), 200

    return jsonify({
        "message": "Student Details API",
        "endpoints": {
            "GET    /health":           "Health check for uptime monitoring",
            "GET    /students":         "Read all students + validation issues",
            "POST   /students":         "Create a new student (JSON body)",
            "PUT    /students/<name>":  "Update an existing student (JSON body)",
            "DELETE /students/<name>":  "Delete a student",
        },
    })


def initialize_csv():
    """On startup: ensure ID column exists in CSV and all rows have IDs."""
    df, err = read_file()
    if err or df is None:
        return
    before_cols = list(df.columns)
    before_ids = df["ID"].tolist() if "ID" in df.columns else []
    df = ensure_id_column(df)
    if list(df.columns) != before_cols or df["ID"].tolist() != before_ids:
        save_file(df)


def start_public_tunnel(port, max_attempts=6):
    """Start a Cloudflare quick tunnel with retries, monitor it, auto-restart if it dies."""
    try:
        from pycloudflared import try_cloudflare
    except ImportError:
        print("pycloudflared not installed. Run: pip install pycloudflared")
        return

    import time
    import threading

    def open_tunnel():
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = try_cloudflare(port=port)
                print("=" * 70)
                print(f"  PUBLIC URL (world wide): {result.tunnel}")
                print(f"  Try:  {result.tunnel}/students")
                print("=" * 70, flush=True)
                return result
            except Exception as e:
                last_err = e
                print(f"  Tunnel attempt {attempt}/{max_attempts} failed: {e}", flush=True)
                if attempt < max_attempts:
                    wait = min(5 * attempt, 30)
                    print(f"  Retrying in {wait}s...", flush=True)
                    time.sleep(wait)
        print(f"Tunnel could not be started after {max_attempts} attempts ({last_err}).", flush=True)
        return None

    def watchdog():
        result = open_tunnel()
        while True:
            time.sleep(15)
            proc = getattr(result, "process", None) if result else None
            if proc is not None and proc.poll() is not None:
                print("Tunnel died — restarting...", flush=True)
                result = open_tunnel()
            elif result is None:
                time.sleep(30)
                result = open_tunnel()

    threading.Thread(target=watchdog, daemon=True).start()


if __name__ == "__main__":
    initialize_csv()
    if "--public" in sys.argv:
        start_public_tunnel(5000)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
