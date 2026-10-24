import os, uuid, secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import cloudinary, cloudinary.uploader, cloudinary.utils

app = Flask(__name__, static_folder='public', static_url_path='')
raw_db = os.getenv('DATABASE_URL', 'sqlite:///pree_wie_dev.db')
if raw_db.startswith('postgres://'): raw_db = raw_db.replace('postgres://', 'postgresql://', 1)
app.config.update(SQLALCHEMY_DATABASE_URI=raw_db, SQLALCHEMY_TRACK_MODIFICATIONS=False,
                  JWT_SECRET_KEY=os.getenv('JWT_SECRET_KEY', secrets.token_hex(32)),
                  MAX_CONTENT_LENGTH=int(os.getenv('MAX_UPLOAD_MB','500'))*1024*1024)
db = SQLAlchemy(app); JWTManager(app)
origins = [x.strip() for x in os.getenv('ALLOWED_ORIGINS','*').split(',') if x.strip()]
CORS(app, origins=origins or '*', supports_credentials=False)
cloudinary.config(cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'), api_key=os.getenv('CLOUDINARY_API_KEY'), api_secret=os.getenv('CLOUDINARY_API_SECRET'), secure=True)

class User(db.Model):
    id=db.Column(db.Integer, primary_key=True); email=db.Column(db.String(255), unique=True, nullable=False)
    password_hash=db.Column(db.String(255), nullable=False); role=db.Column(db.String(20), default='client', nullable=False)
    active=db.Column(db.Boolean, default=True, nullable=False); qr_url=db.Column(db.Text); qr_public_id=db.Column(db.String(255))
    created_at=db.Column(db.DateTime, default=datetime.utcnow)
class Package(db.Model):
    id=db.Column(db.Integer, primary_key=True); name=db.Column(db.String(120), nullable=False)
    description=db.Column(db.Text, default=''); price=db.Column(db.Float, nullable=False); days=db.Column(db.Integer, nullable=False)
    upload_limit=db.Column(db.Integer, default=20); active=db.Column(db.Boolean, default=True, nullable=False)
class Membership(db.Model):
    id=db.Column(db.Integer, primary_key=True); user_id=db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    package_id=db.Column(db.Integer, db.ForeignKey('package.id'), nullable=False); expires_at=db.Column(db.DateTime, nullable=False)
    status=db.Column(db.String(20), default='pending'); created_at=db.Column(db.DateTime, default=datetime.utcnow)
class Story(db.Model):
    id=db.Column(db.Integer, primary_key=True); owner_id=db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title=db.Column(db.String(200), nullable=False); description=db.Column(db.Text, default=''); price=db.Column(db.Float, nullable=False, default=1.0)
    poster_url=db.Column(db.Text); poster_public_id=db.Column(db.String(255)); video_url=db.Column(db.Text); video_public_id=db.Column(db.String(255))
    video_type=db.Column(db.String(40), default='upload'); file_url=db.Column(db.Text); file_public_id=db.Column(db.String(255)); file_name=db.Column(db.String(255))
    created_at=db.Column(db.DateTime, default=datetime.utcnow); active=db.Column(db.Boolean, default=True)
class Payment(db.Model):
    id=db.Column(db.Integer, primary_key=True); payer_id=db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id=db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False); kind=db.Column(db.String(20), nullable=False)
    package_id=db.Column(db.Integer, db.ForeignKey('package.id')); story_id=db.Column(db.Integer, db.ForeignKey('story.id'))
    amount=db.Column(db.Float, nullable=False); receipt_url=db.Column(db.Text); status=db.Column(db.String(20), default='pending')
    created_at=db.Column(db.DateTime, default=datetime.utcnow); reviewed_at=db.Column(db.DateTime)
class StoryAccess(db.Model):
    id=db.Column(db.Integer, primary_key=True); user_id=db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    story_id=db.Column(db.Integer, db.ForeignKey('story.id'), nullable=False); payment_id=db.Column(db.Integer, db.ForeignKey('payment.id'))

