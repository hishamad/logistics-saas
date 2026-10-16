"""Create a local development company, user and operation (never for production).

    uv run python scripts/seed_dev.py

Idempotent: running it again resets the demo company's operation to the full
synthetic scenario. The login below is a local test account for this machine only.
"""

from pathlib import Path

from sqlalchemy import select

from freight.api.db import Company, Database, Operation, User
from freight.api.security import hash_password
from freight.domain.models import Snapshot
from freight.settings import get_settings

DEV_COMPANY = "Demo Carrier (synthetic)"
DEV_USERS = [
    # (email, name, role, password) - local development accounts only
    ("admin@demo.test", "Demo Admin", "admin", "demo-admin-2026"),
    ("dispatcher@demo.test", "Demo Dispatcher", "dispatcher", "demo-dispatch-2026"),
    ("viewer@demo.test", "Demo Viewer", "viewer", "demo-viewer-2026"),
]
SCENARIO = (
    Path(__file__).resolve().parents[2] / "data" / "saudi" / "scenarios" / "full" / "snapshot.json"
)


def main() -> None:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    database = Database(url)
    snapshot = Snapshot.model_validate_json(SCENARIO.read_text(encoding="utf-8"))
    with database.session.begin() as db:
        company = db.scalar(select(Company).where(Company.name == DEV_COMPANY))
        if company is None:
            company = Company(name=DEV_COMPANY)
            db.add(company)
            db.flush()
        for email, name, role, password in DEV_USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                db.add(
                    User(
                        company_id=company.id,
                        email=email,
                        name=name,
                        role=role,
                        password_hash=hash_password(password),
                    )
                )
        operation = db.get(Operation, company.id)
        if operation is None:
            db.add(Operation(company_id=company.id, snapshot=snapshot.model_dump_json()))
        else:
            operation.snapshot = snapshot.model_dump_json()
            operation.version += 1
    print(f"Seeded {DEV_COMPANY}: {len(snapshot.teams)} trucks, {len(snapshot.jobs)} jobs")
    print("Local test logins are listed in scripts/seed_dev.py")


if __name__ == "__main__":
    main()
