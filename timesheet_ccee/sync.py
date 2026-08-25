from __future__ import annotations

from dataclasses import dataclass

from .database import TimesheetDatabase
from .workbook import TimesheetWorkbook


@dataclass(slots=True)
class SyncOutcome:
    imported: bool
    synchronized: bool
    record_count: int
    backup_path: str = ""


class TimesheetSync:
    """Coordena o SQLite (fonte local) e a planilha (destino sincronizado)."""

    def __init__(self, database: TimesheetDatabase) -> None:
        self.database = database

    def activate(self, workbook: TimesheetWorkbook) -> SyncOutcome:
        """Importa no primeiro uso; nos demais, sincroniza somente se necessário."""
        if not self.database.contains(workbook.path):
            metadata, entries = workbook.load_dataset()
            count = self.database.import_workbook(workbook.path, metadata, entries)
            return SyncOutcome(
                imported=True,
                synchronized=False,
                record_count=count,
            )
        return self.synchronize(workbook)

    def synchronize(self, workbook: TimesheetWorkbook) -> SyncOutcome:
        if not self.database.needs_sync(workbook.path):
            return SyncOutcome(
                imported=False,
                synchronized=False,
                record_count=len(self.database.load_all_entries(workbook.path)),
            )

        result = workbook.save_all(self.database.load_all_entries(workbook.path))
        self.database.mark_synced(workbook.path)
        return SyncOutcome(
            imported=False,
            synchronized=True,
            record_count=result.record_count,
            backup_path=result.backup_path,
        )
