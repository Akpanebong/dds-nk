# DDS-NK THRIVE Integrated Management System

Django starter implementation for a centralized DDS-NK THRIVE platform covering:
- MEAL / M&E: data collection, verification, quality control, tracking, analysis and reporting.
- Procurement: vendors, requests, approvals, awards and procurement tracking.
- HR: staff records, performance tracking and HR documentation.

## Run in PyCharm / terminal

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

For local settings, copy `.env.example` to `.env` and keep
`DJANGO_DEBUG=1`. The settings module loads that file automatically; never
commit `.env` or place production secrets in the repository.

## Deployment

Install the pinned deployment dependencies and configure environment variables
from `.env.example` in the hosting platform's secret/configuration store. For
production, set `DJANGO_DEBUG=0`, provide a long random `DJANGO_SECRET_KEY`,
set `APP_BASE_URL` and `DJANGO_ALLOWED_HOSTS`, and use a PostgreSQL
`DATABASE_URL`. Do not use `DJANGO_ALLOW_SQLITE` in a multi-instance or
ephemeral deployment.

Run the release commands before starting the web process:

```bash
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
```

`STATIC_ROOT` is served by WhiteNoise. Configure persistent storage or an
external object-storage backend for `MEDIA_ROOT` if users upload files.

## FY26 MEAL tracker

The MEAL workspace is backed by the unified `meal` app and follows the FY26 workbook hierarchy: outcome, output, activity and indicator. Load or refresh the attached workbook with:

```bash
python manage.py load_fy26_tracker "Activity Tracker FY26.xlsx"
```

Each activity is classified as a people or non-people activity. People activities capture the workbook's sex, age and PWD disaggregation; non-people activities capture period progress, status and comments. Submissions enter a review queue and notify the MEAL Head group.

The reusable `notifications` app provides in-app notifications plus optional email delivery through `notifications.services.notify_user`, `notify_users` and `notify_group`.

Open http://127.0.0.1:8000/ . The login page is the staff entry point. After login, staff land on a module selector and can open MEAL, Procurement or HR depending on their permissions.

## Permissions
Use Django groups in `/admin/`:
- DDS-NK Management
- MEAL Team
- Procurement Team
- HR Team
- Data Entry

The system also allows module access flags on the staff profile. A superuser has all access.

## Notes
This is a production-oriented foundation: the data model, authentication, dashboards, audit logging, role-aware navigation, responsive Bootstrap UI, reusable template tags, signals and reporting foundations are included. Before production deployment, configure PostgreSQL, environment secrets, email/storage, HTTPS, backups and organization-specific approval rules.
