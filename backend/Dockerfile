FROM python:3.12-slim

    ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/backend \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates nodejs npm openssh-client xauth xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g playwright@1.60.0 \
    && npx playwright install --with-deps chromium \
    && npm cache clean --force

WORKDIR /workspace/backend

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY browser-runners/package*.json /workspace/browser-runners/
COPY publisher-worker/package*.json /workspace/publisher-worker/
COPY assets /workspace/assets

RUN cd /workspace/browser-runners \
    && npm ci \
    && cd /workspace/publisher-worker \
    && npm ci \
    && npx playwright install --with-deps chromium

COPY browser-runners /workspace/browser-runners
COPY publisher-worker /workspace/publisher-worker

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e '.[dev]'

EXPOSE 8765

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
