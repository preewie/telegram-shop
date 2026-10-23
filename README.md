# Pree Wie Mini App

Flask + PostgreSQL + Cloudinary starter for Pree Wie.

## Important deployment setup
Set these Render Environment Variables before use:
- DATABASE_URL: Internal Database URL from Render PostgreSQL
- SECRET_KEY: long random secret (not public)
- MASTER_USERNAME: master username
- MASTER_PASSWORD: strong password; the master user is created on first database initialization
- CLOUDINARY_CLOUD_NAME
- CLOUDINARY_API_KEY
- CLOUDINARY_API_SECRET
- ABA_MASTER_QR_URL: optional HTTPS URL of the Master ABA KHQR image

Client accounts are registered at /register. Clients can upload stories only while their subscription is active.
Master and each Client have separate ABA QR fields. Cloudinary folders are split by owner, e.g. `pree-wie/client-<id>/videos` vs `pree-wie/master-<id>/videos`; database records also keep `owner_id` separate.

## Important limitations before public launch
This is an initial functional scaffold, not a finished commercial platform. Cloudinary video URLs in this version are direct URLs; a determined user may share a URL. Production-grade paid video protection requires authenticated/signed delivery or a private storage/delivery setup. The current Customer area is minimal; customer purchase history, CSRF protection, advanced moderation, rate limiting, and comprehensive audit logs should be added before public launch. Manual ABA receipt review is not automatic bank verification.

## Deploy
1. Create Render PostgreSQL and set `DATABASE_URL`.
2. Set `SECRET_KEY`, `MASTER_USERNAME`, `MASTER_PASSWORD`.
3. Create Cloudinary account and add its three credentials.
4. Add the files to the GitHub repo preserving `templates/index.html` path.
5. Deploy. Open `/health`; it should return `{"status":"ok"}`.
6. Login as Master at `/login` with the environment username/password. The master account is created when tables initialize for the first time. If a master already exists, changing MASTER_PASSWORD environment variable does not reset its password; use Profile.
