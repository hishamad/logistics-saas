#!/bin/sh
# Runs only when PostgreSQL initializes a new data volume. No secret is logged.
set -eu
app_password=$(cat /run/secrets/postgres_app_password)
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 --set=app_password="$app_password" <<'SQL'
CREATE ROLE freight_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE freight TO freight_app;
GRANT USAGE ON SCHEMA public TO freight_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE freight_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO freight_app;
ALTER DEFAULT PRIVILEGES FOR ROLE freight_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO freight_app;
SQL
unset app_password
