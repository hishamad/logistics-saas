"""Operator commands for running the product (not for carriers).

    uv run freight-admin create-company --name "Carrier" --admin-email a@b.sa \
        --admin-name "Name" --fleet fleet.xlsx [--orders orders.xlsx] \
        --start "2026-10-20 06:00" [--days 2]

The admin's first password is read from FREIGHT_ADMIN_PASSWORD or asked for, never
taken on the command line (it would end up in shell history).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

from freight.api.db import Company, Database, Operation, User, new_id
from freight.api.security import hash_password
from freight.onboarding import OnboardingError, new_operation
from freight.settings import get_settings
from freight.sheets import SheetError, parse_time


def create_company(args: argparse.Namespace) -> int:
    start = parse_time(args.start)
    if start is None:
        print(f"Cannot read the start time {args.start!r} (use 2026-10-20 06:00, Riyadh time)")
        return 2
    password = os.environ.get("FREIGHT_ADMIN_PASSWORD") or getpass.getpass(
        "Admin's first password: "
    )
    if len(password) < 10:
        print("The password needs at least 10 characters.")
        return 2
    # Check everything before writing anything: a bad file leaves no half-made company.
    company_id = new_id()
    fleet = Path(args.fleet)
    orders = Path(args.orders) if args.orders else None
    try:
        snapshot, summary = new_operation(
            company_id,
            args.name,
            (fleet.name, fleet.read_bytes()),
            start,
            args.days,
            (orders.name, orders.read_bytes()) if orders else None,
        )
    except (OnboardingError, SheetError) as error:
        print(f"Nothing was created. {error}")
        return 1
    database = Database(args.database or get_settings().database_url)
    email = args.admin_email.strip().lower()
    with database.session.begin() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"Nothing was created. {email} already has an account.")
            return 1
        db.add(Company(id=company_id, name=args.name))
        db.flush()
        db.add(Operation(company_id=company_id, snapshot=snapshot.model_dump_json()))
        db.add(
            User(
                company_id=company_id,
                email=email,
                name=args.admin_name,
                role="admin",
                password_hash=hash_password(password),
            )
        )
    print(
        f"Created {args.name}: {summary['trucks']} trucks, {summary['orders']} orders. "
        f"{email} can sign in and add the other users under Settings."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freight-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-company", help="Set up a new carrier and its admin")
    create.add_argument("--name", required=True)
    create.add_argument("--admin-email", required=True)
    create.add_argument("--admin-name", required=True)
    create.add_argument("--fleet", required=True, help="Fleet .xlsx/.csv in the product template")
    create.add_argument("--orders", help="Orders .xlsx/.csv (optional; can be uploaded later)")
    create.add_argument("--start", required=True, help="Planning window start, Riyadh time")
    create.add_argument("--days", type=int, default=2, choices=range(1, 8))
    create.add_argument("--database", help="Database URL (default: from settings)")
    args = parser.parse_args(argv)
    return create_company(args)


if __name__ == "__main__":
    sys.exit(main())
