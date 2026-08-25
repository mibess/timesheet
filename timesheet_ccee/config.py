from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__


APP_NAME = "Timesheet CCEE"
APP_VERSION = __version__


@dataclass
class Preset:
    name: str
    hours: str


@dataclass
class AppSettings:
    default_activity_type: str = "Sustentação"
    default_ticket: str = "CSTM"
    default_observation: str = "Trabalhando nas atividades"
    expected_daily_hours: str = "08:00"
    presets: list[Preset] = field(
        default_factory=lambda: [
            Preset("Daily", "00:15"),
            Preset("Planning", "00:30"),
            Preset("Weekly", "00:30"),
            Preset("Chapter", "01:00"),
        ]
    )


def resource_path(filename: str) -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir) / filename
    return Path(__file__).resolve().parent.parent / filename


def application_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "TimesheetCCEE"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "TimesheetCCEE"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "TimesheetCCEE"


def load_settings() -> AppSettings:
    defaults = AppSettings()
    path = resource_path("settings.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return defaults

    presets = []
    for item in payload.get("presets", []):
        if isinstance(item, dict) and item.get("name") and item.get("hours"):
            presets.append(Preset(str(item["name"]), str(item["hours"])))

    return AppSettings(
        default_activity_type=str(
            payload.get("defaultActivityType", defaults.default_activity_type)
        ),
        default_ticket=str(payload.get("defaultTicket", defaults.default_ticket)),
        default_observation=str(
            payload.get("defaultObservation", defaults.default_observation)
        ),
        expected_daily_hours=str(
            payload.get("expectedDailyHours", defaults.expected_daily_hours)
        ),
        presets=presets or defaults.presets,
    )


def default_workbook_path() -> Path:
    template = resource_path("Modelo_Timesheet_CCEE.template.xlsx")
    destination = application_dir() / "Modelo_Timesheet_CCEE.xlsx"
    if not destination.exists() and template.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, destination)
    return destination


def configure_logging() -> Path:
    directory = user_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "timesheet.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        encoding="utf-8",
    )
    return log_path
