# AImagician Deployment

This directory contains deployment examples for a single-admin AImagician runtime.

## Files

- `aimagician.env.example`: environment template for local or `systemd --user` deployment.
- `systemd/aimagician-api.service.example`: API service example that binds to private host/port from env.
- `systemd/aimagician-worker.service.example`: allowlisted job worker example.
- `../bin/aimagician-backend`: operational wrapper for install, migrate, bootstrap, doctor, serve, smoke, and one-shot worker actions.

## Minimal Private Server Flow

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
bin/aimagician-backend install
cp deploy/aimagician.env.example ~/.config/aimagician/aimagician.env
$EDITOR ~/.config/aimagician/aimagician.env
AIMAGICIAN_ENV_FILE=~/.config/aimagician/aimagician.env bin/aimagician-backend migrate
AIMAGICIAN_ENV_FILE=~/.config/aimagician/aimagician.env bin/aimagician-backend bootstrap-admin
AIMAGICIAN_ENV_FILE=~/.config/aimagician/aimagician.env bin/aimagician-backend doctor
AIMAGICIAN_ENV_FILE=~/.config/aimagician/aimagician.env bin/aimagician-backend serve
```

## systemd --user

```bash
mkdir -p ~/.config/aimagician ~/.config/systemd/user
cp deploy/aimagician.env.example ~/.config/aimagician/aimagician.env
cp deploy/systemd/aimagician-api.service.example ~/.config/systemd/user/aimagician-api.service
cp deploy/systemd/aimagician-worker.service.example ~/.config/systemd/user/aimagician-worker.service
systemctl --user daemon-reload
systemctl --user enable --now aimagician-api.service
systemctl --user enable --now aimagician-worker.service
systemctl --user status aimagician-api.service
journalctl --user -u aimagician-worker.service -f
journalctl --user -u aimagician-api.service -f
```

## Docker Compose

For the private LAN server, use Docker Compose from the repository root:

```bash
mkdir -p ~/.config/aimagician
cp deploy/aimagician.env.example ~/.config/aimagician/aimagician-docker.env
$EDITOR ~/.config/aimagician/aimagician-docker.env
cd backend/deploy
sudo --preserve-env=AIMAGICIAN_DOCKER_ENV_FILE,POSTGRES_PASSWORD,AIMAGICIAN_BIND_HOST,AIMAGICIAN_PUBLISHED_PORT \
  docker compose up -d --build postgres api worker publisher_worker
sudo --preserve-env=AIMAGICIAN_DOCKER_ENV_FILE,POSTGRES_PASSWORD \
  docker compose run --rm api alembic upgrade head
sudo --preserve-env=AIMAGICIAN_DOCKER_ENV_FILE,POSTGRES_PASSWORD \
  docker compose run --rm api python -m app.cli bootstrap-admin
curl --fail http://127.0.0.1:8765/api/health
```

The compose file mounts the repository at `/workspace` for source hot reload, backend-owned browser runners, and the TypeScript publisher worker. Article production and publishing jobs must use backend-native handlers through the API/MCP contract. Browser platform publishing is executed by `publisher_worker` through Postgres `publisher_worker_jobs`; Python workers must not spawn Node browser runners directly. The default host port is `8775` to avoid colliding with other local services on `8765`.
If the host only has Compose v1 installed, replace `docker compose` with `docker-compose`. The repository root `.dockerignore` intentionally whitelists only backend build inputs so deploy builds do not stream credentials, browser profiles, generated blogs, or large media artifacts into the Docker build context.

## Doctor

```bash
AIMAGICIAN_ENV_FILE=~/.config/aimagician/aimagician.env bin/aimagician-backend doctor
```

The doctor reports settings safety, artifact writability, database reachability, Alembic revision, admin existence, worker queue state, and command hints. It redacts database passwords.

## Deep Research Worker Env

Article-flow `run_research` actions enqueue a backend-native `deep_research` worker job. Configure provider keys in the same env file used by the API and worker:

- `TAVILY_API_KEYS` / `TAVILY_API_KEY_FALLBACK`: comma-separated Tavily keys. The backend research worker tries keys in order and classifies quota/auth/network failures.
- `BRAVE_SEARCH_API_KEYS`: fallback official search API keys.
- `SEARXNG_BASE_URL`: optional self-hosted/open-source fallback before DDG HTML.
- `OPENCLAW_DEEP_RESEARCH_PROVIDER=auto`: compatibility env name for the provider chain. The default chain is Tavily -> Brave -> SearXNG -> DDGS -> DDG HTML when configured.

The worker stores final evidence and provider diagnostics as article artifacts when the run is linked to an article. Quality gates block continuation when evidence is empty/under the configured minimum or when article word count falls below the confirmed lower bound.

## Agent MCP Auth

After the API service is healthy, issue a short-lived agent access token from a configured refresh token:

```bash
export AIMAGICIAN_API_BASE_URL=http://127.0.0.1:8765
export AIMAGICIAN_AGENT_REFRESH_TOKEN='replace-with-allowlisted-refresh-token'
ACCESS_TOKEN="$(
  curl --fail -sS "$AIMAGICIAN_API_BASE_URL/api/auth/agent-token/refresh" \
    -H 'Content-Type: application/json' \
    -d "{\"refresh_token\":\"$AIMAGICIAN_AGENT_REFRESH_TOKEN\",\"label\":\"main-agent\",\"scopes\":[\"mcp\"]}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
)"
curl --fail -sS "$AIMAGICIAN_API_BASE_URL/api/mcp/capabilities" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Agents should use the MCP streamable HTTP endpoint at `/mcp` with the same Bearer token. If a token expires, refresh it through `/api/auth/agent-token/refresh` and retry the same MCP call once. Runtime state must come from AImagician API/MCP responses.

## Backup Basics

- Database: use `pg_dump "$AIMAGICIAN_DATABASE_URL"` from a shell where the env file is loaded.
- Artifacts: back up `AIMAGICIAN_ARTIFACT_ROOT`.
- Secrets: back up the ignored env file through your local password manager or encrypted backup. Do not commit it.

## Boundary

This pack intentionally stays single-host and private-network oriented. Public multi-user hosting, Kubernetes, and publisher rewrites are outside v3 Phase 123.
