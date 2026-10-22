import hashlib
import hma
import json
import os
import secrets
import time
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
MASTER_API_PASSWORD = os.environ.get("MASTER_API_PASSWORD", "").strip()
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*").strip()
# Master sessions are persistent until logout or password change.

allowed_origins = (
    "*"
    if ALLOWED_ORIGIN == "*"
    else [origin.strip() for origin in ALLOWED_ORIGIN.split(",") if origin.strip()]
)
CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "PUT", "POST", "OPTIONS"],
    supports_credentials=False,
)

DEFAULT_PACKAGES = {
    "days": [
        {"id": 1, "days": 5, "price": "$3.00"},
        {"id": 2, "days": 10, "price": "$5.00"},
        {"id": 3, "days": 20, "price": "$10.00"},
        {"id": 4, "days": 30, "price": "$15.00"},
    ],
    "videos": [
        {"id": 101, "count": 5, "price": "$3.00"},
        {"id": 102, "count": 10, "price": "$4.00"},
        {"id": 103, "count": 25, "price": "$5.80"},
        {"id": 104, "count": 30, "price": "$6.00"},
        {"id": 105, "count": 35, "price": "$6.30"},
    ],
}


def db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10,
        cursor_factory=RealDictCursor,
    )


def init_db():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS site_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS master_credentials (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    password_hash TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS master_sessions (
                    token_hash TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # Master password is created from the app on first use; only its hash is stored.
            cur.execute(
                """
                INSERT INTO site_settings (setting_key, setting_value)
                VALUES (%s, %s)
                ON CONFLICT (setting_key) DO NOTHING
                """,
                ("channel_packages", Json(DEFAULT_PACKAGES)),
            )


def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_admin_token(token):
    if not isinstance(token, str) or len(token) < 32:
        return False
    try:
        token_hash = hash_session_token(token)
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM master_sessions WHERE token_hash = %s",
                    (token_hash,),
                )
                valid = cur.fetchone() is not None
                if valid:
                    cur.execute(
                        "UPDATE master_sessions SET last_seen_at = NOW() WHERE token_hash = %s",
                        (token_hash,),
                    )
        return valid
    except Exception:
        app.logger.exception("Could not validate Master session")
        return False


def get_bearer_token():
    header = request.headers.get("Authorization", "")
    return header[7:] if header.startswith("Bearer ") else ""


def require_admin():
    return verify_admin_token(get_bearer_token())


def validate_packages(data):
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object"

    days = data.get("days")
    videos = data.get("videos")
    if not isinstance(days, list) or not isinstance(videos, list):
        return None, "Both 'days' and 'videos' must be arrays"
    if len(days) > 100 or len(videos) > 100:
        return None, "Too many package rows"

    clean_days = []
    clean_videos = []

    for i, item in enumerate(days):
        if not isinstance(item, dict):
            return None, f"Day package #{i + 1} is invalid"
        try:
            package_id = int(item.get("id", i + 1))
            count = int(item.get("days"))
        except (TypeError, ValueError):
            return None, f"Day package #{i + 1}: id and days must be integers"
        price = item.get("price")
        if count < 1 or count > 3650:
            return None, f"Day package #{i + 1}: days must be between 1 and 3650"
        if not isinstance(price, str) or not price.strip() or len(price.strip()) > 40:
            return None, f"Day package #{i + 1}: price is required (max 40 characters)"
        clean_days.append({"id": package_id, "days": count, "price": price.strip()})

    for i, item in enumerate(videos):
        if not isinstance(item, dict):
            return None, f"Video package #{i + 1} is invalid"
        try:
            package_id = int(item.get("id", 101 + i))
            count = int(item.get("count"))
        except (TypeError, ValueError):
            return None, f"Video package #{i + 1}: id and count must be integers"
        price = item.get("price")
        if count < 1 or count > 1000000:
            return None, f"Video package #{i + 1}: count must be between 1 and 1000000"
        if not isinstance(price, str) or not price.strip() or len(price.strip()) > 40:
            return None, f"Video package #{i + 1}: price is required (max 40 characters)"
        clean_videos.append({"id": package_id, "count": count, "price": price.strip()})

    return {"days": clean_days, "videos": clean_videos}, None


@app.get("/")
def health():
    return jsonify({
        "ok": True,
        "service": "Pree Wie Backend",
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/health")
def api_health():
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS healthy")
                cur.fetchone()
        return jsonify({"ok": True, "database": "connected"})
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify({"ok": False, "database": "unavailable"}), 503


@app.get("/api/channel-packages")
def get_channel_packages():
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT setting_value FROM site_settings WHERE setting_key = %s",
                    ("channel_packages",),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        """
                        INSERT INTO site_settings (setting_key, setting_value)
                        VALUES (%s, %s)
                        ON CONFLICT (setting_key) DO NOTHING
                        """,
                        ("channel_packages", Json(DEFAULT_PACKAGES)),
                    )
                    return jsonify(DEFAULT_PACKAGES)
                value = row["setting_value"]
                if isinstance(value, str):
                    value = json.loads(value)
                return jsonify(value)
    except Exception:
        app.logger.exception("Could not load package settings")
        return jsonify({"error": "Could not load packages from database"}), 503


@app.get("/api/admin/status")
def admin_status():
    """Report whether first-time Master password setup has been completed."""
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM master_credentials WHERE id = 1")
                initialized = cur.fetchone() is not None
        return jsonify({"ok": True, "initialized": initialized})
    except Exception:
        app.logger.exception("Could not read Master setup status")
        return jsonify({"error": "Could not check Master setup status"}), 503


@app.post("/api/admin/setup")
def admin_setup():
    """Create the first Master password exactly once."""
    if not DATABASE_URL:
        return jsonify({"error": "Database is not configured"}), 503
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not isinstance(password, str) or len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if len(password) > 256:
        return jsonify({"error": "Password is too long"}), 400

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                # Serialize first-time setup attempts so only one can succeed.
                cur.execute("SELECT pg_advisory_xact_lock(741920261)")
                cur.execute("SELECT 1 FROM master_credentials WHERE id = 1")
                if cur.fetchone() is not None:
                    return jsonify({"error": "Master password is already set. Please log in."}), 409
                cur.execute(
                    "INSERT INTO master_credentials (id, password_hash) VALUES (1, %s)",
                    (generate_password_hash(password),),
                )
                token = secrets.token_urlsafe(48)
                cur.execute(
                    "INSERT INTO master_sessions (token_hash) VALUES (%s)",
                    (hash_session_token(token),),
                )
        return jsonify({"ok": True, "token": token, "persistent": True})
    except Exception:
        app.logger.exception("Master first-time setup failed")
        return jsonify({"error": "Could not create Master password. Please try again."}), 503


@app.post("/api/admin/login")
def admin_login():
    if not DATABASE_URL:
        return jsonify({"error": "Database is not configured"}), 503
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not isinstance(password, str) or not password:
        return jsonify({"error": "Password is required"}), 400

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM master_credentials WHERE id = 1")
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Master password is not initialized. Please create it first."}), 409
                if not check_password_hash(row["password_hash"], password):
                    return jsonify({"error": "Incorrect Master Password"}), 401
                token = secrets.token_urlsafe(48)
                cur.execute(
                    "INSERT INTO master_sessions (token_hash) VALUES (%s)",
                    (hash_session_token(token),),
                )
        return jsonify({"ok": True, "token": token, "persistent": True})
    except Exception:
        app.logger.exception("Master login failed")
        return jsonify({"error": "Could not log in. Please try again."}), 503


@app.get("/api/admin/session")
def admin_session():
    if not require_admin():
        return jsonify({"ok": False}), 401
    return jsonify({"ok": True, "authenticated": True})


@app.post("/api/admin/logout")
def admin_logout():
    token = get_bearer_token()
    if not token:
        return jsonify({"ok": True})
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM master_sessions WHERE token_hash = %s",
                    (hash_session_token(token),),
                )
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("Master logout failed")
        return jsonify({"error": "Could not log out on server"}), 503


@app.post("/api/admin/change-password")
def admin_change_password():
    if not require_admin():
        return jsonify({"error": "Unauthorized. Please log in again."}), 401
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        return jsonify({"error": "Invalid password format"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400
    if len(new_password) > 256:
        return jsonify({"error": "New password is too long"}), 400
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM master_credentials WHERE id = 1 FOR UPDATE")
                row = cur.fetchone()
                if not row or not check_password_hash(row["password_hash"], current_password):
                    return jsonify({"error": "Current password is incorrect"}), 401
                cur.execute(
                    "UPDATE master_credentials SET password_hash = %s, updated_at = NOW() WHERE id = 1",
                    (generate_password_hash(new_password),),
                )
                # Revoke all other devices/sessions, but keep this session logged in.
                current_token_hash = hash_session_token(get_bearer_token())
                cur.execute(
                    "DELETE FROM master_sessions WHERE token_hash <> %s",
                    (current_token_hash,),
                )
        return jsonify({"ok": True, "message": "Password changed successfully"})
    except Exception:
        app.logger.exception("Master password change failed")
        return jsonify({"error": "Could not change password"}), 503

@app.put("/api/channel-packages")
def save_channel_packages():
    if not require_admin():
        return jsonify({"error": "Unauthorized. Please log in again."}), 401

    data = request.get_json(silent=True)
    packages, error = validate_packages(data)
    if error:
        return jsonify({"error": error}), 400

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO site_settings (setting_key, setting_value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (setting_key)
                    DO UPDATE SET setting_value = EXCLUDED.setting_value,
                                  updated_at = NOW()
                    """,
                    ("channel_packages", Json(packages)),
                )
        return jsonify({"ok": True, "message": "Packages saved to PostgreSQL", "data": packages})
    except Exception:
        app.logger.exception("Could not save package settings")
        return jsonify({"error": "Could not save packages to database"}), 503


# Initialize schema on service startup. Render must have DATABASE_URL configured.
try:
    init_db()
    app.logger.info("Database initialized")
except Exception:
    app.logger.exception("Database initialization failed; check DATABASE_URL")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
