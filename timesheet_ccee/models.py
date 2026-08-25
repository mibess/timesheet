from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TimeEntry:
    hours: str
    activity_type: str
    ticket: str
    number: str = ""
    observation: str = ""
    phase: str = ""

    def as_row(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.hours,
            self.activity_type,
            self.ticket,
            self.number,
            self.observation,
            self.phase,
        )


@dataclass(slots=True)
class WorkbookMetadata:
    activity_types: list[str] = field(default_factory=list)
    ticket_types: list[str] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    recent_numbers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SaveResult:
    backup_path: str
    record_count: int