ALLOWED_EXTRA={'pdf','txt','doc','docx','epub','zip'}
def current_user():
    ident=get_jwt_identity()
    return db.session.get(User, int(ident)) if ident else None
def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        @jwt_required()
        def wrapped(*a,**kw):
            u=current_user()
            if not u or not u.active: return jsonify(error='Account inactive'),403
            if u.role not in roles: return jsonify(error='Permission denied'),403
            return fn(*a,**kw)
        return wrapped
    return deco
def upload_cloud(file, resource_type='auto', folder='pree-wie'):
    if not file or not file.filename: raise ValueError('Missing file')
    if not os.getenv('CLOUDINARY_CLOUD_NAME') or not os.getenv('CLOUDINARY_API_KEY') or not os.getenv('CLOUDINARY_API_SECRET'):
        raise RuntimeError('Cloudinary credentials are not configured')
    result=cloudinary.uploader.upload(file, folder=folder, resource_type=resource_type, use_filename=False, unique_filename=True)
    return result

def story_json(s):
    return {'id':s.id,'owner_id':s.owner_id,'title':s.title,'description':s.description,'price':s.price,'poster_url':s.poster_url,
            'video_available':bool(s.video_public_id),'file_name':s.file_name,'created_at':s.created_at.isoformat()+'Z'}
def payment_json(p):
    return {'id':p.id,'payer_id':p.payer_id,'recipient_id':p.recipient_id,'kind':p.kind,'amount':p.amount,'status':p.status,
            'receipt_url':p.receipt_url,'created_at':p.created_at.isoformat()+'Z','story_id':p.story_id,'package_id':p.package_id}
@app.get('/')
def home(): return send_from_directory('public','index.html')
@app.get('/api/health')
def health():
    try: db.session.execute(db.text('SELECT 1')); return jsonify(ok=True,database='connected')
    except Exception: return jsonify(ok=False,database='unavailable'),503
@app.post('/api/auth/register')
def register():
    data=request.get_json(silent=True) or {}; email=str(data.get('email','')).strip().lower(); password=str(data.get('password',''))
    if len(email)<5 or len(password)<8: return jsonify(error='Valid email and password (8+ characters) required'),400
    if User.query.filter_by(email=email).first(): return jsonify(error='Email already registered'),409
    u=User(email=email,password_hash=generate_password_hash(password),role='client'); db.session.add(u); db.session.commit()
    return jsonify(token=create_access_token(identity=str(u.id)),user={'id':u.id,'email':u.email,'role':u.role})
@app.post('/api/auth/login')
def login():
    data=request.get_json(silent=True) or {}; u=User.query.filter_by(email=str(data.get('email','')).strip().lower()).first()
    if not u or not check_password_hash(u.password_hash,str(data.get('password',''))) or not u.active: return jsonify(error='Invalid login or inactive account'),401
    return jsonify(token=create_access_token(identity=str(u.id)),user={'id':u.id,'email':u.email,'role':u.role})
@app.get('/api/me')
@jwt_required()
def me():
    u=current_user()
    if not u: return jsonify(error='User not found'),404
    membership=Membership.query.filter_by(user_id=u.id,status='active').order_by(Membership.expires_at.desc()).first()
    return jsonify(id=u.id,email=u.email,role=u.role,active=u.active,qr_url=u.qr_url,membership={'expires_at':membership.expires_at.isoformat()+'Z'} if membership else None)
@app.post('/api/me/qr')
@role_required('master','client')
def set_qr():
    u=current_user(); f=request.files.get('qr')
    if not f: return jsonify(error='Choose a QR image'),400
    if not (f.mimetype or '').startswith('image/'): return jsonify(error='QR must be an image'),400
    try:
        r=upload_cloud(f,'image','pree-wie/qr')
        u.qr_url=r['secure_url']; u.qr_public_id=r['public_id']; db.session.commit()
        return jsonify(ok=True,qr_url=u.qr_url)
    except Exception as e: db.session.rollback(); return jsonify(error=str(e)),400
