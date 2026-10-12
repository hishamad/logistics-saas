FROM python:3.13-slim AS build
RUN pip install --no-cache-dir uv==0.11.7
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY backend/scripts ./scripts
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
RUN useradd --uid 10001 --create-home freight
WORKDIR /app
COPY --from=build --chown=freight:freight /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER freight
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "freight.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
