PREE WIE — Backend + Frontend (Master Setup repair package)

FILES
- app.py: Flask backend, PostgreSQL settings, Master setup/login/session/logout/change-password and package API.
- index.html: PREE WIE shop interface and API calls.
- requirements.txt: Python dependencies.

IMPORTANT: Do NOT delete all Render Environment Variables. Keep or set these on the BACKEND service:
1. DATABASE_URL = your existing Render PostgreSQL internal/external connection string as currently used. Do not replace it with a guessed value.
2. MASTER_SETUP_SECRET = a long private secret only you know. Never put it in index.html or send it in chat.
3. ALLOWED_ORIGIN = https://pree-wie-shop.onrender.com
Render provides PORT automatically; do not set it manually unless needed.

DEPLOY
1. Back up current files first.
2. Replace backend app.py and requirements.txt at the existing backend repository root.
3. Replace the frontend index.html at the same path the frontend service already serves (if the repo uses public/index.html, put it there instead of root index.html).
4. Commit changes and wait for both Render services to finish deploying.
5. Open https://pree-wie-backend.onrender.com/api/health and check database=connected.
6. Open https://pree-wie-backend.onrender.com/api/admin/status. If initialized=false, press Master Login / create password in the shop; enter MASTER_SETUP_SECRET first, then create a new Master Password (at least 8 characters).
7. If initialized=true, use the Master Password previously created.

DATA SAFETY
- Do not delete or reset the PostgreSQL database. Existing package data is stored there.
- Do not remove DATABASE_URL or MASTER_SETUP_SECRET.
- This ZIP is not deployed automatically; GitHub commit and Render deployment are still required.
