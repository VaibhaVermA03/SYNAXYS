"""Run the retention cleanup once:  python -m app.scripts.cleanup [--dry-run]

Use this from an external scheduler (e.g. a Render Cron Job with the same environment as the API) when the worker is not
guaranteed to be running continuously. Exit code 1 if any rule failed. Prints counts only, never row contents."""
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine
from app.services.retention import run_cleanup


def main(argv: list[str]) -> int:
    s = get_settings()
    configure_logging(s.log_level)
    result = run_cleanup(SessionLocal, s, dry_run="--dry-run" in argv, engine=engine)
    print(json.dumps(result))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
