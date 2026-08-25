from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable

from .config import APP_NAME, resource_path, user_data_dir


MANIFEST_LIMIT = 1024 * 1024
ARCHIVE_LIMIT = 500 * 1024 * 1024
EXTRACTED_LIMIT = 750 * 1024 * 1024
FILE_COUNT_LIMIT = 10_000
NETWORK_TIMEOUT = 20
UPDATE_CONFIG_FILENAME = "update-config.json"
UPDATE_STATUS_FILENAME = "last-update.json"
RELEASE_INFO_FILENAME = "release-info.json"
PLACEHOLDER_PARTS = ("SEU_USUARIO", "SEU_REPOSITORIO")
PRESERVED_PATHS = {
    ".venv",
    ".venv-build-windows",
    "backups-timesheet",
    "Modelo_Timesheet_CCEE.xlsx",
    "settings.json",
}


class UpdateError(RuntimeError):
    """Erro seguro e apresentável relacionado à atualização do aplicativo."""


@dataclass(frozen=True, slots=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str | int, ...] = ()

    @classmethod
    def parse(cls, value: str) -> Version:
        match = re.fullmatch(
            r"[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?",
            value.strip(),
        )
        if match is None:
            raise UpdateError(f'A versão "{value}" não está no formato 1.2.3.')
        identifiers: list[str | int] = []
        for identifier in (match.group(4) or "").split("."):
            if not identifier:
                continue
            identifiers.append(int(identifier) if identifier.isdigit() else identifier)
        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tuple(identifiers),
        )

    def __lt__(self, other: Version) -> bool:
        own_core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if own_core != other_core:
            return own_core < other_core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for own, remote in zip(self.prerelease, other.prerelease):
            if own == remote:
                continue
            if isinstance(own, int) and isinstance(remote, str):
                return True
            if isinstance(own, str) and isinstance(remote, int):
                return False
            assert isinstance(own, type(remote))
            return own < remote  # type: ignore[operator]
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True, slots=True)
class UpdatePackage:
    url: str
    sha256: str
    size: int | None = None


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    notes: str
    release_url: str
    package: UpdatePackage


def platform_key(system: str | None = None) -> str:
    detected = system or platform.system()
    if detected == "Windows":
        return "windows"
    if detected == "Darwin":
        return "macos"
    raise UpdateError("As atualizações são oferecidas somente no macOS e no Windows.")


def application_root() -> Path:
    """Retorna a pasta portátil que contém os inicializadores do aplicativo."""
    return Path(__file__).resolve().parent.parent


def _require_https(url: str, *, allow_insecure: bool) -> None:
    if allow_insecure:
        return
    if not url.lower().startswith("https://"):
        raise UpdateError("O endereço de atualização precisa usar HTTPS.")


def _read_limited(response: BinaryIO, limit: int) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise UpdateError("A resposta do servidor de atualizações é grande demais.")
    return payload


def _validate_final_url(response: Any, *, allow_insecure: bool) -> None:
    get_url = getattr(response, "geturl", None)
    if callable(get_url):
        _require_https(str(get_url()), allow_insecure=allow_insecure)


def _open_url(url: str, *, timeout: int = NETWORK_TIMEOUT) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, application/octet-stream",
            "User-Agent": f"{APP_NAME.replace(' ', '-')}-Updater",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


