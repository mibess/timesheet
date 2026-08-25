from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from timesheet_ccee.database import TimesheetDatabase
from timesheet_ccee.models import TimeEntry
from timesheet_ccee.sync import TimesheetSync
from timesheet_ccee.workbook import TimesheetWorkbook


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TimesheetSyncTests(unittest.TestCase):
    def test_first_use_imports_and_later_sync_exports_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workbook_path = root / "timesheet.xlsx"
            shutil.copy2(
                PROJECT_ROOT / "Modelo_Timesheet_CCEE.template.xlsx",
                workbook_path,
            )
            database = TimesheetDatabase(root / "timesheet.sqlite3")
            synchronizer = TimesheetSync(database)
            workbook = TimesheetWorkbook(workbook_path)

            initial_entries = workbook.load_dataset()[1]
            imported = synchronizer.activate(workbook)
            self.assertTrue(imported.imported)
            self.assertEqual(imported.record_count, len(initial_entries))
            self.assertFalse(database.needs_sync(workbook_path))

            selected_date = date(2099, 1, 2)
            entry = TimeEntry(
                "03:45", "Sustentação", "CSTM", "999", "Teste de sincronização"
            )
            database.save_day(workbook_path, selected_date, [entry])
            synchronized = synchronizer.synchronize(workbook)

            self.assertTrue(synchronized.synchronized)
            self.assertEqual(synchronized.record_count, len(initial_entries) + 1)
            self.assertTrue(Path(synchronized.backup_path).is_file())
            self.assertFalse(database.needs_sync(workbook_path))
            self.assertEqual(workbook.load_day(selected_date), [entry])

            unchanged = synchronizer.synchronize(workbook)
            self.assertFalse(unchanged.synchronized)
            self.assertEqual(unchanged.backup_path, "")


if __name__ == "__main__":
    unittest.main()
