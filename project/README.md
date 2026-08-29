# Bhagya Laxmi Library

A Django application (server-rendered HTML + HTMX) for study-seat booking and
reading-room management.

## Why this layout

This is a **monolithic Django app** — Django renders the HTML pages directly,
there's no separate JSON API. Because of that, `frontend/` and `backend/` are
organized into separate folders for clarity, but they still run as a **single
Django process** at deploy time (Django reads templates/CSS/JS straight out of
`frontend/` — see `FRONTEND_DIR` in `backend/config/settings/base.py`).

```
.
├── backend/          # Django project: apps, config, manage.py, requirements
│   ├── apps/
│   ├── config/
│   ├── manage.py
│   ├── requirements/
│   ├── db.sqlite3        (local dev only, gitignored)
│   └── media/             (user uploads, gitignored)
└── frontend/          # Templates + static assets + Tailwind build tooling
    ├── templates/
    ├── static/
    ├── tailwind.config.js
    └── package.json
```

## Prerequisites

- Python 3.12
- Node.js (for the Tailwind CSS build)
- PostgreSQL 18 (or use SQLite locally if you skip `DATABASE_URL` — see notes below)
- Redis (for Celery — seat-hold expiry, grace-period checks, renewal reminders)

## First-time setup

### 1. Backend (Django) — from `backend/`

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements/local.txt

cp .env.example .env
```

Now open `.env` and fill in your real values — at minimum:

- `DJANGO_SECRET_KEY` — any long random string for local dev
- `DATABASE_URL` — your Postgres connection string (or point it at a local Postgres you've created)
- `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` — your local Redis instance
- `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` — needed for OTP emails (password change/reset flows send real emails). For local testing without SMTP, you can set `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` to print OTP emails to your terminal instead.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — only needed if you're testing Google OAuth login for students
- **`ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_PHONE_NUMBER`** — the admin/owner account's login credentials. `ADMIN_EMAIL` is the single source of truth for the admin email (the admin login page rejects any other email); `ADMIN_PASSWORD` is only used to create the account the first time — after that, change your password from the admin dashboard, and that new password sticks even if you rerun the seed command later.

Then run:

```bash
python manage.py migrate
python manage.py seed_admin
python manage.py runserver
```

- `migrate` creates the database schema (and seeds the 150 library seats via the `seats` app migration).
- `seed_admin` creates the one admin/owner account from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in your `.env`. Safe to re-run any time — it only creates the account if it doesn't exist yet, and otherwise just keeps the email in sync with `.env` without ever touching the password.
- `runserver` starts the app at **http://127.0.0.1:8000/** — Django automatically pulls templates and static files from the sibling `frontend/` folder.

Log in to the admin portal at **http://127.0.0.1:8000/admin-portal/login/** with the `ADMIN_EMAIL` / `ADMIN_PASSWORD` from your `.env`, then go to **Change Password** in the dashboard to set your own password for future logins.

### 2. Frontend (Tailwind CSS build) — from `frontend/`, in a second terminal

```bash
cd frontend
npm install
npm run watch:css     # rebuilds static/css/output.css on change
# or: npm run build:css   for a one-off minified build
```

### 3. Background jobs (Celery) — from `backend/`, in additional terminals

The app relies on Celery + Redis for automatic seat-hold expiry, grace-period
checks, and renewal reminders (see the schedule in `backend/config/celery.py`).
Make sure Redis is running locally, then start a worker and beat scheduler:

```bash
# Terminal 3 — worker
cd backend
source .venv/bin/activate
celery -A config worker -l info

# Terminal 4 — beat (scheduler)
cd backend
source .venv/bin/activate
celery -A config beat -l info
```

These aren't strictly required just to click around the site, but seat holds
won't auto-expire and reminder emails won't fire without them.

## Everyday local dev (after the first-time setup above)

```bash
# Terminal 1
cd backend && source .venv/bin/activate && python manage.py runserver

# Terminal 2
cd frontend && npm run watch:css

# Terminal 3 / 4 (optional, for background jobs)
cd backend && source .venv/bin/activate && celery -A config worker -l info
cd backend && source .venv/bin/activate && celery -A config beat -l info
```

## Deployment

Since this is one Django process, you deploy **one artifact that contains
both folders** (e.g. one Docker image / one server). The split just keeps
the codebase organized:

1. Build frontend assets first: `cd frontend && npm install && npm run build:css`
2. From `backend/`: `python manage.py collectstatic --noinput` — this gathers
   `frontend/static/**` + each Django app's own static files into
   `backend/staticfiles/`, which Whitenoise serves in production.
3. Run `python manage.py migrate` and `python manage.py seed_admin` against
   the production database, using production values for `ADMIN_EMAIL` /
   `ADMIN_PASSWORD` — then log in once and change the password immediately.
4. Run Django as usual, e.g. `gunicorn config.wsgi:application` from `backend/`,
   with `DJANGO_SETTINGS_MODULE=config.settings.production`.

Keep `frontend/` and `backend/` in the same deployment (same container /
same server), since Django needs `frontend/templates` and `frontend/static`
at runtime (and at collectstatic time) to serve pages.

> If you later want frontend and backend to be **truly independent
> deployments** (e.g. a React app on Vercel calling a Django REST API), that
> requires converting the Django views into a JSON API (Django REST
> Framework) and rebuilding the templates as a JS frontend — a larger,
> separate project.

## Admin credential model (quick reference)

- The admin portal only accepts the email in `ADMIN_EMAIL` (set in `.env`) — logins with any other email are rejected before a password is even checked.
- `python manage.py seed_admin` creates the account with `ADMIN_PASSWORD` the first time only.
- After first login, use **Admin Portal → Change Password** (OTP-verified via email) to set your real password — this is stored in the database and is never overwritten by `seed_admin` on later runs.
- If you rotate `ADMIN_EMAIL` in `.env`, rerunning `seed_admin` will rename the existing admin account to the new email (password stays whatever it currently is).