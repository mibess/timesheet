from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_in_default_app(path: str | Path) -> None:
    target = str(Path(path).expanduser().resolve())
    system = platform.system()
    if system == "Windows":
        os.startfile(target)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def reveal_in_file_manager(path: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(target)])
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target.parent)])
