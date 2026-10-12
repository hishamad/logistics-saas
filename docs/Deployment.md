# Deployment and release readiness

The code is prepared for a **single-host shadow-planning deployment**. It never publishes dispatch instructions. Local verification includes 56 backend tests, browser workflows, 16 live OpenAI cases and a PostgreSQL restore drill. This document separates that evidence from work that must happen on the chosen host. Docker is unavailable on the development machine, so container builds, TLS and a real OIDC provider have not been exercised here. The supplied CI builds both images, but hosted CI has not yet run.

## Configuration and isolation

Local startup remains loopback-only demo mode. `scripts/start-demo.ps1` uses `backend/scripts/run_local.py`: it reads `backend/.env`, then the repository-root `.env`, overriding inherited values for keys present in those files. This prevents a stale shell API key from hiding a replacement file value. Ordinary application settings give process environment values precedence; production containers do not run the local launcher or contain dotenv files.

Production mode requires an HTTPS origin and issuer, an OIDC client/secret, an explicit host allowlist, exactly one allowed browser origin, and a random session-signing secret of at least 32 characters. Known example placeholders are rejected. Demo workspace selection and seeding are disabled. Memberships use the verified `(issuer, subject)` pair, never an unverified email address. `dispatcher` may edit; `viewer` may read. Membership is checked on every request. Provision one workspace per identity for this first release: if an identity has multiple memberships, sign-in selects the first tenant ID alphabetically; a production workspace-switching UI is not implemented.

Only Caddy publishes host ports. The browser uses one origin; `/api/*` routes directly to the API. PostgreSQL, the worker and frontend are on a private Docker bridge. A fixed gateway address restricts trusted proxy headers. If that subnet conflicts with the host network, change both the Compose subnet/address and the API's `--forwarded-allow-ips` setting together.

The API and worker use a non-superuser `freight_app` database role with table DML privileges. Only the migration service receives the owner connection string. Containers omit dotenv files, run the application as a non-root user with a read-only filesystem, and bound worker CPU/memory. Keep deployment files and secret files readable only by the operator; do not publish rendered Compose configuration, container environment output or database connection strings.

## Prepare the host

Use a maintained Linux host with Docker Engine and Compose v2, persistent storage, adequate CPU/RAM and outbound access to the configured identity provider and OpenAI. The measured 50-team/150-job scenario took about 47 seconds before queue delay on the development machine; benchmark the actual host before promising an SLA. DNS must resolve the public domain to the host, with ports 80 and 443 reachable for Caddy's certificate flow. Do not expose ports 3000, 8000 or 5432.

1. Copy `deploy/.env.example` to `deploy/.env` and replace every placeholder. Set the exact domain/origin, issuer, client credentials and signing secret. Generate independent random database owner and application passwords. Save their raw values in `deploy/secrets/postgres_owner_password` and `deploy/secrets/postgres_app_password`; use URL-encoded versions in the corresponding database URLs. Protect these files with restrictive permissions. The owner and runtime database URLs must point to the same `freight` database.
2. Register a confidential OIDC authorization-code client supporting PKCE S256. Its exact redirect URI is `https://YOUR_HOST/api/auth/callback`. Use the issuer from the provider's discovery metadata. Do not provision users by guessed email/subject mappings; obtain the provider's verified `sub` value.
3. For AI, use `OPENAI_MODEL_RULES=gpt-6-luna` and `OPENAI_REASONING_EFFORT=low`, with the private key in `deploy/.env`. It is optional for manual planning. Establish project spending limits and customer-data processing approval before sending real catalogs. The application limits AI attempts to 20 per workspace per ten minutes and does not automatically retry provider requests.
4. Build, inspect startup logs, and start the stack from the repository root:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml build
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml logs --tail=100 migrate api worker
```

The database initialization script creates the application role only for a **new** volume. Editing a password file later does not rotate an existing database password; rotate the role password and matching runtime configuration together. Migrations must complete before the API and worker start. Never remove the production volume to fix an initialization or migration error.

## Provision a reviewed workspace

Create an approved JSON `Snapshot` matching the API/domain schema. Set `mode` to `shadow`, give it an explicit tenant ID, confirmed fixed teams, timezone-aware calendars, real lane provenance and approved costs. Missing costs stay missing and disable cash comparisons; fixture rates are never supplied automatically. The CLI refuses to overwrite an existing tenant. This is an operator action, not a public API.

Save the approved file under an operator-controlled `deploy/provisioning/` directory. Keep customer data outside Git. Example Linux commands, with real tenant/subject values substituted:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm --no-deps \
  -v "$PWD/deploy/provisioning:/provisioning:ro" api \
  python -m freight.admin create-workspace --snapshot /provisioning/reviewed.json --name "Approved workspace"

docker compose --env-file deploy/.env -f deploy/compose.yaml exec api \
  python -m freight.admin grant --tenant TENANT_ID --subject VERIFIED_SUBJECT --role dispatcher

docker compose --env-file deploy/.env -f deploy/compose.yaml exec api \
  python -m freight.admin grant --tenant TENANT_ID --subject VIEWER_SUBJECT --role viewer
```

