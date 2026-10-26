import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader

app = Flask(__name__, static_folder='public', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'pree_wie_super_secret_key')

# Cloudinary Setup
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT stories.*, users.username as client_name, users.qr_code_url as client_qr
        FROM stories 
        JOIN users ON stories.client_id = users.id 
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
