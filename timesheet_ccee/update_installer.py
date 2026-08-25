from __future__ import annotations

import argparse
import json
from pathlib import Path

from .updater import run_installer


def main() -> int:
    parser = argparse.ArgumentParser(description="Instalador do Timesheet CCEE")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--relaunch", required=True)
    arguments = parser.parse_args()
    relaunch = json.loads(arguments.relaunch)
    if not isinstance(relaunch, list) or not all(
        isinstance(part, str) for part in relaunch
    ):
        parser.error("--relaunch precisa ser uma lista JSON de strings")
    return run_installer(
        archive=arguments.archive,
        version=arguments.version,
        target=arguments.target,
        parent_pid=arguments.parent_pid,
        relaunch=relaunch,
    )


if __name__ == "__main__":
    raise SystemExit(main())