To revoke access immediately, use the same command with `revoke --tenant ... --subject ...`. Existing sessions are invalidated; membership changes also take effect on the next request. `python -m freight.admin expire-sessions` removes expired session records. Run it through your host's operations scheduler. The application does not self-delete revisions, imports, idempotency records or audit history; agree retention and encrypted storage capacity before customer onboarding.

## Commission the release

On a separate staging stack with synthetic data, verify a real SSO login, logout, viewer write denial, revoked access, absent demo endpoints and a healthy HTTPS `/health`. Check that a second tenant cannot fetch another tenant's run/import/proposal. Run a job import, manual rule, real AI proposal/approval and worker solve through the browser. Review Arabic rendering with an Arabic-speaking dispatcher.

Observe a worker restart while a run is active: an expired lease can be reclaimed, old attempts cannot write results, and a run stops retrying after three claims. A cancellation immediately prevents result acceptance, although the bounded calculation may finish before the worker takes its next task. API shutdown/restart should preserve revisions and idempotency. Verify a temporary database outage and recovery on staging, never by stopping a live customer database without a maintenance window.

Health checks test database access and detect queued work older than five minutes or an expired worker lease older than one minute. A healthy idle queue does not prove a worker is alive; include a synthetic planning canary in monitoring. Alert on sustained health failures, failed runs, queue age, disk space, backup age and resource saturation. Set the first alert thresholds from measured staging behavior. Request logs include a generated request ID, method, path, status and duration; no bodies, tokens or query strings are logged by the configured API command. Database and reverse-proxy logs still require normal access control and retention.

## Backups, upgrades and recovery

The local `scripts/verify-backup.ps1` created a custom-format `pg_dump`, restored it into a fresh disposable database, read the restored records/migration version, and removed only that disposable database. Evidence is in `backup-verification.json`. This does not establish off-host durability or a recovery-time objective.

Before customer use, arrange encrypted off-host backups with an agreed retention period and recovery point/time objective. Use PostgreSQL 17 client tools for the production PostgreSQL 17 service. Back up the application database and retain separately protected deployment secrets/configuration and role provisioning instructions. Restore to a **new isolated staging database**, verify counts and representative revision hashes, apply necessary role grants, then run login/import/planning checks before considering any recovery cutover. Preserve the original database until the replacement is accepted.

For upgrades, record immutable image digests, take/verify a backup, stop acceptance of new planning work during incompatible schema changes, then run the migration and deploy compatible API/worker/frontend images together. Do not blindly run Alembic downgrade on a populated database. Prefer a forward repair or restoration to a new database if a migration is not backward compatible. The current identity migration is additive, but that does not guarantee future downgrades are lossless.

## Release decision

The synthetic MVP is verified, including real AI. Customer production approval still requires a successful container/host/SSO commissioning run, owned monitoring and backups, an agreed operational policy and update path, and representative customer validation. Lane accuracy, freshness, driver-hour/rest policies and commercial savings cannot be established by synthetic tests. No live dispatch/publication release is included in this implementation.
