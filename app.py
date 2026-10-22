import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
MASTER_API_PASSWORD = os.environ.get("MASTER_API_PASSWORD", "").strip()
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*").strip()
TOKEN_TTL_SECONDS = 1800

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
                INSERT INTO site_settings (setting_key, setting_value)
                VALUES (%s, %s)
                ON CONFLICT (setting_key) DO NOTHING
                """,
                ("channel_packages", Json(DEFAULT_PACKAGES)),
            )


def make_admin_token():
    issued_at = str(int(time.time()))
    signature = hmac.new(
        MASTER_API_PASSWORD.encode("utf-8"),
        issued_at.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{issued_at}.{signature}"


def verify_admin_token(token):
    if not MASTER_API_PASSWORD or not isinstance(token, str) or "." not in token:
        return False
    try:
        issued_at_text, supplied_signature = token.split(".", 1)
        issued_at = int(issued_at_text)
        now = int(time.time())
        if issued_at > now or now - issued_at > TOKEN_TTL_SECONDS:
            return False
        expected_signature = hmac.new(
            MASTER_API_PASSWORD.encode("utf-8"),
            issued_at_text.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(supplied_signature, expected_signature)
    except (ValueError, TypeError):
        return False


def require_admin():
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    return verify_admin_token(token)


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


@app.post("/api/admin/login")
def admin_login():
    if not MASTER_API_PASSWORD:
        return jsonify({"error": "Server admin password is not configured"}), 503

    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not isinstance(password, str) or not hmac.compare_digest(password, MASTER_API_PASSWORD):
        return jsonify({"error": "Incorrect Master API Password"}), 401

    return jsonify({
        "ok": True,
        "token": make_admin_token(),
        "expires_in": TOKEN_TTL_SECONDS,
    })


@app.put("/api/channel-packages")
def save_channel_packages():
    if not MASTER_API_PASSWORD:
        return jsonify({"error": "Server admin password is not configured"}), 503
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
