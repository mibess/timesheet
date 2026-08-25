from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(path: Path, *, repository: str, tag: str) -> dict[str, str | int]:
    encoded_tag = quote(tag, safe="")
    encoded_name = quote(path.name, safe="")
    return {
        "url": (
            f"https://github.com/{repository}/releases/download/"
            f"{encoded_tag}/{encoded_name}"
        ),
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cria o update.json de um release")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--macos", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--notes", default="Consulte as notas do release para conhecer as novidades."
    )
    arguments = parser.parse_args()
    version = arguments.version.removeprefix("v")
    manifest = {
        "version": version,
        "notes": arguments.notes,
        "releaseUrl": f"https://github.com/{arguments.repository}/releases/tag/{quote(arguments.tag, safe='')}",
        "platforms": {
            "macos": package(
                arguments.macos,
                repository=arguments.repository,
                tag=arguments.tag,
            ),
            "windows": package(
                arguments.windows,
                repository=arguments.repository,
                tag=arguments.tag,
            ),
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
