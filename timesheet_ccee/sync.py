from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .database import TimesheetDatabase
from .workbook import TimesheetWorkbook


@dataclass
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

    def reset(
        self, workbook: TimesheetWorkbook, template_path: str | Path
    ) -> SyncOutcome:
        """Recria a planilha pelo modelo e zera seu estado no banco local."""
        result = workbook.replace_with_template(template_path)
        try:
            metadata, entries = workbook.load_dataset()
            if entries:
                raise RuntimeError("O modelo da planilha contém apontamentos.")
            self.database.reset_workbook(workbook.path, metadata)
        except Exception:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{workbook.path.stem}_restore_",
                suffix=workbook.path.suffix,
                dir=workbook.path.parent,
            )
            os.close(descriptor)
            restore_path = Path(temp_name)
            try:
                shutil.copy2(result.backup_path, restore_path)
                os.replace(restore_path, workbook.path)
            finally:
                restore_path.unlink(missing_ok=True)
            raise
        return SyncOutcome(
            imported=False,
            synchronized=True,
            record_count=0,
            backup_path=result.backup_path,
        )
