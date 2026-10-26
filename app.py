import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader

app = Flask(__name__, static_folder='public', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY') or 'change-this-secret-in-render-env'

# Cloudinary Setup
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise RuntimeError('DATABASE_URL is missing in Render Environment Variables')
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor, connect_timeout=10)


def ensure_schema():
    """Apply safe additive migrations for existing PostgreSQL databases."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'client',
                    qr_code_url TEXT,
                    package_expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            \"\"\")
            cur.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS packages (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    duration_days INT NOT NULL,
                    max_videos INT NOT NULL,
                    price DECIMAL(10,2) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            \"\"\")
            cur.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS stories (
                    id SERIAL PRIMARY KEY,
                    client_id INT REFERENCES users(id) ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL DEFAULT '',
                    description TEXT,
                    poster_url TEXT NOT NULL DEFAULT '',
                    video_url TEXT NOT NULL DEFAULT '',
                    file_url TEXT,
                    price DECIMAL(10,2) NOT NULL DEFAULT 1.00,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            \"\"\")
            # Critical fix: add the missing owner column to older stories tables.
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS client_id INT REFERENCES users(id) ON DELETE CASCADE\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS title VARCHAR(255) NOT NULL DEFAULT ''\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS description TEXT\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS poster_url TEXT NOT NULL DEFAULT ''\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS video_url TEXT NOT NULL DEFAULT ''\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS file_url TEXT\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS price DECIMAL(10,2) NOT NULL DEFAULT 1.00\")
            cur.execute(\"ALTER TABLE stories ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\")
            cur.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    buyer_id INT REFERENCES users(id) ON DELETE SET NULL,
                    seller_id INT REFERENCES users(id) ON DELETE SET NULL,
                    story_id INT REFERENCES stories(id) ON DELETE SET NULL,
                    package_id INT REFERENCES packages(id) ON DELETE SET NULL,
                    type VARCHAR(50) NOT NULL DEFAULT 'movie',
                    amount DECIMAL(10,2) NOT NULL DEFAULT 0,
                    receipt_url TEXT NOT NULL DEFAULT '',
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            \"\"\")
        conn.commit()
    finally:
        conn.close()


@app.before_request
def run_safe_migrations():
    # Ensure old databases gain the columns this version needs.
    if not app.config.get('SCHEMA_READY'):
        ensure_schema()
        app.config['SCHEMA_READY'] = True

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT stories.*, users.username as client_name, users.qr_code_url as client_qr
        FROM stories 
        LEFT JOIN users ON stories.client_id = users.id 
        ORDER BY stories.created_at DESC
    """)
    stories = cur.fetchall()
    
    cur.execute("SELECT * FROM packages ORDER BY price ASC")
    packages = cur.fetchall()
    
    cur.execute("SELECT * FROM users WHERE role = 'master' LIMIT 1")
    master_user = cur.fetchone()
    
    cur.close()
    conn.close()
    return render_template('index.html', stories=stories, packages=packages, master_user=master_user, user=session.get('user'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user and check_password_hash(user['password'], password):
        session['user'] = {
            'id': user['id'],
            'username': user['username'],
            'role': user['role']
        }
        return redirect(url_for('index'))
    return redirect(url_for('index', error='invalid_credentials'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

@app.route('/change-password', methods=['POST'])
def change_password():
    if 'user' not in session:
        return redirect(url_for('index'))
    
    new_password = request.form.get('new_password')
    hashed_password = generate_password_hash(new_password)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_password, session['user']['id']))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/update-qr', methods=['POST'])
def update_qr():
    if 'user' not in session:
        return redirect(url_for('index'))
    
    qr_file = request.files.get('qr_image')
    if qr_file:
        upload_result = cloudinary.uploader.upload(qr_file, folder="pree_wie_qrs")
        qr_url = upload_result.get('secure_url')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET qr_code_url = %s WHERE id = %s", (qr_url, session['user']['id']))
        conn.commit()
        cur.close()
        conn.close()
        
    return redirect(url_for('index'))

@app.route('/upload-story', methods=['POST'])
def upload_story():
    if 'user' not in session or session['user']['role'] != 'client':
        return redirect(url_for('index'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    price = request.form.get('price', 1.00)
    
    poster_file = request.files.get('poster')
    video_file = request.files.get('video')
    extra_file = request.files.get('file')
    
    poster_url = cloudinary.uploader.upload(poster_file, folder="pree_wie_posters").get('secure_url') if poster_file else ''
    video_url = cloudinary.uploader.upload(video_file, folder="pree_wie_videos", resource_type="video").get('secure_url') if video_file else ''
    file_url = cloudinary.uploader.upload(extra_file, folder="pree_wie_files", resource_type="raw").get('secure_url') if extra_file else ''
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO stories (client_id, title, description, poster_url, video_url, file_url, price)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user']['id'], title, description, poster_url, video_url, file_url, price))
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/submit-order', methods=['POST'])
def submit_order():
    buyer_id = session['user']['id'] if 'user' in session else None
    seller_id = request.form.get('seller_id')
    story_id = request.form.get('story_id')
    package_id = request.form.get('package_id')
    order_type = request.form.get('type')
    amount = request.form.get('amount')
    receipt_file = request.files.get('receipt')
    
    receipt_url = cloudinary.uploader.upload(receipt_file, folder="pree_wie_receipts").get('secure_url') if receipt_file else ''
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (buyer_id, seller_id, story_id, package_id, type, amount, receipt_url, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
    """, (buyer_id, seller_id, story_id, package_id, order_type, amount, receipt_url))
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
