# Engineering Rules & Guidelines (AGENTS.md)

## 1. Project Context & Philosophy
This repository hosts the production management and booking system for **Bhagya Laxmi Library** (trade name: *Bhagya Laxmi Library & PG*).
- **Core Domain**: Paid AC study-seat / reading-room booking and membership lifecycle management.
- **Seat Inventory**: Exactly 150 fixed AC study seats numbered 1 to 150.
- **Pricing**: ₹800 per seat for a 30-day billing cycle.
- **Strict Scope Constraint**: This application is strictly for study-seat / reading-room management. **DO NOT** create or reference any PG, hostel, room, bed, or accommodation features.

---

## 2. Technology Stack & Hard Constraints

### Allowed Stack
- **Backend**: Python 3.12, Django 5.x (latest stable compatible with Python 3.12).
- **Database**: PostgreSQL 18 with modern `psycopg` (v3) driver.
- **Frontend Architecture**: Server-side rendered Django Templates + HTMX + Tailwind CSS.
- **Task Queue & Cache**: Celery + Redis.
- **Production Server**: Gunicorn + WhiteNoise / Nginx reverse proxy.
- **Testing**: Django `TestCase` / `pytest-django`.

### Strictly Prohibited
- **NO** React, Vue, Angular, Svelte, Next.js, or SPA frameworks.
- **NO** Separate frontend node server in production.
- **NO** Firebase / Supabase as the primary database (PostgreSQL only).
- **NO** Microservices architecture (Maintain a clean, modular monolith).
- **NO** Unapproved third-party dependencies. Keep the dependency footprint lean and audit-ready.

---

## 3. Architecture & Code Organization

### Directory Layout
```
bhagya-laxmi-library/
├── apps/                     # Modular Django apps
│   ├── core/                 # Health checks, landing, shared helpers, base models
│   ├── seats/                # Seat topology (1-150), statuses, seat grid (Phase 2+)
│   ├── members/              # Student/member profiles & KYC (Phase 2+)
│   ├── bookings/             # Seat allocations, 30-day validity, renewals (Phase 2+)
│   ├── payments/             # ₹800 fee payments, receipts, verification (Phase 2+)
│   └── complaints/           # Desk/facility issue ticketing (Phase 2+)
├── config/                   # Project configuration
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py           # Shared settings across all environments
│   │   ├── local.py          # Local development overrides
│   │   └── production.py     # Hardened production settings
│   ├── asgi.py
│   ├── celery.py
│   ├── urls.py
│   └── wsgi.py
├── static/                   # Static assets (compiled CSS, JS, images)
│   ├── css/
│   │   ├── input.css
│   │   └── output.css
│   └── js/
│       └── htmx.min.js
├── templates/                # Global Django templates
│   ├── base.html
│   ├── components/           # Reusable UI partials & HTMX fragments
│   └── pages/                # Full page views
├── requirements/             # Pinned dependency lists
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── .env.example              # Environment variables template
├── manage.py
├── package.json              # Tailwind CSS build scripts
└── tailwind.config.js
```

### Clean Architecture Principles
1. **Fat Models / Service Layer, Lean Views**:
   - Complex business calculations (seat validity dates, fee calculation, receipt numbering, seat auto-release) MUST reside in domain service modules (`apps/<app>/services.py`) or model methods.
   - Views should only handle request parsing, authentication checks, service orchestration, and template rendering.
2. **HTMX Partial vs Full Page Rendering**:
   - For HTMX requests (`request.htmx`), return focused partial HTML snippets or components.
   - For direct browser navigations, return full pages extending `base.html`.
3. **Database Integrity**:
   - Always define explicit `related_name` on ForeignKeys.
   - Use `select_related` and `prefetch_related` to eliminate N+1 queries.
   - Wrap multi-table state transitions (e.g. seat booking + payment creation) in `transaction.atomic()`.

---

## 4. Security & Quality Standards

1. **CSRF Protection**:
   - Never disable CSRF (`@csrf_exempt` is strictly prohibited on user-facing forms).
   - Global HTMX configuration must include the `X-CSRFToken` header.
2. **Secrets & Environment Variables**:
   - Never hardcode API keys, secrets, database passwords, or credentials.
   - Always read from environment variables via `django-environ`.
   - Ensure `.env` is listed in `.gitignore`.
3. **Static File Integrity**:
   - Vendored scripts (such as `htmx.min.js`) must be stored locally in `static/js/` to avoid external runtime CDN failures in production.

---

## 5. Testing & Verification Requirements
- Every new feature, endpoint, or model state transition must be backed by automated tests.
- Run `python manage.py test` before submitting any task.
- Tests must pass with zero failures and zero warnings.
