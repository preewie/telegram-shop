import os
import logging
from datetime import timedelta
from functools import wraps

import cloudinary
import cloudinary.uploader
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_ME_BEFORE_DEPLOY")
app.permanent_session_lifetime = timedelta(days=7)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
MASTER_USERNAME = os.environ.get("MASTER_USERNAME", "master").strip().lower()
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "")
MASTER_DISPLAY_NAME = os.environ.get("MASTER_DISPLAY_NAME", "Pree Wie Master")
MASTER_QR_URL = os.environ.get("ABA_MASTER_QR_URL", "")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("pree-wie")

if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )

def connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing in Render Environment")
    return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)

def init_db():
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                display_name VARCHAR(120) NOT NULL,
                password_hash TEXT NOT NULL,
                role VARCHAR(20) NOT NULL CHECK(role IN ('master','client','customer')),
                aba_qr_url TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE IF NOT EXISTS stories (
                id BIGSERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL REFERENCES users(id),
                title VARCHAR(200) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price NUMERIC(10,2) NOT NULL DEFAULT 1.00 CHECK(price >= 0),
                poster_url TEXT,
                video_url TEXT,
                video_public_id TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'published'
                    CHECK(status IN ('draft','published','hidden')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS purchases (
                id BIGSERIAL PRIMARY KEY,
                story_id BIGINT NOT NULL REFERENCES stories(id),
                buyer_id BIGINT NOT NULL REFERENCES users(id),
                seller_id BIGINT NOT NULL REFERENCES users(id),
                amount NUMERIC(10,2) NOT NULL,
                receipt_url TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                reviewed_by BIGINT REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                UNIQUE(story_id, buyer_id)
            );
            CREATE TABLE IF NOT EXISTS upload_packages (
                id BIGSERIAL PRIMARY KEY,
                title VARCHAR(120) NOT NULL,
                days INTEGER NOT NULL CHECK(days > 0 AND days <= 3650),
                price NUMERIC(10,2) NOT NULL CHECK(price >= 0),
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE IF NOT EXISTS package_payments (
                id BIGSERIAL PRIMARY KEY,
                client_id BIGINT NOT NULL REFERENCES users(id),
                package_id BIGINT NOT NULL REFERENCES upload_packages(id),
                amount NUMERIC(10,2) NOT NULL,
                receipt_url TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                reviewed_by BIGINT REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            );
            CREATE TABLE IF NOT EXISTS client_subscriptions (
                id BIGSERIAL PRIMARY KEY,
                client_id BIGINT NOT NULL REFERENCES users(id),
                starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                source_payment_id BIGINT REFERENCES package_payments(id),
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE INDEX IF NOT EXISTS idx_stories_owner ON stories(owner_id);
            CREATE INDEX IF NOT EXISTS idx_purchases_seller ON purchases(seller_id, status);
            CREATE INDEX IF NOT EXISTS idx_package_payments_client ON package_payments(client_id, status);
            """)
            cur.execute("SELECT id FROM users WHERE role='master' LIMIT 1")
            row = cur.fetchone()
            if not row:
                if MASTER_PASSWORD:
                    cur.execute(
                        "INSERT INTO users(username,display_name,password_hash,role,aba_qr_url) VALUES(%s,%s,%s,'master',%s)",
                        (MASTER_USERNAME, MASTER_DISPLAY_NAME, generate_password_hash(MASTER_PASSWORD), MASTER_QR_URL or None)
                    )
            cur.execute("SELECT COUNT(*) FROM upload_packages")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO upload_packages(title,days,price) VALUES(%s,%s,%s)",
                    [("5 ថ្ងៃ", 5, 2), ("10 ថ្ងៃ", 10, 3), ("15 ថ្ងៃ", 15, 4),
                     ("20 ថ្ងៃ", 20, 5), ("30 ថ្ងៃ", 30, 6)]
                )

def query_one(sql, args=()):
    with connect_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, args)
            return cur.fetchone()

def query_all(sql, args=()):
    with connect_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, args)
            return cur.fetchall()

def execute(sql, args=(), returning=False):
    with connect_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, args)
            result = cur.fetchone() if returning else None
            return result

def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return query_one("SELECT id,username,display_name,role,aba_qr_url FROM users WHERE id=%s AND active=TRUE", (uid,))

def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                flash("សូមចូលគណនីជាមុន។", "error")
                return redirect(url_for("login"))
            if role and user["role"] != role:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return deco

def upload_cloudinary(file_obj, resource_type="image", folder="pree-wie"):
    if not (CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET):
        raise RuntimeError("សូមកំណត់ Cloudinary credentials នៅ Render Environment ជាមុន។")
    if not file_obj or not file_obj.filename:
        return None
    return cloudinary.uploader.upload(
        file_obj, folder=folder, resource_type=resource_type, overwrite=False, unique_filename=True, use_filename=False
    )

@app.before_request
def startup_db_check():
    if request.path == "/health":
        return
    if not app.config.get("_db_ready"):
        init_db()
        app.config["_db_ready"] = True

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def index():
    user = current_user()
    stories = query_all("""
        SELECT s.id,s.title,s.description,s.price,s.poster_url,s.owner_id,u.display_name AS owner_name
        FROM stories s JOIN users u ON u.id=s.owner_id
        WHERE s.status='published'
        ORDER BY s.created_at DESC LIMIT 100
    """)
    return render_template("index.html", user=user, stories=stories)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 8 or not display:
            flash("Username ត្រូវមានយ៉ាងតិច 3 តួ, Password យ៉ាងតិច 8 តួ និងបញ្ចូលឈ្មោះ។", "error")
        else:
            try:
                execute("INSERT INTO users(username,display_name,password_hash,role) VALUES(%s,%s,%s,'client')",
                        (username, display, generate_password_hash(password)))
                flash("បង្កើតគណនី Client ជោគជ័យ។ សូមចូលគណនី។", "success")
                return redirect(url_for("login"))
            except psycopg2.errors.UniqueViolation:
                flash("Username នេះមានអ្នកប្រើរួចហើយ។", "error")
    return render_template("auth.html", mode="register", user=current_user())

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE username=%s AND active=TRUE", (username,))
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["uid"] = user["id"]
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Username ឬ Password មិនត្រឹមត្រូវ។", "error")
    return render_template("auth.html", mode="login", user=current_user())

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.get("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    if user["role"] == "master":
        stories = query_all("""
            SELECT s.*,u.display_name AS owner_name,
            (SELECT COUNT(*) FROM purchases p WHERE p.story_id=s.id AND p.status='approved') AS buyer_count
            FROM stories s JOIN users u ON u.id=s.owner_id ORDER BY s.created_at DESC
        """)
        pending_stories = query_all("""
            SELECT p.*,s.title,b.username AS buyer_name,seller.display_name AS seller_name
            FROM purchases p JOIN stories s ON s.id=p.story_id
            JOIN users b ON b.id=p.buyer_id JOIN users seller ON seller.id=p.seller_id
            WHERE p.status='pending' ORDER BY p.created_at
        """)
        package_payments = query_all("""
            SELECT pp.*,u.username,u.display_name,p.title AS package_title
            FROM package_payments pp JOIN users u ON u.id=pp.client_id
            JOIN upload_packages p ON p.id=pp.package_id
            WHERE pp.status='pending' ORDER BY pp.created_at
        """)
        clients = query_all("""
            SELECT u.id,u.username,u.display_name,u.aba_qr_url,
            (SELECT MAX(expires_at) FROM client_subscriptions cs WHERE cs.client_id=u.id AND cs.active=TRUE) AS expires_at
            FROM users u WHERE u.role='client' ORDER BY u.created_at DESC
        """)
        packages = query_all("SELECT * FROM upload_packages ORDER BY days")
        return render_template("master.html", user=user, stories=stories, pending_stories=pending_stories,
                               package_payments=package_payments, clients=clients, packages=packages)
    if user["role"] == "client":
        stories = query_all("""
            SELECT s.*,(SELECT COUNT(*) FROM purchases p WHERE p.story_id=s.id AND p.status='approved') AS buyer_count
            FROM stories s WHERE s.owner_id=%s ORDER BY s.created_at DESC
        """, (user["id"],))
        subscription = query_one("""
            SELECT expires_at FROM client_subscriptions
            WHERE client_id=%s AND active=TRUE AND expires_at>NOW()
            ORDER BY expires_at DESC LIMIT 1
        """, (user["id"],))
        packages = query_all("SELECT * FROM upload_packages WHERE active=TRUE ORDER BY days")
        payments = query_all("""
            SELECT pp.*,p.title AS package_title FROM package_payments pp
            JOIN upload_packages p ON p.id=pp.package_id
            WHERE pp.client_id=%s ORDER BY pp.created_at DESC LIMIT 20
        """, (user["id"],))
        return render_template("client.html", user=user, stories=stories, subscription=subscription,
                               packages=packages, payments=payments)
    return render_template("customer.html", user=user)

@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile():
    user = current_user()
    if request.method == "POST":
        display = request.form.get("display_name", "").strip()
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        row = query_one("SELECT password_hash FROM users WHERE id=%s", (user["id"],))
        updates = []
        args = []
        if display:
            updates.append("display_name=%s"); args.append(display)
        if new:
            if len(new) < 8 or not check_password_hash(row["password_hash"], old):
                flash("Password ថ្មីត្រូវមានយ៉ាងតិច 8 តួ ហើយត្រូវបញ្ចូល Password ចាស់ឱ្យបានត្រឹមត្រូវ។", "error")
                return redirect(url_for("profile"))
            updates.append("password_hash=%s"); args.append(generate_password_hash(new))
        qr = request.files.get("aba_qr")
        if qr and qr.filename:
            uploaded = upload_cloudinary(qr, "image", f"pree-wie/aba/{user['id']}")
            updates.append("aba_qr_url=%s"); args.append(uploaded["secure_url"])
        if updates:
            args.append(user["id"])
            execute("UPDATE users SET " + ", ".join(updates) + " WHERE id=%s", tuple(args))
        flash("រក្សាទុក Profile រួចរាល់។", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)

@app.route("/story/new", methods=["GET", "POST"])
@login_required("client")
def new_story():
    user = current_user()
    subscription = query_one("""
        SELECT expires_at FROM client_subscriptions WHERE client_id=%s AND active=TRUE
        AND expires_at>NOW() ORDER BY expires_at DESC LIMIT 1
    """, (user["id"],))
    if not subscription:
        flash("គណនីអ្នកមិនមានកញ្ចប់បង្ហោះសកម្មទេ។ សូមទិញកញ្ចប់ពី Master ជាមុន។", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        try:
            price = float(request.form.get("price", "1.00"))
            if not title or price < 0:
                raise ValueError()
            poster = upload_cloudinary(request.files.get("poster"), "image", f"pree-wie/client-{user['id']}/posters")
            video = upload_cloudinary(request.files.get("video"), "video", f"pree-wie/client-{user['id']}/videos")
            if not video:
                raise ValueError("សូមជ្រើសរើសវីដេអូរឿង។")
            execute("""
                INSERT INTO stories(owner_id,title,description,price,poster_url,video_url,video_public_id,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'published')
            """, (user["id"], title, description, price, poster["secure_url"] if poster else None,
                  video["secure_url"], video["public_id"]))
            flash("បានបង្ហោះរឿងជោគជ័យ។", "success")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            log.exception("Story upload failed")
            flash(f"មិនអាចបង្ហោះរឿងបាន៖ {exc}", "error")
    return render_template("story_form.html", user=user)

@app.route("/master/story/new", methods=["GET", "POST"])
@login_required("master")
def master_new_story():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        owner_id = int(request.form.get("owner_id", user["id"]))
        price = float(request.form.get("price", "1.00"))
        try:
            poster = upload_cloudinary(request.files.get("poster"), "image", f"pree-wie/master-{user['id']}/posters")
            video = upload_cloudinary(request.files.get("video"), "video", f"pree-wie/master-{user['id']}/videos")
            if not title or price < 0 or not video:
                raise ValueError("សូមបញ្ចូលចំណងជើង តម្លៃត្រឹមត្រូវ និងវីដេអូ។")
            execute("""INSERT INTO stories(owner_id,title,description,price,poster_url,video_url,video_public_id,status)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'published')""",
                    (owner_id, title, description, price, poster["secure_url"] if poster else None, video["secure_url"], video["public_id"]))
            flash("បានបន្ថែមរឿងជោគជ័យ។", "success")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            log.exception("Master story upload failed")
            flash(f"មិនអាចបន្ថែមរឿងបាន៖ {exc}", "error")
    owners = query_all("SELECT id,username,display_name,role FROM users WHERE role IN ('master','client') ORDER BY role,username")
    return render_template("master_story_form.html", user=user, owners=owners)

@app.get("/story/<int:story_id>")
def story_detail(story_id):
    user = current_user()
    story = query_one("""SELECT s.*,u.display_name AS owner_name,u.aba_qr_url AS seller_qr,u.id AS seller_id
                         FROM stories s JOIN users u ON u.id=s.owner_id WHERE s.id=%s AND s.status='published'""", (story_id,))
    if not story:
        abort(404)
    unlocked = False
    pending = False
    if user:
        p = query_one("SELECT status FROM purchases WHERE story_id=%s AND buyer_id=%s", (story_id, user["id"]))
        unlocked = bool(p and p["status"] == "approved")
        pending = bool(p and p["status"] == "pending")
        if story["owner_id"] == user["id"] or user["role"] == "master":
            unlocked = True
    return render_template("story.html", user=user, story=story, unlocked=unlocked, pending=pending)

@app.route("/story/<int:story_id>/buy", methods=["GET", "POST"])
@login_required()
def buy_story(story_id):
    user = current_user()
    story = query_one("""SELECT s.*,u.aba_qr_url AS seller_qr,u.display_name AS seller_name
                         FROM stories s JOIN users u ON u.id=s.owner_id
                         WHERE s.id=%s AND s.status='published'""", (story_id,))
    if not story:
        abort(404)
    if user["role"] == "master" or user["id"] == story["owner_id"]:
        flash("អ្នកមិនចាំបាច់ទិញរឿងផ្ទាល់ខ្លួនទេ។", "error")
        return redirect(url_for("story_detail", story_id=story_id))
    existing = query_one("SELECT status FROM purchases WHERE story_id=%s AND buyer_id=%s", (story_id, user["id"]))
    if existing and existing["status"] == "approved":
        return redirect(url_for("story_detail", story_id=story_id))
    if request.method == "POST":
        try:
            receipt = upload_cloudinary(request.files.get("receipt"), "image", f"pree-wie/receipts/story-{story_id}")
            if not receipt:
                raise ValueError("សូមផ្ទុករូបបង្កាន់ដៃ ABA។")
            execute("""
                INSERT INTO purchases(story_id,buyer_id,seller_id,amount,receipt_url,status)
                VALUES(%s,%s,%s,%s,%s,'pending')
                ON CONFLICT(story_id,buyer_id) DO UPDATE SET amount=EXCLUDED.amount,
                receipt_url=EXCLUDED.receipt_url,status='pending',reviewed_by=NULL,reviewed_at=NULL
            """, (story_id, user["id"], story["owner_id"], story["price"], receipt["secure_url"]))
            flash("បានផ្ញើបង្កាន់ដៃជូនម្ចាស់រឿងរួចរាល់។", "success")
            return redirect(url_for("story_detail", story_id=story_id))
        except Exception as exc:
            log.exception("Purchase receipt upload failed")
            flash(f"មិនអាចផ្ញើបង្កាន់ដៃបាន៖ {exc}", "error")
    return render_template("buy_story.html", user=user, story=story)

@app.post("/client/purchase/<int:purchase_id>/<action>")
@login_required("client")
def review_story_purchase(purchase_id, action):
    if action not in ("approve","reject"):
        abort(404)
    user = current_user()
    purchase = query_one("SELECT * FROM purchases WHERE id=%s AND seller_id=%s AND status='pending'", (purchase_id, user["id"]))
    if not purchase:
        abort(404)
    status = "approved" if action == "approve" else "rejected"
    execute("UPDATE purchases SET status=%s,reviewed_by=%s,reviewed_at=NOW() WHERE id=%s",
            (status, user["id"], purchase_id))
    flash("បានអាប់ដេតស្ថានភាពការទិញរឿង។", "success")
    return redirect(url_for("dashboard"))

@app.route("/packages/buy/<int:package_id>", methods=["GET", "POST"])
@login_required("client")
def buy_package(package_id):
    user = current_user()
    package = query_one("SELECT * FROM upload_packages WHERE id=%s AND active=TRUE", (package_id,))
    if not package:
        abort(404)
    if request.method == "POST":
        try:
            receipt = upload_cloudinary(request.files.get("receipt"), "image", f"pree-wie/receipts/package-client-{user['id']}")
            if not receipt:
                raise ValueError("សូមផ្ទុករូបបង្កាន់ដៃ ABA។")
            execute("""INSERT INTO package_payments(client_id,package_id,amount,receipt_url,status)
                       VALUES(%s,%s,%s,%s,'pending')""",
                    (user["id"], package_id, package["price"], receipt["secure_url"]))
            flash("បានផ្ញើបង្កាន់ដៃទិញកញ្ចប់ទៅ Master ជោគជ័យ។", "success")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            log.exception("Package payment upload failed")
            flash(f"មិនអាចផ្ញើបង្កាន់ដៃបាន៖ {exc}", "error")
    master = query_one("SELECT aba_qr_url FROM users WHERE role='master' LIMIT 1")
    return render_template("buy_package.html", user=user, package=package,
                           master_qr=(master["aba_qr_url"] if master and master["aba_qr_url"] else MASTER_QR_URL))

@app.post("/master/package-payment/<int:payment_id>/<action>")
@login_required("master")
def review_package_payment(payment_id, action):
    if action not in ("approve","reject"):
        abort(404)
    payment = query_one("""SELECT pp.*,p.days FROM package_payments pp
                           JOIN upload_packages p ON p.id=pp.package_id
                           WHERE pp.id=%s AND pp.status='pending'""", (payment_id,))
    if not payment:
        abort(404)
    user = current_user()
    status = "approved" if action == "approve" else "rejected"
    execute("UPDATE package_payments SET status=%s,reviewed_by=%s,reviewed_at=NOW() WHERE id=%s",
            (status, user["id"], payment_id))
    if action == "approve":
        execute("""INSERT INTO client_subscriptions(client_id,starts_at,expires_at,source_payment_id,active)
                   VALUES(%s,NOW(),NOW() + (%s * INTERVAL '1 day'),%s,TRUE)""",
                (payment["client_id"], payment["days"], payment_id))
    flash("បានអនុម័តកញ្ចប់សមាជិកភាព។", "success")
    return redirect(url_for("dashboard"))

@app.route("/master/package/new", methods=["POST"])
@login_required("master")
def create_package():
    title = request.form.get("title", "").strip()
    try:
        days = int(request.form.get("days", "0"))
        price = float(request.form.get("price", "0"))
        if not title or days < 1 or price < 0:
            raise ValueError()
        execute("INSERT INTO upload_packages(title,days,price,active) VALUES(%s,%s,%s,TRUE)", (title, days, price))
        flash("បានបង្កើតកញ្ចប់ថ្មីជោគជ័យ។", "success")
    except Exception:
        flash("ព័ត៌មានកញ្ចប់មិនត្រឹមត្រូវ។", "error")
    return redirect(url_for("dashboard"))

@app.post("/master/package/<int:package_id>/toggle")
@login_required("master")
def toggle_package(package_id):
    execute("UPDATE upload_packages SET active=NOT active WHERE id=%s", (package_id,))
    return redirect(url_for("dashboard"))

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="អ្នកមិនមានសិទ្ធិចូលផ្នែកនេះទេ។ មានតែ Master ប៉ុណ្ណោះដែលអាចจัดการកញ្ចប់បាន។"), 403

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="រកមិនឃើញទំព័រនេះទេ។"), 404

@app.errorhandler(413)
def too_large(_):
    return render_template("error.html", code=413, message="ឯកសារធំពេក។"), 413

@app.errorhandler(Exception)
def unhandled(exc):
    log.exception("Unhandled error: %s", exc)
    return render_template("error.html", code=500, message="มีបញ្ហាក្នុងប្រព័ន្ធ។"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
