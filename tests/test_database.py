from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from timesheet_ccee.database import DatabaseError, TimesheetDatabase
from timesheet_ccee.models import TimeEntry, WorkbookMetadata


class TimesheetDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.workbook_path = self.root / "timesheet.xlsx"
        self.workbook_path.write_bytes(b"arquivo-inicial")
        self.database = TimesheetDatabase(self.root / "timesheet.sqlite3")
        self.metadata = WorkbookMetadata(
            activity_types=["Sustentação", "ADM"],
            ticket_types=["CSTM", "Reuniões"],
            phases=["Execução"],
            recent_numbers=["100"],
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_import_load_save_and_sync_state(self) -> None:
        initial_date = date(2026, 8, 24)
        imported = self.database.import_workbook(
            self.workbook_path,
            self.metadata,
            [
                (
                    initial_date,
                    TimeEntry("01:30", "Sustentação", "CSTM", "100", "Teste"),
                )
            ],
        )

        self.assertEqual(imported, 1)
        self.assertTrue(self.database.contains(self.workbook_path))
        self.assertEqual(
            self.database.load_day(self.workbook_path, initial_date)[0].hours,
            "01:30",
        )
        self.assertFalse(self.database.needs_sync(self.workbook_path))

        new_date = date(2026, 8, 25)
        new_entry = TimeEntry(
            "02:15", "Sustentação", "CSTM", "200", "Persistido", "Execução"
        )
        self.database.save_day(self.workbook_path, new_date, [new_entry])

        self.assertEqual(self.database.load_day(self.workbook_path, new_date), [new_entry])
        self.assertTrue(self.database.needs_sync(self.workbook_path))
        self.database.mark_synced(self.workbook_path)
        self.assertFalse(self.database.needs_sync(self.workbook_path))
        self.assertEqual(
            self.database.load_metadata(self.workbook_path).recent_numbers[:2],
            ["200", "100"],
        )

        self.workbook_path.write_bytes(b"alteracao-externa")
        self.assertTrue(self.database.needs_sync(self.workbook_path))

    def test_rejects_invalid_day_without_changing_existing_data(self) -> None:
        selected_date = date(2026, 8, 25)
        original = TimeEntry("01:00", "ADM", "Reuniões")
        self.database.import_workbook(
            self.workbook_path,
            self.metadata,
            [(selected_date, original)],
        )

        with self.assertRaises(DatabaseError):
            self.database.save_day(
                self.workbook_path,
                selected_date,
                [TimeEntry("00:00", "ADM", "Reuniões")],
            )

        self.assertEqual(
            self.database.load_day(self.workbook_path, selected_date), [original]
        )

    def test_loads_latest_existing_day_before_selected_date(self) -> None:
        older = TimeEntry("01:00", "ADM", "Reuniões", observation="Mais antigo")
        latest = TimeEntry("02:00", "ADM", "Reuniões", observation="Vigente")
        latest_second = TimeEntry(
            "00:30", "Sustentação", "CSTM", observation="Segunda atividade"
        )
        future = TimeEntry("03:00", "ADM", "Reuniões", observation="Futuro")
        self.database.import_workbook(
            self.workbook_path,
            self.metadata,
            [
                (date(2026, 8, 20), older),
                (date(2026, 8, 22), latest),
                (date(2026, 8, 22), latest_second),
                (date(2026, 8, 26), future),
            ],
        )

        result = self.database.load_latest_day_before(
            self.workbook_path, date(2026, 8, 25)
        )

        self.assertEqual(result, (date(2026, 8, 22), [latest, latest_second]))

    def test_latest_existing_day_returns_none_without_previous_entries(self) -> None:
        current = date(2026, 8, 25)
        self.database.import_workbook(
            self.workbook_path,
            self.metadata,
            [(current, TimeEntry("01:00", "ADM", "Reuniões"))],
        )

        self.assertIsNone(
            self.database.load_latest_day_before(self.workbook_path, current)
        )

    def test_calculates_worked_hours_across_all_days(self) -> None:
        self.database.import_workbook(
            self.workbook_path,
            self.metadata,
            [
                (date(2026, 8, 24), TimeEntry("01:30", "ADM", "Reuniões")),
                (date(2026, 8, 24), TimeEntry("00:45", "ADM", "Reuniões")),
                (date(2026, 8, 25), TimeEntry("07:15", "Sustentação", "CSTM")),
            ],
        )

        self.assertEqual(
            self.database.calculate_worked_hours(self.workbook_path),
            (570, 3),
        )


if __name__ == "__main__":
    unittest.main()
