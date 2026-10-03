# AImagician Backend

AImagician backend is the API, database, and MCP server for the self-media operations console.

The web console lives in `../frontend`. Platform login state stays on your machine and is never part of this repository.

## Local Setup

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765
```

The operational wrapper provides the same flow with deployment diagnostics:

```bash
bin/aimagician-backend install
bin/aimagician-backend migrate
bin/aimagician-backend bootstrap-admin
bin/aimagician-backend doctor
bin/aimagician-backend serve
```

## Required Environment

The first skeleton only reads configuration. Database connectivity and migrations are implemented in the next plan.

```bash
AIMAGICIAN_APP_ENV=local
AIMAGICIAN_DATABASE_URL=postgresql+psycopg://aimagician:aimagician@127.0.0.1:5432/aimagician
AIMAGICIAN_SESSION_SECRET=replace-with-a-long-random-secret
```

Never commit `.env`.

## Database Bootstrap

Create a local PostgreSQL database, set `AIMAGICIAN_DATABASE_URL`, then run migrations:

```bash
cd backend
. .venv/bin/activate
alembic upgrade head
```

If PostgreSQL is not available, migration SQL can still be inspected without connecting:

```bash
alembic upgrade head --sql
```

## Admin Bootstrap

After migrations, create or rotate the single admin account:

```bash
python -m app.cli bootstrap-admin \
  --email admin@example.com \
  --display-name "AImagician Admin" \
  --password "$AIMAGICIAN_ADMIN_PASSWORD"
```

Use `--rotate-password` only when intentionally replacing an existing admin password.

## Verification

```bash
cd backend
python -m compileall app
python -m pytest
alembic upgrade head --sql >/tmp/aimagician-alembic.sql
curl http://127.0.0.1:8765/api/health
python -m app.cli doctor --fail-on-error
```

## Private Deployment

Deployment examples live in [`deploy/`](./deploy/):

- `deploy/aimagician.env.example` for ignored local runtime config.
- `deploy/systemd/aimagician-api.service.example` for a `systemd --user` private API service.
- `bin/aimagician-backend` for install, migrate, bootstrap, doctor, serve, smoke, and one-shot worker commands.

The deployment doctor reports settings safety, artifact root writability, database reachability, Alembic revision, admin existence, worker queue state, and command hints. It redacts database passwords and is the first command to run before wiring OpenClaw bridge env.

## Current Scope

Current backend scope includes:

- FastAPI app factory, settings loading, API router, and health endpoint.
- SQLAlchemy models and Alembic migration setup for `users`, `admin_sessions`, and `audit_events`.
- Single-admin auth with Argon2id password hashing, HttpOnly SameSite session cookie, and `X-CSRF-Token` enforcement for state-changing requests.
