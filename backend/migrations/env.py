from alembic import context
from sqlalchemy import create_engine

from freight.db import Base
from freight.settings import get_settings

engine = create_engine(get_settings().database_url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
