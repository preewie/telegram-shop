# Pree Wie Mini App — Step 1

This is the first deployable scaffold: Flask page, health checks, and initial PostgreSQL tables.

## Files
- `app.py` — Flask backend and database schema initialization
- `templates/index.html` — responsive starter page that can open inside Telegram
- `requirements.txt` — Python dependencies
- `render.yaml` — Render service settings
- `.gitignore` — excludes local secrets

## Render setup
1. Create a PostgreSQL database in Render.
2. Create a Web Service from this GitHub repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variable `DATABASE_URL` using the **Internal Database URL** from your Render PostgreSQL database when available.
6. Set `INIT_DB_ON_START` to `true` for the first deployment so the initial tables are created. After confirming `/health/database` works, you can change it to `false`.
7. Open `/health` and `/health/database` to test the service.

## Important
- Do not commit `.env` or secrets to GitHub.
- This is only the foundation. Payment approval, ABA KHQR receipt upload, Master login, client upload subscriptions, automatic expiry, and protected video delivery are not implemented yet.
- `INIT_DB_ON_START=true` runs the `CREATE TABLE IF NOT EXISTS` statements at service startup. It does not delete existing tables or records.
