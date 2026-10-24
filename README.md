# PREE WIE STUDIO — starter app

This package implements the requested Master/Client split and a mobile-first Streaming-style story upload page with separate Poster, Video and optional File cards, price preview, Cloudinary uploads, PostgreSQL metadata, package purchase requests, story purchase requests, payment review, and owner-only story editing/deletion.

## Important: deployment and security

This is a functional starter that needs a staging deployment and end-to-end testing with your actual Render/PostgreSQL/Cloudinary accounts before public use. It is not yet a production-certified streaming platform.

- Create a PostgreSQL database on Render and set `DATABASE_URL` on the backend service.
- Set `JWT_SECRET_KEY`, `MASTER_EMAIL`, `MASTER_PASSWORD`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, and `ALLOWED_ORIGINS` in Render Environment. Never commit real secrets.
- Deploy this folder as the backend service. `render.yaml` provides a starting blueprint. If your frontend remains on a separate Render static service, set `API` in `public/index.html` to `https://pree-wie-backend.onrender.com` instead of `location.origin`, and configure CORS origins.
- The first startup creates the Master account from `MASTER_EMAIL`/`MASTER_PASSWORD` if it does not exist and seeds example packages. Change the bootstrap password and keep credentials private.
- Master package payments are addressed to the Master QR. Story purchase payments are addressed to the story owner's QR. QR URLs are stored per user.
- Payments are manual: the recipient must check actual ABA payment in their banking app before approving. This app does not connect to ABA APIs.

## Security checklist before production

1. Configure Cloudinary authenticated/private video delivery and generate short-lived signed URLs. The included `/api/stories/<id>/play` checks authorization but currently returns the stored Cloudinary URL; the upload helper uses regular Cloudinary upload delivery. Do not publish paid content until this is replaced with authenticated delivery.
2. Implement genuine receipt image upload and verification workflow instead of pasting a receipt URL in the simple demo checkout prompts.
3. Add rate limiting, audit logs, CSRF protection if cookie auth is introduced, email verification/password reset, stronger upload MIME/content scanning, and file size limits tailored to your plan.
4. Test membership expiration, package limits, concurrent payment review, refunds, story purchase edge cases, Cloudinary cleanup, and database migrations. `create_all()` is used for initial setup; use migrations for future schema changes.
5. Consider private raw file delivery and signed download links for extra files, and review local legal/privacy requirements.

## API overview

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/me`
- `GET /api/packages`, Master-only `POST /api/master/packages`, `PATCH /api/master/packages/<id>`
- `POST /api/packages/<id>/purchase`
- Client-only `POST /api/stories`, `GET /api/stories`, `PATCH/DELETE /api/stories/<id>`, `POST /api/stories/<id>/purchase`
- `GET /api/stories/<id>/play` checks ownership/purchase access
- `POST /api/payments/<id>/review`, `GET /api/payments`
- Master-only `GET /api/master/dashboard`, `GET /api/master/clients`, `PATCH /api/master/clients/<id>`
- `POST /api/me/qr`, `GET /api/health`

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env       # set real local values before running
python app.py
```

For local use, export the variables in `.env` through your shell or use a local dotenv loader. The app intentionally does not load `.env` automatically.


## Role boundaries (important)
- Customer: browse stories and purchase them. The current starter UI/API should be tested end-to-end before public launch.
- Client: may purchase a package from Master and upload/manage only their own stories. Client cannot create or sell packages.
- Master: creates packages, reviews package payments, manages client accounts, and owns a separate QR setting.
- Package payments are addressed to the Master account; story payments are addressed to the story owner. QR images are stored per user.

## Important production checklist
1. Set `MASTER_EMAIL`, `MASTER_PASSWORD`, `DATABASE_URL`, `JWT_SECRET_KEY`, and Cloudinary credentials in Render Environment. Use a strong unique master password and secret.
2. Set `ALLOWED_ORIGINS` to the exact frontend origin(s), not `*`, when deploying publicly.
3. **Paid video security is not production-complete in this starter.** The current upload helper creates standard Cloudinary assets and the play endpoint gates access but returns the stored URL. Configure authenticated/private Cloudinary delivery and implement short-lived signed delivery URLs before selling access to paid video.
4. Payment approval is manual; there is no ABA API integration. Verify the transfer in ABA before approving a payment.
5. Validate upload size/type, test on a staging database, and test role permissions and purchase flows before public launch.
6. `public/index.html` is served at `/`; `templates/index.html` is included as a synced copy for projects that need that path. Flask does not automatically render the templates copy.


## Folder and GitHub names
- Keep `app.py`, `requirements.txt`, `render.yaml`, `.env.example`, and `README.md` in the repository root.
- The frontend file is available at both `public/index.html` and `templates/index.html` as requested. The app serves `public/index.html` at `/`.
- `__pycache__` folders are generated automatically and should not be uploaded.

## Important deployment note
Use Python 3.12 on Render (configured in `render.yaml`) and ensure the deployed commit includes the `psycopg2-binary` requirement. This addresses the `ModuleNotFoundError: No module named psycopg` driver error when the database URL is rewritten to use `psycopg2`. Set `DATABASE_URL`, `JWT_SECRET_KEY`, Cloudinary credentials, `MASTER_EMAIL`, `MASTER_PASSWORD`, and `ALLOWED_ORIGINS` in Render Environment. Do not put secrets in GitHub.

The Guest landing page is public and does not force login before browsing stories. Client and Master tools appear after login. Before using for real payments, verify the payment workflow and private video delivery on a staging deployment; a public Cloudinary URL alone does not protect paid video.

## V3 safety and go-live checklist

This package is a deployment starter, not a claim that every business workflow has been production-tested.

### Included in this V3 package
- Three separate entry points: Guest, Client, and Master Admin.
- Guest can browse stories without signing in.
- Client package purchase requests and story upload flow.
- Master package management, client activation controls, payment review, and dashboard.
- Separate QR settings per account; package payments are directed to the Master account and story payments to the story owner.
- PostgreSQL URL normalization for Render (`postgres://` / `postgresql://` to `postgresql+psycopg2://`).
- Duplicate review protection for payments already marked approved/rejected.
- Fail-closed paid-video playback: the app does not return public Cloudinary video URLs until authenticated/private Cloudinary delivery and short-lived signed playback URLs are configured.

### Before opening to real customers
1. Set `DATABASE_URL`, `JWT_SECRET_KEY`, all Cloudinary credentials, `MASTER_EMAIL`, `MASTER_PASSWORD`, and the exact `ALLOWED_ORIGINS` in Render Environment. Never commit secrets to GitHub.
2. Change any default or reused Master password. If the Master account already exists, verify its password and role before launch.
3. Configure Cloudinary authenticated/private video delivery and implement short-lived signed playback URLs. Paid video playback intentionally returns HTTP 503 until this is configured; this prevents exposing public video URLs.
4. Replace receipt URL entry with a proper receipt image upload flow if customers need to upload screenshots directly.
5. Test registration/login, Master login, QR separation, package purchase, payment approval/rejection, package expiry/limits, story upload/edit/delete, purchase access, and mobile layout on a staging database.
6. Set up PostgreSQL backups and test restoring one before real launch.
7. Check that `https://pree-wie-shop.onrender.com` is the only allowed frontend origin, or add the actual frontend URL if it differs.

### Repository layout
Upload the contents of this ZIP into the root of the GitHub repository. Keep both `public/index.html` and `templates/index.html`; the deployed home page is served from `public/index.html`.
