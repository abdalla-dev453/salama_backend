# SALAMA backend (Django REST Framework + PostgreSQL)

The server behind the SALAMA Flutter app. Survivors' phones send reports to it
(over the internet **or** by SMS through Africa's Talking), CHWs log in from the
app to see and work on cases, and admins use a web dashboard.

```
Survivor app ──HTTPS──▶  POST /api/intake/            ┐
Survivor SMS ──▶ Africa's Talking ──▶ POST /api/sms/…  ├─▶ Django + PostgreSQL ─▶ CHW app (JWT)
                                                       │                       ─▶ Admin web dashboard
```

## What is in it

| Part | What it does |
|---|---|
| `accounts` | One user table. Role `chw` or `admin`. A CHW's **username is the CHW ID** (e.g. `CHW-KWALE-001`). JWT login. |
| `cases` | Cases, audit trail, inbound SMS inbox, API, web dashboard, Django admin. |
| Idempotent intake | The phone makes the case ID (`KWALE-2710-A1B2C3`, `SOS-9F8E7D`). The same case arriving by SMS *and* by internet becomes one case, never two. |
| Encrypted at rest | Description, contact phone, notes and raw SMS text are encrypted in the database (Fernet). A stolen database dump does not expose survivors. |
| Audit trail | Every assignment, status change and note records who did it and when. |
| Rate limiting | Login, intake and SMS webhook are throttled (counters in the database, shared by all workers). |
| Data minimisation | `purge_old_cases` command deletes old closed cases and SMS. |

## Quick start on your computer (Docker)

```bash
cp .env.example .env
#  edit .env: set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, FIELD_ENCRYPTION_KEYS
#  and for local testing:  DJANGO_DEBUG=true  DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
docker compose up -d --build

docker compose exec web python manage.py createsuperuser      # your admin login
docker compose exec web python manage.py seed_demo            # the 4 Kwale CHWs (passwords printed ONCE)
```

Open `http://localhost:8000/` → staff dashboard. `http://localhost:8000/admin/` → Django admin.

### Without Docker
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# have a PostgreSQL database ready, then:
export DJANGO_DEBUG=true POSTGRES_PASSWORD=... POSTGRES_HOST=localhost
python manage.py migrate
python manage.py createcachetable
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8000
```

## Managing people

* **Admin accounts:** `python manage.py createsuperuser`.
* **CHWs:** Django admin → Users → Add (set *Role* = CHW, the username is the CHW ID),
  or the API (`POST /api/chws/`), or `seed_demo` for the four Kwale CHWs.
* **A CHW leaves:** untick *Active* (or `DELETE /api/chws/<id>/`). Their cases stay,
  their tokens stop working immediately. Never delete users: it removes the audit trail.
* **Password reset:** Django admin → the user → change password.

## Staff web dashboard (`/dashboard/`, admins only)
KPIs (total, urgent SOS, referred, closed), 30-day trend, cases by type, recent cases,
CHW workload, case list with filters and **Assign**. It deliberately does **not** show
descriptions or phone numbers; open the case in `/admin/` for those.

## Go live (a small VPS is enough)

1. Get a server (Ubuntu) and a domain, e.g. `api.yourdomain.org` pointing to it. Install Docker.
2. Copy this folder to the server, `cp .env.example .env`, fill it in (**DEBUG=false**,
   your real domain in `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`).
3. `docker compose up -d --build`
4. Put HTTPS in front. Easiest is Caddy (automatic certificates). `/etc/caddy/Caddyfile`:
   ```
   api.yourdomain.org {
       reverse_proxy 127.0.0.1:8000
   }
   ```
5. `createsuperuser` and `seed_demo` as above.
6. **Back up** the database (`docker compose exec db pg_dump -U salama salama > backup.sql`,
   daily) **and `FIELD_ENCRYPTION_KEYS` separately**. Without the key the encrypted text in a
   backup cannot be read. Do not store them together.
7. Run `python manage.py purge_old_cases --days 365 --dry-run` and, once you agree with it,
   schedule it (cron) weekly.

## Africa's Talking (SMS when there is no internet)

1. Create an Africa's Talking account, get an SMS **shortcode or long number** that can receive SMS.
2. Put that number in the Flutter app: `kServerNumber` in `lib/core/constants.dart`.
3. In Africa's Talking → SMS → Callback URLs → **Incoming messages**, set
   `https://api.yourdomain.org/api/sms/africastalking/?token=<AT_WEBHOOK_TOKEN>`
   (the token is the value you put in `.env`; without it the webhook refuses everything).
4. Test with the sandbox first (`AT_SANDBOX=true`, `AT_USERNAME=sandbox`).
5. Optional: set `AT_USERNAME`, `AT_API_KEY` and `NOTIFY_CHWS_ON_SOS=true` to text every CHW
   with a phone number when an SOS arrives (the text contains only the reference, no personal data).

SMS formats the app sends (parsed by `cases/parsing.py`):
```
SALAMA:<ref>|<V|A|C|SOS>|<location>|<lat>,<lon>[|<contact>|<safe 1/0>]      NA,NA = no GPS
SOS! <ref> <location> [https://maps.google.com/?q=<lat>,<lon>]
```
Messages that do not match are kept in *Django admin → Inbound SMS* (`parsed = False`) for a person to read.

## API (all JSON)

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/intake/` | survivor app (no login, optional `X-Salama-Key`) | Upload one case. Idempotent by `case_ref`. |
| `POST /api/sms/africastalking/?token=…` | Africa's Talking | Incoming SMS. |
| `POST /api/auth/login/` `{username, password}` | CHW/admin | → `{access, refresh, user}` (CHW ID is case-insensitive) |
| `POST /api/auth/refresh/` `{refresh}` | | → `{access}` |
| `GET /api/auth/me/` | staff | Who am I |
| `GET /api/cases/?scope=mine\|unassigned\|open\|urgent&status=&type=&search=&page=` | staff | Paginated list. CHW sees own + unassigned; admin sees all. SOS first. |
| `GET /api/cases/<id>/` | staff | Detail with timeline |
| `POST /api/cases/<id>/claim/` | staff | Take an unassigned case (409 if someone else has it) |
| `POST /api/cases/<id>/status/` `{status, note}` | staff | Change status (statuses: new, sos, responded, referred, followup, closed) |
| `POST /api/cases/<id>/note/` `{note}` | staff | Add a note |
| `POST /api/cases/<id>/assign/` `{chw: <user id> \| null}` | admin | Assign / unassign |
| `GET /api/stats/` | staff | KPI numbers + 30-day trend |
| `GET/POST/PATCH/DELETE /api/chws/` | admin | Manage CHW accounts (DELETE = deactivate) |
| `GET /api/health/` | anyone | Health check |

A CHW cannot open or change a case assigned to another CHW (404/403).

## Tests
```bash
python manage.py test        # 92 tests; needs the PostgreSQL settings above
```

## Security checklist before real survivors use it
- [ ] `DJANGO_DEBUG=false`, long random `DJANGO_SECRET_KEY`, HTTPS working (the app must use `https://`).
- [ ] `FIELD_ENCRYPTION_KEYS` set and backed up separately.
- [ ] Strong passwords for every CHW; remove accounts when people leave.
- [ ] Server disk encryption and restricted SSH (keys only).
- [ ] Agree who may see data with Utetezi; follow the Kenya Data Protection Act 2019
      (consent wording in the app, retention period, a named data controller, breach procedure).
- [ ] `SURVIVOR_API_KEY` is not a secret: the real defence against spam is the rate limit.
      Watch the *Inbound SMS* inbox and the case list for junk.

## Known limits
- Docker files were written for this project but **not run** in the environment where it was built
  (no Docker there); the code itself was tested with PostgreSQL 16 (92 unit tests and an end-to-end
  replay of the app's requests). Expect to fix small deployment details on first run.
- No push notifications: CHWs see new cases when they open or refresh the app (optional SOS SMS alert exists).
- No USSD yet (the flyer mentions `*483*87#`); Africa's Talking supports USSD and it can be added as another webhook.
