from __future__ import annotations

import hashlib
import io
import json
import ssl
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from timesheet_ccee.config import APP_NAME
from timesheet_ccee.updater import (
    UpdateClient,
    UpdateError,
    UpdateInfo,
    UpdatePackage,
    Version,
    _connection_error_message,
    _open_url,
    install_update,
)


class MemoryResponse(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers: dict[str, str] = {"Content-Length": str(len(payload))}

    def __enter__(self) -> MemoryResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class TimesheetUpdaterTests(unittest.TestCase):
    def test_opens_https_with_the_certifi_certificate_bundle(self) -> None:
        response = object()
        ssl_context = object()
        with patch(
            "timesheet_ccee.updater.ssl.create_default_context",
            return_value=ssl_context,
        ) as create_context, patch(
            "timesheet_ccee.updater.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = _open_url("https://example.test/update.json", timeout=7)

        self.assertIs(result, response)
        create_context.assert_called_once()
        self.assertTrue(create_context.call_args.kwargs["cafile"].endswith("cacert.pem"))
        self.assertIs(urlopen.call_args.kwargs["context"], ssl_context)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)

    def test_explains_a_certificate_validation_failure(self) -> None:
        certificate_error = ssl.SSLCertVerificationError("invalid certificate")
        network_error = urllib.error.URLError(certificate_error)

        message = _connection_error_message(network_error, downloading=False)

        self.assertIn("conexão segura", message)

    def test_compares_stable_and_prerelease_versions(self) -> None:
        self.assertLess(Version.parse("2.1.9"), Version.parse("2.2.0"))
        self.assertLess(Version.parse("v2.2.0-beta.2"), Version.parse("2.2.0"))
        self.assertLess(
            Version.parse("2.2.0-beta.2"), Version.parse("2.2.0-beta.10")
        )
        self.assertFalse(Version.parse("2.2.0") < Version.parse("2.2.0"))

    def test_checks_the_package_for_the_current_platform(self) -> None:
        manifest = {
            "version": "2.3.0",
            "notes": "Melhorias",
            "releaseUrl": "https://github.com/example/timesheet/releases/tag/v2.3.0",
            "platforms": {
                "macos": {
                    "url": "https://github.com/example/timesheet/macos.zip",
                    "sha256": "a" * 64,
                    "size": 123,
                },
                "windows": {
                    "url": "https://github.com/example/timesheet/windows.zip",
                    "sha256": "b" * 64,
                },
            },
        }
        payload = json.dumps(manifest).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = Path(temporary_directory) / "update-config.json"
            config.write_text(
                json.dumps({"manifestUrl": "https://example.test/update.json"}),
                encoding="utf-8",
            )
            client = UpdateClient(
                "2.2.0",
                config_path=config,
                system="Windows",
                opener=lambda *_args, **_kwargs: MemoryResponse(payload),
            )

            update = client.check()

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.version, "2.3.0")
        self.assertTrue(update.package.url.endswith("windows.zip"))
        self.assertEqual(update.package.sha256, "b" * 64)

    def test_download_rejects_a_different_sha256(self) -> None:
        payload = b"not-a-zip"
        update = UpdateInfo(
            version="2.3.0",
            notes="",
            release_url="",
            package=UpdatePackage(
                url="https://example.test/package.zip",
                sha256=hashlib.sha256(b"another-payload").hexdigest(),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            client = UpdateClient(
                "2.2.0",
                opener=lambda *_args, **_kwargs: MemoryResponse(payload),
                download_root=temporary_directory,
            )

            with self.assertRaisesRegex(UpdateError, "SHA-256"):
                client.download(update)

            self.assertFalse(list(Path(temporary_directory).rglob("*.part")))

    def test_installs_code_but_preserves_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "application"
            target_package = target / "timesheet_ccee"
            target_package.mkdir(parents=True)
            (target / "run_timesheet.py").write_text("old runner", encoding="utf-8")
            (target_package / "__init__.py").write_text("old code", encoding="utf-8")
            (target / "settings.json").write_text("user settings", encoding="utf-8")
            (target / "Modelo_Timesheet_CCEE.xlsx").write_bytes(b"user workbook")

            archive_path = root / "release.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                prefix = "Timesheet-CCEE/"
                archive.writestr(prefix + "run_timesheet.py", "new runner")
                archive.writestr(prefix + "timesheet_ccee/__init__.py", "new code")
                archive.writestr(prefix + "settings.json", "release settings")
                archive.writestr(
                    prefix + "Modelo_Timesheet_CCEE.xlsx", b"release workbook"
                )
                archive.writestr(
                    prefix + "release-info.json",
                    json.dumps(
                        {"application": APP_NAME, "version": "2.3.0"}
                    ),
                )

            backup = install_update(
                archive_path,
                version="2.3.0",
                target_root=target,
                work_root=root / "updates",
            )

            self.assertEqual(
                (target / "run_timesheet.py").read_text(encoding="utf-8"),
                "new runner",
            )
            self.assertEqual(
                (target_package / "__init__.py").read_text(encoding="utf-8"),
                "new code",
            )
            self.assertEqual(
                (target / "settings.json").read_text(encoding="utf-8"),
                "user settings",
            )
            self.assertEqual(
                (target / "Modelo_Timesheet_CCEE.xlsx").read_bytes(),
                b"user workbook",
            )
            self.assertEqual(
                (backup / "run_timesheet.py").read_text(encoding="utf-8"),
                "old runner",
            )

    def test_rejects_path_traversal_in_the_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")

            with self.assertRaisesRegex(UpdateError, "caminho"):
                install_update(
                    archive_path,
                    version="2.3.0",
                    target_root=root / "application",
                    work_root=root / "updates",
                )


if __name__ == "__main__":
    unittest.main()