@app.get('/api/packages')
def packages(): return jsonify(packages=[{'id':p.id,'name':p.name,'description':p.description,'price':p.price,'days':p.days,'upload_limit':p.upload_limit} for p in Package.query.filter_by(active=True).order_by(Package.price)])
@app.post('/api/master/packages')
@role_required('master')
def create_package():
    d=request.get_json(silent=True) or {}
    try:
        p=Package(name=str(d['name']).strip(),description=str(d.get('description','')),price=round(float(d['price']),2),days=int(d['days']),upload_limit=int(d.get('upload_limit',20)))
        if p.price<0 or p.days<1 or p.upload_limit<1: raise ValueError()
        db.session.add(p); db.session.commit(); return jsonify(id=p.id),201
    except Exception: db.session.rollback(); return jsonify(error='Check package name, price, days and upload limit'),400
@app.patch('/api/master/packages/<int:pid>')
@role_required('master')
def edit_package(pid):
    p=db.session.get(Package,pid)
    if not p: return jsonify(error='Package not found'),404
    d=request.get_json(silent=True) or {}
    for k in ('name','description','active'):
        if k in d: setattr(p,k,d[k])
    for k in ('price','days','upload_limit'):
        if k in d: setattr(p,k, type(getattr(p,k))(d[k]))
    db.session.commit(); return jsonify(ok=True)
@app.post('/api/packages/<int:pid>/purchase')
@role_required('client')
def purchase_package(pid):
    u=current_user(); p=db.session.get(Package,pid); receipt=request.form.get('receipt_url','').strip()
    if not p or not p.active: return jsonify(error='Package unavailable'),404
    master=User.query.filter_by(role='master',active=True).first()
    if not master: return jsonify(error='Master payment account unavailable'),503
    pay=Payment(payer_id=u.id,recipient_id=master.id,kind='package',package_id=p.id,amount=p.price,receipt_url=receipt or None)
    db.session.add(pay); db.session.commit(); return jsonify(payment=payment_json(pay),recipient_qr=master.qr_url),201
@app.post('/api/stories')
@role_required('client')
def create_story():
    u=current_user(); membership=Membership.query.filter_by(user_id=u.id,status='active').filter(Membership.expires_at>datetime.utcnow()).order_by(Membership.expires_at.desc()).first()
    if not membership: return jsonify(error='Active package required before uploading stories'),403
    pkg=db.session.get(Package,membership.package_id)
    count=Story.query.filter_by(owner_id=u.id,active=True).count()
    if pkg and count>=pkg.upload_limit: return jsonify(error='Package story limit reached'),403
    title=request.form.get('title','').strip(); description=request.form.get('description','').strip()
    try: price=round(float(request.form.get('price','1.00')),2)
    except ValueError: return jsonify(error='Invalid price'),400
    if not title or len(title)>200 or price<0: return jsonify(error='Title and non-negative price required'),400
    poster=request.files.get('poster'); video=request.files.get('video'); extra=request.files.get('extra_file')
    if not poster or not (poster.mimetype or '').startswith('image/'): return jsonify(error='Poster image is required'),400
    if not video: return jsonify(error='Video file is required'),400
    if extra:
        ext=extra.filename.rsplit('.',1)[-1].lower() if '.' in extra.filename else ''
        if ext not in ALLOWED_EXTRA: return jsonify(error='Extra file type not allowed'),400
    uploaded=[]
    try:
        pr=upload_cloud(poster,'image','pree-wie/posters'); uploaded.append(pr)
        # Keep paid videos authenticated/private at delivery; store public_id and only return a gated play endpoint.
        vr=upload_cloud(video,'video','pree-wie/videos'); uploaded.append(vr)
        fr=None
        if extra: fr=upload_cloud(extra,'raw','pree-wie/files'); uploaded.append(fr)
        s=Story(owner_id=u.id,title=title,description=description,price=price,poster_url=pr['secure_url'],poster_public_id=pr['public_id'],
                video_url=vr['secure_url'],video_public_id=vr['public_id'],video_type=vr.get('resource_type','video'),
                file_url=fr['secure_url'] if fr else None,file_public_id=fr['public_id'] if fr else None,file_name=secure_filename(extra.filename) if extra else None)
        db.session.add(s); db.session.commit(); return jsonify(story=story_json(s)),201
    except Exception as e:
        db.session.rollback()
        # Best-effort rollback of already uploaded assets.
        for r in uploaded:
            try: cloudinary.uploader.destroy(r['public_id'],resource_type=r.get('resource_type','image'),invalidate=True)
            except Exception: pass
        return jsonify(error='Upload/save failed: '+str(e)),400
