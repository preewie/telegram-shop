import os
import logging
from flask import Flask, jsonify, render_template
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not configured")

    # Render PostgreSQL URLs normally use SSL. sslmode=require is safe for Render.
    return psycopg2.connect(
        DATABASE_URL,
        sslmode=os.getenv("DB_SSLMODE", "require"),
        connect_timeout=10,
    )


def init_database():
    """Create the initial tables if they do not exist yet."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS app_users (
            id BIGSERIAL PRIMARY KEY,
            telegram_user_id BIGINT UNIQUE,
            username TEXT,
            role TEXT NOT NULL DEFAULT 'client'
                CHECK (role IN ('master', 'client')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stories (
            id BIGSERIAL PRIMARY KEY,
            owner_user_id BIGINT REFERENCES app_users(telegram_user_id),
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            poster_url TEXT NOT NULL DEFAULT '',
            video_url TEXT NOT NULL DEFAULT '',
            price NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (price >= 0),
            is_published BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS story_purchases (
            id BIGSERIAL PRIMARY KEY,
            buyer_telegram_user_id BIGINT NOT NULL,
            story_id BIGINT NOT NULL REFERENCES stories(id),
            amount NUMERIC(10,2) NOT NULL CHECK (amount >= 0),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            receipt_file_id TEXT,
            receipt_unique_id TEXT UNIQUE,
            reviewed_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS upload_packages (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            duration_days INTEGER NOT NULL CHECK (duration_days > 0),
            price NUMERIC(10,2) NOT NULL CHECK (price >= 0),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS client_subscriptions (
            id BIGSERIAL PRIMARY KEY,
            client_telegram_user_id BIGINT NOT NULL,
            package_id BIGINT REFERENCES upload_packages(id),
            starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'expired', 'cancelled')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS upload_package_payments (
            id BIGSERIAL PRIMARY KEY,
            client_telegram_user_id BIGINT NOT NULL,
            package_id BIGINT NOT NULL REFERENCES upload_packages(id),
            amount NUMERIC(10,2) NOT NULL CHECK (amount >= 0),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            receipt_file_id TEXT,
            receipt_unique_id TEXT UNIQUE,
            reviewed_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
        logger.info("Initial database tables are ready")
    finally:
        conn.close()


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "pree-wie-mini-app"}), 200


@app.get("/health/database")
def database_health():
    try:
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT NOW() AS database_time")
                row = cur.fetchone()
            return jsonify({
                "ok": True,
                "database": "connected",
                "database_time": row["database_time"].isoformat(),
            }), 200
        finally:
            conn.close()
    except Exception:
        logger.exception("Database health check failed")
        return jsonify({
            "ok": False,
            "database": "disconnected",
            "message": "Check DATABASE_URL and Render PostgreSQL settings",
        }), 503


@app.post("/internal/init-database")
def internal_init_database():
    # Temporary setup endpoint. Protect it with INIT_SECRET before using.
    expected_secret = os.getenv("INIT_SECRET", "").strip()
    supplied_secret = os.getenv("INIT_SECRET_HEADER", "").strip()
    if not expected_secret or supplied_secret != expected_secret:
        return jsonify({
            "ok": False,
            "message": "Database initialization endpoint is disabled. Set up tables via deployment startup instead."
        }), 403

    try:
        init_database()
        return jsonify({"ok": True, "message": "Initial tables created"}), 200
    except Exception:
        logger.exception("Database initialization failed")
        return jsonify({"ok": False, "message": "Database initialization failed"}), 500


if __name__ == "__main__":
    # Render provides PORT automatically.
    port = int(os.getenv("PORT", "10000"))
    # Initial schema is created only when INIT_DB_ON_START=true.
    if os.getenv("INIT_DB_ON_START", "false").lower() == "true":
        try:
            init_database()
        except Exception:
            logger.exception("Initial database setup failed")
    app.run(host="0.0.0.0", port=port)
