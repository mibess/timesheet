from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from timesheet_ccee.config import default_workbook_path


class TimesheetConfigTests(unittest.TestCase):
    def test_uses_fixed_workbook_name_and_ignores_old_user_preference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "app"
            data_dir = root / "data"
            template = root / "Modelo_Timesheet_CCEE.template.xlsx"
            old_workbook = root / "arquivo-antigo.xlsx"
            template.write_bytes(b"template")
            old_workbook.write_bytes(b"old")
            app_dir.mkdir()
            data_dir.mkdir()
            (data_dir / "user-config.json").write_text(
                '{"workbookPath": "' + str(old_workbook) + '"}',
                encoding="utf-8",
            )

            with (
                patch("timesheet_ccee.config.application_dir", return_value=app_dir),
                patch("timesheet_ccee.config.resource_path", return_value=template),
                patch("timesheet_ccee.config.user_data_dir", return_value=data_dir),
            ):
                path = default_workbook_path()

            self.assertEqual(path, app_dir / "Modelo_Timesheet_CCEE.xlsx")
            self.assertEqual(path.read_bytes(), b"template")


if __name__ == "__main__":
    unittest.main()
