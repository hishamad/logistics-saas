"""Explicit operator-only provisioning. This command has no HTTP equivalent."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete

from freight.db import Audit, LoginSession, Membership, Revision, Tenant, Workspace, session_factory
from freight.domain.models import Snapshot
from freight.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision reviewed workspaces and OIDC memberships"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-workspace")
    create.add_argument("--snapshot", type=Path, required=True)
    create.add_argument("--name", required=True)
    for name in ("grant", "revoke"):
        command = commands.add_parser(name)
        command.add_argument("--tenant", required=True)
        command.add_argument("--subject", required=True)
        if name == "grant":
            command.add_argument("--role", choices=["viewer", "dispatcher"], required=True)
    commands.add_parser("expire-sessions")
    args = parser.parse_args()
    with session_factory().begin() as db:
        if args.command == "create-workspace":
            if args.snapshot.stat().st_size > 2_000_000:
                parser.error("Snapshot limit is 2 MB")
            snapshot = Snapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
            if not 1 <= len(args.name) <= 150:
                parser.error("Workspace name must contain 1–150 characters")
            if db.get(Tenant, snapshot.tenant_id):
                parser.error("Workspace already exists; provisioning cannot overwrite it")
            db.add(Tenant(id=snapshot.tenant_id, name=args.name))
            db.flush()
            data = snapshot.model_dump(mode="json")
            db.add(Workspace(tenant_id=snapshot.tenant_id, version=1, data=data))
            db.add(
                Revision(
                    tenant_id=snapshot.tenant_id,
                    version=1,
                    data=data,
                    fingerprint=snapshot.fingerprint,
                    reason="Operator provisioned reviewed snapshot",
                )
            )
            db.add(
                Audit(
                    tenant_id=snapshot.tenant_id,
                    actor="operator-cli",
                    kind="workspace_provisioned",
                    data={"fingerprint": snapshot.fingerprint},
                )
            )
        elif args.command == "expire-sessions":
            db.execute(delete(LoginSession).where(LoginSession.expires_at <= datetime.now(UTC)))
        else:
            issuer = get_settings().oidc_issuer
            if not issuer or len(issuer) > 255 or not 1 <= len(args.subject) <= 255:
                parser.error(
                    "Configure OIDC_ISSUER and supply the exact provider subject (1–255 characters)"
                )
            if db.get(Tenant, args.tenant) is None:
                parser.error("Unknown workspace")
            member = db.get(Membership, (args.tenant, issuer, args.subject))
            if args.command == "grant":
                if member:
                    member.role, member.active = args.role, True
                else:
                    db.add(
                        Membership(
                            tenant_id=args.tenant,
                            issuer=issuer,
                            subject=args.subject,
                            role=args.role,
                            active=True,
                        )
                    )
            elif member:
                member.active = False
                db.execute(
                    delete(LoginSession).where(
                        LoginSession.tenant_id == args.tenant,
                        LoginSession.issuer == issuer,
                        LoginSession.subject == args.subject,
                    )
                )
            db.add(
                Audit(
                    tenant_id=args.tenant,
                    actor="operator-cli",
                    kind=f"membership_{args.command}",
                    data={
                        "issuer": issuer,
                        "subject": args.subject,
                        "role": getattr(args, "role", None),
                    },
                )
            )
    print("Operation committed.")


if __name__ == "__main__":
    main()
