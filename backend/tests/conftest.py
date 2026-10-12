import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from freight.db import session_factory
from freight.settings import get_settings


@pytest.fixture
def clients(monkeypatch):
    url = os.environ.get("FREIGHT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FREIGHT_TEST_DATABASE_URL for real PostgreSQL integration tests")
    schema = "freight_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL", scoped.render_as_string(hide_password=False))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_MODEL_RULES", "")
    get_settings.cache_clear()
    session_factory.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    from freight.api.app import app

    try:
        with (
            TestClient(app, headers={"X-Freight-Request": "1"}) as eastern,
            TestClient(app, headers={"X-Freight-Request": "1"}) as western,
        ):
            assert (
                eastern.post("/api/session", json={"tenant_id": "eastern-demo"}).status_code == 200
            )
            assert (
                western.post("/api/session", json={"tenant_id": "western-demo"}).status_code == 200
            )
            yield eastern, western
    finally:
        session_factory().kw["bind"].dispose()
        session_factory.cache_clear()
        get_settings.cache_clear()
        # The generated schema above is owned solely by this test invocation.
        assert schema.startswith("freight_test_") and schema[13:].isalnum()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