@app.get('/api/stories')
def list_stories(): return jsonify(stories=[story_json(s) for s in Story.query.filter_by(active=True).order_by(Story.created_at.desc()).all()])
@app.patch('/api/stories/<int:sid>')
@role_required('client')
def edit_story(sid):
    u=current_user(); s=db.session.get(Story,sid)
    if not s or s.owner_id!=u.id: return jsonify(error='Story not found or not yours'),404
    d=request.get_json(silent=True) or {}
    if 'title' in d:
        title=str(d['title']).strip()
        if not title or len(title)>200: return jsonify(error='Invalid title'),400
        s.title=title
    if 'description' in d: s.description=str(d['description'])
    if 'price' in d:
        try: s.price=round(float(d['price']),2)
        except Exception: return jsonify(error='Invalid price'),400
        if s.price<0: return jsonify(error='Invalid price'),400
    db.session.commit(); return jsonify(story=story_json(s))
@app.delete('/api/stories/<int:sid>')
@role_required('client')
def delete_story(sid):
    u=current_user(); s=db.session.get(Story,sid)
    if not s or s.owner_id!=u.id: return jsonify(error='Story not found or not yours'),404
    s.active=False; db.session.commit(); return jsonify(ok=True)
@app.post('/api/stories/<int:sid>/purchase')
@role_required('client')
def purchase_story(sid):
    u=current_user(); s=db.session.get(Story,sid)
    if not s or not s.active: return jsonify(error='Story unavailable'),404
    if s.owner_id==u.id: return jsonify(error='Cannot purchase your own story'),400
    if StoryAccess.query.filter_by(user_id=u.id,story_id=s.id).first(): return jsonify(error='Already purchased'),409
    owner=db.session.get(User,s.owner_id)
    pay=Payment(payer_id=u.id,recipient_id=owner.id,kind='story',story_id=s.id,amount=s.price,receipt_url=(request.get_json(silent=True) or {}).get('receipt_url'))
    db.session.add(pay); db.session.commit(); return jsonify(payment=payment_json(pay),recipient_qr=owner.qr_url),201
@app.get('/api/stories/<int:sid>/play')
@jwt_required()
def play_story(sid):
    u=current_user(); s=db.session.get(Story,sid)
    if not u or not s or not s.active: return jsonify(error='Story unavailable'),404
    allowed=s.owner_id==u.id or u.role=='master' or StoryAccess.query.filter_by(user_id=u.id,story_id=s.id).first() is not None
    if not allowed: return jsonify(error='Purchase required'),403
    if not s.video_public_id: return jsonify(error='Video unavailable'),404
    # Auth gate is enforced here. For production, configure Cloudinary authenticated/private assets
    # and replace this URL with a short-lived signed delivery URL; do not use public video delivery.
    return jsonify(video_url=s.video_url,security_note='Configure authenticated Cloudinary delivery before production use.')
