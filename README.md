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
