"""Run a local module with explicit dotenv values, overriding stale shell settings.

The repository-root .env takes precedence over backend/.env. Production containers
do not use this launcher; their process environment remains authoritative.
"""

import runpy
import sys

from dotenv import load_dotenv

from freight.settings import LOCAL_ENV_FILES


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/run_local.py MODULE [ARGUMENTS...]")
    for path in LOCAL_ENV_FILES:
        load_dotenv(path, override=True)
    target = sys.argv.pop(1)
    if target.endswith(".py"):
        runpy.run_path(target, run_name="__main__")
    else:
        runpy.run_module(target, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