@app.get('/api/payments')
@role_required('master','client')
def payments():
    u=current_user()
    q=Payment.query.filter((Payment.recipient_id==u.id)|(Payment.payer_id==u.id))
    return jsonify(payments=[payment_json(p) for p in q.order_by(Payment.created_at.desc()).limit(300).all()])
@app.post('/api/payments/<int:pid>/review')
@role_required('master','client')
def review_payment(pid):
    u=current_user(); d=request.get_json(silent=True) or {}; p=db.session.get(Payment,pid)
    if not p or p.recipient_id!=u.id: return jsonify(error='Payment not found or not yours to review'),404
    if p.status!='pending': return jsonify(error='Payment already reviewed'),409
    status=d.get('status')
    if status not in ('approved','rejected'): return jsonify(error='Status must be approved or rejected'),400
    p.status=status; p.reviewed_at=datetime.utcnow()
    if status=='approved' and p.kind=='package':
        package=db.session.get(Package,p.package_id)
        if not package: return jsonify(error='Package missing'),400
        old=Membership.query.filter_by(user_id=p.payer_id,status='active').filter(Membership.expires_at>datetime.utcnow()).order_by(Membership.expires_at.desc()).first()
        start=max(datetime.utcnow(),old.expires_at) if old else datetime.utcnow()
        if old: old.status='expired'
        db.session.add(Membership(user_id=p.payer_id,package_id=package.id,expires_at=start+timedelta(days=package.days),status='active'))
    elif status=='approved' and p.kind=='story':
        if not StoryAccess.query.filter_by(user_id=p.payer_id,story_id=p.story_id).first(): db.session.add(StoryAccess(user_id=p.payer_id,story_id=p.story_id,payment_id=p.id))
    db.session.commit(); return jsonify(ok=True,payment=payment_json(p))
@app.get('/api/master/dashboard')
@role_required('master')
def dashboard():
    return jsonify(clients=User.query.filter_by(role='client').count(),active_clients=User.query.filter_by(role='client',active=True).count(),
                   stories=Story.query.filter_by(active=True).count(),pending_payments=Payment.query.filter_by(status='pending').count(),
                   approved_revenue=round(sum(p.amount for p in Payment.query.filter_by(status='approved').all()),2))
@app.get('/api/master/clients')
@role_required('master')
def clients(): return jsonify(clients=[{'id':u.id,'email':u.email,'active':u.active,'created_at':u.created_at.isoformat()+'Z'} for u in User.query.filter_by(role='client').order_by(User.created_at.desc()).all()])
@app.patch('/api/master/clients/<int:uid>')
@role_required('master')
def update_client(uid):
    u=db.session.get(User,uid)
    if not u or u.role!='client': return jsonify(error='Client not found'),404
    d=request.get_json(silent=True) or {}
    if 'active' in d: u.active=bool(d['active'])
    db.session.commit(); return jsonify(ok=True,active=u.active)
@app.errorhandler(413)
def too_large(_): return jsonify(error='File too large; increase MAX_UPLOAD_MB if appropriate'),413
@app.errorhandler(500)
def server_error(_): db.session.rollback(); return jsonify(error='Internal server error'),500

def seed_master():
    email=os.getenv('MASTER_EMAIL','').strip().lower(); password=os.getenv('MASTER_PASSWORD','')
    if not email or not password: return
    u=User.query.filter_by(email=email).first()
    if u: u.role='master'
    else: db.session.add(User(email=email,password_hash=generate_password_hash(password),role='master'))
    if Package.query.count()==0:
        for name,price,days,limit in [('Starter',3,7,10),('Creator',6,30,50),('Studio',12,90,200)]:
            db.session.add(Package(name=name,price=price,days=days,upload_limit=limit,description=f'{limit} active stories for {days} days'))
    db.session.commit()
with app.app_context():
    db.create_all()
    try: seed_master()
    except Exception: db.session.rollback()

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