class UpdateClient:
    def __init__(
        self,
        current_version: str,
        *,
        config_path: str | Path | None = None,
        system: str | None = None,
        opener: Callable[..., Any] | None = None,
        allow_insecure: bool = False,
        download_root: str | Path | None = None,
    ) -> None:
        self.current_version = current_version
        self.config_path = (
            Path(config_path)
            if config_path is not None
            else resource_path(UPDATE_CONFIG_FILENAME)
        )
        self.system = system
        self.opener = opener or _open_url
        self.allow_insecure = allow_insecure
        self.download_root = (
            Path(download_root)
            if download_root is not None
            else user_data_dir() / "updates"
        )

    def _manifest_url(self) -> str:
        override = os.environ.get("TIMESHEET_UPDATE_URL", "").strip()
        if override:
            url = override
        else:
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise UpdateError(
                    "O canal de atualizações ainda não foi configurado. "
                    "Consulte a seção de publicação no README."
                ) from exc
            except (OSError, json.JSONDecodeError) as exc:
                raise UpdateError(
                    "Não foi possível ler a configuração de atualizações."
                ) from exc
            url = str(payload.get("manifestUrl", "")).strip()
        if not url or any(part in url for part in PLACEHOLDER_PARTS):
            raise UpdateError(
                "O canal de atualizações ainda não foi configurado. "
                "Consulte a seção de publicação no README."
            )
        _require_https(url, allow_insecure=self.allow_insecure)
        return url

    def check(self) -> UpdateInfo | None:
        manifest_url = self._manifest_url()
        try:
            with self.opener(manifest_url, timeout=NETWORK_TIMEOUT) as response:
                _validate_final_url(response, allow_insecure=self.allow_insecure)
                raw_manifest = _read_limited(response, MANIFEST_LIMIT)
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except UpdateError:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise UpdateError(
                "Não foi possível acessar o servidor de atualizações. "
                "Verifique sua conexão com a internet."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            raise UpdateError("O servidor retornou um manifesto inválido.") from exc

        if not isinstance(manifest, dict):
            raise UpdateError("O servidor retornou um manifesto inválido.")
        remote_version_text = str(manifest.get("version", "")).strip()
        remote_version = Version.parse(remote_version_text)
        current_version = Version.parse(self.current_version)
        if not current_version < remote_version:
            return None

        platforms = manifest.get("platforms")
        package_data = (
            platforms.get(platform_key(self.system))
            if isinstance(platforms, dict)
            else None
        )
        if not isinstance(package_data, dict):
            raise UpdateError("A atualização não possui um pacote para este sistema.")

        url = str(package_data.get("url", "")).strip()
        digest = str(package_data.get("sha256", "")).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise UpdateError("O pacote de atualização não possui um SHA-256 válido.")
        _require_https(url, allow_insecure=self.allow_insecure)
        size_value = package_data.get("size")
        try:
            size = int(size_value) if size_value is not None else None
        except (TypeError, ValueError) as exc:
            raise UpdateError("O tamanho informado para a atualização é inválido.") from exc
        if size is not None and (size <= 0 or size > ARCHIVE_LIMIT):
            raise UpdateError("O tamanho informado para a atualização é inválido.")

        return UpdateInfo(
            version=remote_version_text,
            notes=str(manifest.get("notes", "")).strip(),
            release_url=str(manifest.get("releaseUrl", "")).strip(),
            package=UpdatePackage(url=url, sha256=digest, size=size),
        )

    def download(self, update: UpdateInfo) -> Path:
        directory = self.download_root / update.version
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "package.zip"
        if destination.is_file() and _sha256(destination) == update.package.sha256:
            return destination
        partial = destination.with_suffix(".zip.part")
        try:
            with self.opener(update.package.url, timeout=NETWORK_TIMEOUT) as response:
                _validate_final_url(response, allow_insecure=self.allow_insecure)
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > ARCHIVE_LIMIT:
                    raise UpdateError("O pacote de atualização é grande demais.")
                digest = hashlib.sha256()
                received = 0
                with partial.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > ARCHIVE_LIMIT:
                            raise UpdateError("O pacote de atualização é grande demais.")
                        digest.update(chunk)
                        output.write(chunk)
            if update.package.size is not None and received != update.package.size:
                raise UpdateError("O download da atualização ficou incompleto.")
            if digest.hexdigest() != update.package.sha256:
                raise UpdateError(
                    "A verificação de segurança do pacote falhou (SHA-256 diferente)."
                )
            with zipfile.ZipFile(partial) as archive:
                if archive.testzip() is not None:
                    raise UpdateError("O pacote de atualização está corrompido.")
            os.replace(partial, destination)
            return destination
        except UpdateError:
            partial.unlink(missing_ok=True)
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError(
                "Não foi possível baixar a atualização. Verifique sua conexão."
            ) from exc
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError("Não foi possível salvar o pacote de atualização.") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(
        part in ("", ".", "..") for part in path.parts
    ):
        raise UpdateError("O pacote contém um caminho de arquivo inválido.")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _extract_verified_archive(archive_path: Path, staging: Path, version: str) -> Path:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > FILE_COUNT_LIMIT:
                raise UpdateError("O pacote contém arquivos demais.")
            if sum(info.file_size for info in members) > EXTRACTED_LIMIT:
                raise UpdateError("O conteúdo do pacote é grande demais.")
            for info in members:
                relative = _safe_member_path(info.filename)
                if _is_symlink(info):
                    raise UpdateError("O pacote contém um link simbólico não permitido.")
                target = staging.joinpath(*relative.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    target.chmod(mode)
    except UpdateError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError("Não foi possível extrair o pacote de atualização.") from exc

    markers = list(staging.rglob(RELEASE_INFO_FILENAME))
    if len(markers) != 1:
        raise UpdateError("O pacote não contém uma identificação de release válida.")
    package_root = markers[0].parent
    try:
        release_info = json.loads(markers[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("A identificação do pacote é inválida.") from exc
    if (
        not isinstance(release_info, dict)
        or release_info.get("application") != APP_NAME
        or str(release_info.get("version", "")) != version
    ):
        raise UpdateError("O pacote pertence a outro aplicativo ou versão.")
    for required in ("run_timesheet.py", "timesheet_ccee/__init__.py"):
        if not (package_root / required).is_file():
            raise UpdateError("O pacote está incompleto e não pode ser instalado.")
    return package_root


def _is_preserved(relative: Path) -> bool:
    preserved = {name.casefold() for name in PRESERVED_PATHS}
    return bool(relative.parts) and relative.parts[0].casefold() in preserved


def install_update(
    archive_path: str | Path,
    *,
    version: str,
    target_root: str | Path,
    work_root: str | Path | None = None,
) -> Path:
    """Instala um pacote verificado e devolve a pasta do backup do aplicativo."""
    archive = Path(archive_path).resolve()
    target = Path(target_root).resolve()
    updates_root = Path(work_root) if work_root else user_data_dir() / "updates"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    transaction = updates_root / f"install-{version}-{timestamp}-{os.getpid()}"
    staging = transaction / "staging"
    backup = transaction / "backup"
    staging.mkdir(parents=True, exist_ok=False)
    package_root = _extract_verified_archive(archive, staging, version)

    installed: list[Path] = []
    backed_up: list[Path] = []
    try:
        sources = sorted(path for path in package_root.rglob("*") if path.is_file())
        for source in sources:
            relative = source.relative_to(package_root)
            destination = target / relative
            if _is_preserved(relative) and destination.exists():
                continue
            if not destination.parent.resolve().is_relative_to(target):
                raise UpdateError("O destino da atualização contém um link inseguro.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup_path = backup / relative
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path)
                backed_up.append(relative)
            replacement = destination.with_name(
                f".{destination.name}.update-{os.getpid()}"
            )
            shutil.copy2(source, replacement)
            os.replace(replacement, destination)
            installed.append(relative)
    except Exception as exc:
        for relative in reversed(installed):
            destination = target / relative
            backup_path = backup / relative
            try:
                if backup_path.exists():
                    shutil.copy2(backup_path, destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError:
                logging.exception("Falha ao restaurar %s", destination)
        raise UpdateError(
            "A instalação falhou; os arquivos anteriores foram restaurados."
        ) from exc

    manifest = {
        "version": version,
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": [relative.as_posix() for relative in installed],
        "backedUpFiles": [relative.as_posix() for relative in backed_up],
    }
    (transaction / "install-result.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return backup


def _process_exists(pid: int) -> bool:
    if platform.system() == "Windows":
        try:
            import ctypes

            synchronize = 0x00100000
            wait_timeout = 0x00000102
            handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
            if not handle:
                return False
            try:
                result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
                return result == wait_timeout
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            logging.exception("Não foi possível consultar o processo no Windows")
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _write_update_status(payload: dict[str, Any]) -> None:
    path = user_data_dir() / UPDATE_STATUS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def consume_update_status() -> dict[str, Any] | None:
    path = user_data_dir() / UPDATE_STATUS_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logging.exception("Não foi possível ler o resultado da atualização")
        return None
    return payload if isinstance(payload, dict) else None


def relaunch_command(root: Path | None = None) -> list[str]:
    app_root = root or application_root()
    if platform.system() == "Windows":
        return ["cmd.exe", "/c", str(app_root / "INICIAR_TIMESHEET.cmd")]
    if platform.system() == "Darwin":
        return ["/bin/zsh", str(app_root / "INICIAR_TIMESHEET.command")]
    return [sys.executable, str(app_root / "run_timesheet.py")]


def start_update_installer(
    archive_path: Path,
    *,
    version: str,
    target_root: Path | None = None,
) -> None:
    root = (target_root or application_root()).resolve()
    command = [
        sys.executable,
        "-m",
        "timesheet_ccee.update_installer",
        "--archive",
        str(archive_path.resolve()),
        "--version",
        version,
        "--target",
        str(root),
        "--parent-pid",
        str(os.getpid()),
        "--relaunch",
        json.dumps(relaunch_command(root), ensure_ascii=False),
    ]
    log_path = user_data_dir() / "update-installer.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = 0
    kwargs: dict[str, Any] = {"cwd": str(root), "close_fds": True}
    if platform.system() == "Windows":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    with log_path.open("ab") as log:
        subprocess.Popen(command, stdout=log, stderr=log, **kwargs)


def run_installer(
    *,
    archive: Path,
    version: str,
    target: Path,
    parent_pid: int,
    relaunch: list[str],
) -> int:
    for _ in range(120):
        if not _process_exists(parent_pid):
            break
        time.sleep(0.25)
    else:
        _write_update_status(
            {
                "success": False,
                "message": "O aplicativo não fechou a tempo para concluir a atualização.",
            }
        )
        return 1

    success = False
    try:
        install_update(archive, version=version, target_root=target)
        _write_update_status(
            {
                "success": True,
                "version": version,
                "message": f"O {APP_NAME} foi atualizado para a versão {version}.",
            }
        )
        success = True
    except Exception as exc:
        logging.exception("Falha ao instalar atualização")
        _write_update_status({"success": False, "message": str(exc)})
    finally:
        try:
            relaunch_kwargs: dict[str, Any] = {
                "cwd": str(target),
                "close_fds": True,
            }
            if platform.system() == "Windows":
                relaunch_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            else:
                relaunch_kwargs["start_new_session"] = True
            subprocess.Popen(
                relaunch,
                **relaunch_kwargs,
            )
        except OSError:
            logging.exception("Falha ao reabrir o aplicativo")
    return 0 if success else 1
