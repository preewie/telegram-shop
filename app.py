import hmac
import json
import os
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
MASTER_API_PASSWORD = os.environ.get("MASTER_API_PASSWORD", "").strip()
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*").strip()

# CORS is a browser policy, not authentication. The write route still checks
# MASTER_API_PASSWORD on every request.
allowed_origins = "*" if ALLOWED_ORIGIN == "*" else [x.strip() for x in ALLOWED_ORIGIN.split(",") if x.strip()]
CORS(app, resources={r"/api/*": {"origins": allowed_origins}},
     allow_headers=["Content-Type", "X-Admin-Password"],
     methods=["GET", "PUT", "OPTIONS"])


def db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing")
    parsed = urlparse(DATABASE_URL)
    sslmode = "require" if parsed.scheme == "postgres" else "require"
    return psycopg2.connect(DATABASE_URL, sslmode=sslmode, connect_timeout=10)


def init_db():
    conn = db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS site_settings (
                        setting_key TEXT PRIMARY KEY,
                        setting_value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    INSERT INTO site_settings (setting_key, setting_value)
                    VALUES (
                        'channel_packages',
                        %s::jsonb
                    )
                    ON CONFLICT (setting_key) DO NOTHING
                """, (json.dumps({
                    "days": [
                        {"id": 1, "days": 5, "price": "$3.00"},
                        {"id": 2, "days": 10, "price": "$5.00"},
                        {"id": 3, "days": 20, "price": "$10.00"},
                        {"id": 4, "days": 30, "price": "$15.00"}
                    ],
                    "videos": [
                        {"id": 101, "count": 5, "price": "$3.00"},
                        {"id": 102, "count": 10, "price": "$4.00"},
                        {"id": 103, "count": 25, "price": "$5.80"},
                        {"id": 104, "count": 30, "price": "$6.00"},
                        {"id": 105, "count": 35, "price": "$6.30"}
                    ]
                }),))
        return True
    finally:
        conn.close()


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": "PREE WIE Shop API"})


@app.get("/api/channel-packages")
def get_channel_packages():
    try:
        init_db()
        conn = db_connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT setting_value FROM site_settings WHERE setting_key = %s",
                    ("channel_packages",)
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"days": [], "videos": []})
                value = row["setting_value"]
                if isinstance(value, str):
                    value = json.loads(value)
                return jsonify(value)
        finally:
            conn.close()
    except Exception:
        app.logger.exception("Could not load channel packages")
        return jsonify({"error": "Could not load package settings"}), 500


@app.put("/api/channel-packages")
def save_channel_packages():
    if not MASTER_API_PASSWORD:
        return jsonify({"error": "Server admin password is not configured"}), 503

    provided = request.headers.get("X-Admin-Password", "")
    if not hmac.compare_digest(provided, MASTER_API_PASSWORD):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON object"}), 400

    days = data.get("days")
    videos = data.get("videos")
    if not isinstance(days, list) or not isinstance(videos, list):
        return jsonify({"error": "Both 'days' and 'videos' must be arrays"}), 400
    if len(days) > 100 or len(videos) > 100:
        return jsonify({"error": "Too many package options"}), 400

    # Validate and normalize values before saving.
    clean_days = []
    for item in days:
        if not isinstance(item, dict):
            return jsonify({"error": "Invalid day package"}), 400
        try:
            d = int(item.get("days", 0))
            price = str(item.get("price", "")).strip()
            ident = int(item.get("id", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid day package fields"}), 400
        if d < 1 or d > 3650 or not price or len(price) > 30:
            return jsonify({"error": "Invalid day package values"}), 400
        clean_days.append({"id": ident, "days": d, "price": price})

    clean_videos = []
    for item in videos:
        if not isinstance(item, dict):
            return jsonify({"error": "Invalid video package"}), 400
        try:
            count = int(item.get("count", 0))
            price = str(item.get("price", "")).strip()
            ident = int(item.get("id", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid video package fields"}), 400
        if count < 1 or count > 100000 or not price or len(price) > 30:
            return jsonify({"error": "Invalid video package values"}), 400
        clean_videos.append({"id": ident, "count": count, "price": price})

    payload = json.dumps({"days": clean_days, "videos": clean_videos})
    try:
        init_db()
        conn = db_connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO site_settings (setting_key, setting_value, updated_at)
                        VALUES ('channel_packages', %s::jsonb, NOW())
                        ON CONFLICT (setting_key)
                        DO UPDATE SET setting_value = EXCLUDED.setting_value,
                                      updated_at = NOW()
                    """, (payload,))
        finally:
            conn.close()
        return jsonify({"ok": True, "message": "Packages saved"})
    except Exception:
        app.logger.exception("Could not save channel packages")
        return jsonify({"error": "Could not save package settings"}), 500


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
