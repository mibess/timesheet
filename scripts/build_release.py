from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from timesheet_ccee import __version__  # noqa: E402
from timesheet_ccee.config import APP_NAME  # noqa: E402


COMMON_FILES = (
    "README.md",
    "requirements.txt",
    "run_timesheet.py",
    "settings.json",
    "Modelo_Timesheet_CCEE.template.xlsx",
)
PLATFORM_FILES = {
    "macos": ("INICIAR_TIMESHEET.command", "Abrir Timesheet.app"),
    "windows": ("INICIAR_TIMESHEET.cmd", "Abrir Timesheet.vbs"),
}
ARCHIVE_ROOT = "Timesheet-CCEE"


def source_paths(platform_name: str) -> list[Path]:
    paths = [PROJECT_ROOT / name for name in COMMON_FILES]
    paths.extend(PROJECT_ROOT / name for name in PLATFORM_FILES[platform_name])
    paths.extend(
        path
        for path in (PROJECT_ROOT / "timesheet_ccee").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    paths.extend(
        path
        for path in (PROJECT_ROOT / "assets").rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    )
    return paths


def add_path(archive: zipfile.ZipFile, path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Links simbólicos não são permitidos no release: {path}")
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.name != ".DS_Store":
                add_path(archive, child)
        return
    if not path.is_file():
        raise FileNotFoundError(path)
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    archive.write(path, f"{ARCHIVE_ROOT}/{relative}")


def add_json(archive: zipfile.ZipFile, name: str, payload: dict[str, object]) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{name}")
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def build_release(
    *, platform_name: str, output: Path, repository: str, version: str
) -> None:
    if version != __version__:
        raise RuntimeError(
            f"A tag informa {version}, mas o aplicativo informa {__version__}."
        )
    if "/" not in repository:
        raise RuntimeError("Informe o repositório no formato proprietário/nome.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        seen: set[Path] = set()
        for path in source_paths(platform_name):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            add_path(archive, path)
        add_json(
            archive,
            "update-config.json",
            {
                "manifestUrl": (
                    f"https://github.com/{repository}/releases/latest/download/"
                    "update.json"
                )
            },
        )
        add_json(
            archive,
            "release-info.json",
            {
                "application": APP_NAME,
                "version": version,
                "platform": platform_name,
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Monta um release do Timesheet CCEE")
    parser.add_argument("--platform", choices=sorted(PLATFORM_FILES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    build_release(
        platform_name=arguments.platform,
        output=arguments.output,
        repository=arguments.repository,
        version=arguments.version.removeprefix("v"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
