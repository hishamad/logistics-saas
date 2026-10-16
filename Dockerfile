# One container runs the whole product: the API, the planning engine and the web app.
# NOTE: written without Docker available to test it (16 Oct 2026); build and smoke-test
# before relying on it.

# --- 1. Build the web app ------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY web/ ./
RUN npm run build

# --- 2. The Python service ----------------------------------------------------------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --extra postgres
COPY data/saudi /app/data/saudi
COPY --from=web /web/dist /app/web/dist

RUN useradd --create-home madar && mkdir -p /app/backend/.data && chown madar /app/backend/.data
USER madar
ENV ENVIRONMENT=production
EXPOSE 8000
# One web worker: plans run in its own process pool (PLAN_WORKERS), and a restarted
# worker fails runs it can no longer finish. Behind a proxy, set FORWARDED_ALLOW_IPS
# to the proxy's address so sign-in throttling sees real client addresses.
CMD ["uv", "run", "--no-sync", "uvicorn", "freight.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
