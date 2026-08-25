from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import user_data_dir
from .models import TimeEntry, WorkbookMetadata
from .time_utils import format_duration, parse_duration


DATABASE_FILENAME = "timesheet.sqlite3"
SCHEMA_VERSION = 1


class DatabaseError(RuntimeError):
    """Erro seguro relacionado ao banco local."""


class TimesheetDatabase:
    """Persistência SQLite local, organizada por caminho de planilha."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path).expanduser().resolve()
            if path is not None
            else user_data_dir() / DATABASE_FILENAME
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def _workbook_key(workbook_path: str | Path) -> str:
        return str(Path(workbook_path).expanduser().resolve())

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS workbooks (
                        id INTEGER PRIMARY KEY,
                        path TEXT NOT NULL UNIQUE,
                        activity_types_json TEXT NOT NULL DEFAULT '[]',
                        ticket_types_json TEXT NOT NULL DEFAULT '[]',
                        phases_json TEXT NOT NULL DEFAULT '[]',
                        recent_numbers_json TEXT NOT NULL DEFAULT '[]',
                        revision INTEGER NOT NULL DEFAULT 0,
                        synced_revision INTEGER NOT NULL DEFAULT 0,
                        file_mtime_ns INTEGER,
                        file_size INTEGER,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_synced_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS entries (
                        id INTEGER PRIMARY KEY,
                        workbook_id INTEGER NOT NULL,
                        worked_date TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        minutes INTEGER NOT NULL,
                        activity_type TEXT NOT NULL,
                        ticket TEXT NOT NULL,
                        number TEXT NOT NULL DEFAULT '',
                        observation TEXT NOT NULL DEFAULT '',
                        phase TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY (workbook_id) REFERENCES workbooks(id)
                            ON DELETE CASCADE,
                        UNIQUE (workbook_id, worked_date, position)
                    );

                    CREATE INDEX IF NOT EXISTS idx_entries_workbook_date
                        ON entries (workbook_id, worked_date, position);
                    """
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível preparar o banco de dados local."
            ) from exc

    @staticmethod
    def _fingerprint(path: str | Path) -> tuple[int, int]:
        try:
            stat = Path(path).stat()
        except OSError as exc:
            raise DatabaseError(
                "Não foi possível verificar a planilha para sincronização."
            ) from exc
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _workbook_id(connection: sqlite3.Connection, key: str) -> int:
        row = connection.execute(
            "SELECT id FROM workbooks WHERE path = ?", (key,)
        ).fetchone()
        if row is None:
            raise DatabaseError(
                "A planilha ainda não foi importada para o banco de dados local."
            )
        return int(row["id"])

    def contains(self, workbook_path: str | Path) -> bool:
        key = self._workbook_key(workbook_path)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT 1 FROM workbooks WHERE path = ?", (key,)
                ).fetchone()
                return row is not None
        except sqlite3.Error as exc:
            raise DatabaseError("Não foi possível consultar o banco local.") from exc

    def import_workbook(
        self,
        workbook_path: str | Path,
        metadata: WorkbookMetadata,
        entries: Iterable[tuple[date, TimeEntry]],
    ) -> int:
        """Importa a planilha apenas se ela ainda não existir no banco."""
        key = self._workbook_key(workbook_path)
        mtime_ns, file_size = self._fingerprint(key)
        prepared = list(entries)
        now = self._now()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    existing = connection.execute(
                        "SELECT id FROM workbooks WHERE path = ?", (key,)
                    ).fetchone()
                    if existing is not None:
                        return 0
                    cursor = connection.execute(
                        """
                        INSERT INTO workbooks (
                            path, activity_types_json, ticket_types_json,
                            phases_json, recent_numbers_json, revision,
                            synced_revision, file_mtime_ns, file_size,
                            created_at, updated_at, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            json.dumps(metadata.activity_types, ensure_ascii=False),
                            json.dumps(metadata.ticket_types, ensure_ascii=False),
                            json.dumps(metadata.phases, ensure_ascii=False),
                            json.dumps(metadata.recent_numbers, ensure_ascii=False),
                            mtime_ns,
                            file_size,
                            now,
                            now,
                            now,
                        ),
                    )
                    workbook_id = int(cursor.lastrowid)
                    positions: dict[str, int] = {}
                    rows = []
                    for worked_date, entry in prepared:
                        iso_date = worked_date.isoformat()
                        position = positions.get(iso_date, 0) + 1
                        positions[iso_date] = position
                        rows.append(
                            self._entry_row(workbook_id, iso_date, position, entry)
                        )
                    connection.executemany(
                        """
                        INSERT INTO entries (
                            workbook_id, worked_date, position, minutes,
                            activity_type, ticket, number, observation, phase
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
            return len(prepared)
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseError(
                "Não foi possível importar a planilha para o banco local."
            ) from exc

    def replace_workbook(
        self,
        workbook_path: str | Path,
        metadata: WorkbookMetadata,
        entries: Iterable[tuple[date, TimeEntry]],
    ) -> int:
        """Substitui, em uma transação, todos os dados de uma planilha existente."""
        key = self._workbook_key(workbook_path)
        prepared = list(entries)
        now = self._now()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    workbook_id = self._workbook_id(connection, key)
                    positions: dict[str, int] = {}
                    rows = []
                    for worked_date, entry in prepared:
                        iso_date = worked_date.isoformat()
                        position = positions.get(iso_date, 0) + 1
                        positions[iso_date] = position
                        rows.append(
                            self._entry_row(
                                workbook_id, iso_date, position, entry
                            )
                        )

                    connection.execute(
                        "DELETE FROM entries WHERE workbook_id = ?", (workbook_id,)
                    )
                    connection.executemany(
                        """
                        INSERT INTO entries (
                            workbook_id, worked_date, position, minutes,
                            activity_type, ticket, number, observation, phase
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    cursor = connection.execute(
                        """
                        UPDATE workbooks
                        SET activity_types_json = ?, ticket_types_json = ?,
                            phases_json = ?, recent_numbers_json = ?,
                            revision = revision + 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            json.dumps(metadata.activity_types, ensure_ascii=False),
                            json.dumps(metadata.ticket_types, ensure_ascii=False),
                            json.dumps(metadata.phases, ensure_ascii=False),
                            json.dumps(metadata.recent_numbers, ensure_ascii=False),
                            now,
                            workbook_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise DatabaseError(
                            "A planilha ainda não foi importada para o banco local."
                        )
            return len(prepared)
        except ValueError as exc:
            raise DatabaseError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível substituir os dados do banco local."
            ) from exc

    @staticmethod
    def _entry_row(
        workbook_id: int,
        iso_date: str,
        position: int,
        entry: TimeEntry,
    ) -> tuple[int, str, int, int, str, str, str, str, str]:
        minutes = parse_duration(entry.hours, allow_zero=True)
        return (
            workbook_id,
            iso_date,
            position,
            minutes,
            entry.activity_type.strip(),
            entry.ticket.strip(),
            entry.number.strip(),
            entry.observation.strip(),
            entry.phase.strip(),
        )

    def load_day(
        self, workbook_path: str | Path, selected_date: date
    ) -> list[TimeEntry]:
        key = self._workbook_key(workbook_path)
        try:
            with closing(self._connect()) as connection:
                workbook_id = self._workbook_id(connection, key)
                rows = connection.execute(
                    """
                    SELECT minutes, activity_type, ticket, number,
                           observation, phase
                    FROM entries
                    WHERE workbook_id = ? AND worked_date = ?
                    ORDER BY position
                    """,
                    (workbook_id, selected_date.isoformat()),
                ).fetchall()
                return [self._time_entry(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Não foi possível carregar o dia do banco local.") from exc

    def load_latest_day_before(
        self, workbook_path: str | Path, selected_date: date
    ) -> tuple[date, list[TimeEntry]] | None:
        """Carrega o dia mais recente com registros anterior à data informada."""
        key = self._workbook_key(workbook_path)
        try:
            with closing(self._connect()) as connection:
                workbook_id = self._workbook_id(connection, key)
                latest_row = connection.execute(
                    """
                    SELECT MAX(worked_date) AS worked_date
                    FROM entries
                    WHERE workbook_id = ? AND worked_date < ?
                    """,
                    (workbook_id, selected_date.isoformat()),
                ).fetchone()
                if latest_row is None or latest_row["worked_date"] is None:
                    return None

                worked_date = date.fromisoformat(str(latest_row["worked_date"]))
                rows = connection.execute(
                    """
                    SELECT minutes, activity_type, ticket, number,
                           observation, phase
                    FROM entries
                    WHERE workbook_id = ? AND worked_date = ?
                    ORDER BY position
                    """,
                    (workbook_id, worked_date.isoformat()),
                ).fetchall()
                return worked_date, [self._time_entry(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível carregar o último dia vigente do banco local."
            ) from exc

    def load_all_entries(
        self, workbook_path: str | Path
    ) -> list[tuple[date, TimeEntry]]:
        key = self._workbook_key(workbook_path)
        try:
            with closing(self._connect()) as connection:
                workbook_id = self._workbook_id(connection, key)
                rows = connection.execute(
                    """
                    SELECT worked_date, minutes, activity_type, ticket, number,
                           observation, phase
                    FROM entries
                    WHERE workbook_id = ?
                    ORDER BY worked_date, position
                    """,
                    (workbook_id,),
                ).fetchall()
                return [
                    (date.fromisoformat(str(row["worked_date"])), self._time_entry(row))
                    for row in rows
                ]
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível carregar os registros do banco local."
            ) from exc

    def calculate_worked_hours(self, workbook_path: str | Path) -> tuple[int, int]:
        """Retorna o total de minutos e de atividades da planilha."""
        key = self._workbook_key(workbook_path)
        try:
            with closing(self._connect()) as connection:
                workbook_id = self._workbook_id(connection, key)
                row = connection.execute(
                    """
                    SELECT COALESCE(SUM(minutes), 0) AS total_minutes,
                           COUNT(*) AS activity_count
                    FROM entries
                    WHERE workbook_id = ?
                    """,
                    (workbook_id,),
                ).fetchone()
                assert row is not None
                return int(row["total_minutes"]), int(row["activity_count"])
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível calcular as horas trabalhadas."
            ) from exc

    @staticmethod
    def _time_entry(row: sqlite3.Row) -> TimeEntry:
        return TimeEntry(
            hours=format_duration(int(row["minutes"])),
            activity_type=str(row["activity_type"]),
            ticket=str(row["ticket"]),
            number=str(row["number"]),
            observation=str(row["observation"]),
            phase=str(row["phase"]),
        )

    def load_metadata(self, workbook_path: str | Path) -> WorkbookMetadata:
        key = self._workbook_key(workbook_path)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT id, activity_types_json, ticket_types_json,
                           phases_json, recent_numbers_json
                    FROM workbooks WHERE path = ?
                    """,
                    (key,),
                ).fetchone()
                if row is None:
                    raise DatabaseError(
                        "A planilha ainda não foi importada para o banco local."
                    )
                number_rows = connection.execute(
                    """
                    SELECT number FROM entries
                    WHERE workbook_id = ? AND number <> ''
                    ORDER BY worked_date DESC, position DESC
                    """,
                    (int(row["id"]),),
                ).fetchall()
                recent_numbers: list[str] = []
                for item in number_rows:
                    number = str(item["number"])
                    if number not in recent_numbers:
                        recent_numbers.append(number)
                    if len(recent_numbers) == 15:
                        break
                for number in self._json_list(row["recent_numbers_json"]):
                    if number not in recent_numbers:
                        recent_numbers.append(number)
                    if len(recent_numbers) == 15:
                        break
                return WorkbookMetadata(
                    activity_types=self._json_list(row["activity_types_json"]),
                    ticket_types=self._json_list(row["ticket_types_json"]),
                    phases=self._json_list(row["phases_json"]),
                    recent_numbers=recent_numbers,
                )
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível carregar as opções do banco local."
            ) from exc

    @staticmethod
    def _json_list(value: object) -> list[str]:
        try:
            decoded = json.loads(str(value))
        except json.JSONDecodeError:
            return []
        return [str(item) for item in decoded] if isinstance(decoded, list) else []

    def save_day(
        self,
        workbook_path: str | Path,
        selected_date: date,
        entries: Iterable[TimeEntry],
    ) -> int:
        key = self._workbook_key(workbook_path)
        prepared = list(entries)
        for position, entry in enumerate(prepared, start=1):
            try:
                minutes = parse_duration(entry.hours, allow_zero=True)
            except ValueError as exc:
                raise DatabaseError(f"Linha {position}: {exc}") from exc
            if minutes == 0:
                raise DatabaseError(
                    f"Linha {position}: as horas estão em 00:00."
                )
            if not entry.activity_type.strip():
                raise DatabaseError(
                    f"Informe o Tipo de Atividade na linha {position}."
                )
            if not entry.ticket.strip():
                raise DatabaseError(f"Informe o Ticket na linha {position}.")
        try:
            with closing(self._connect()) as connection:
                with connection:
                    workbook_id = self._workbook_id(connection, key)
                    iso_date = selected_date.isoformat()
                    rows = [
                        self._entry_row(workbook_id, iso_date, position, entry)
                        for position, entry in enumerate(prepared, start=1)
                    ]
                    connection.execute(
                        "DELETE FROM entries WHERE workbook_id = ? AND worked_date = ?",
                        (workbook_id, iso_date),
                    )
                    connection.executemany(
                        """
                        INSERT INTO entries (
                            workbook_id, worked_date, position, minutes,
                            activity_type, ticket, number, observation, phase
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    connection.execute(
                        """
                        UPDATE workbooks
                        SET revision = revision + 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (self._now(), workbook_id),
                    )
            return len(prepared)
        except ValueError as exc:
            raise DatabaseError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise DatabaseError("Não foi possível salvar o dia no banco local.") from exc

    def needs_sync(self, workbook_path: str | Path) -> bool:
        key = self._workbook_key(workbook_path)
        try:
            mtime_ns, file_size = self._fingerprint(key)
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT revision, synced_revision, file_mtime_ns, file_size
                    FROM workbooks WHERE path = ?
                    """,
                    (key,),
                ).fetchone()
                if row is None:
                    raise DatabaseError(
                        "A planilha ainda não foi importada para o banco local."
                    )
                return (
                    int(row["revision"]) != int(row["synced_revision"])
                    or row["file_mtime_ns"] != mtime_ns
                    or row["file_size"] != file_size
                )
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível verificar o estado da sincronização."
            ) from exc

    def mark_synced(self, workbook_path: str | Path) -> None:
        key = self._workbook_key(workbook_path)
        mtime_ns, file_size = self._fingerprint(key)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        """
                        UPDATE workbooks
                        SET synced_revision = revision, file_mtime_ns = ?,
                            file_size = ?, last_synced_at = ?
                        WHERE path = ?
                        """,
                        (mtime_ns, file_size, self._now(), key),
                    )
                    if cursor.rowcount != 1:
                        raise DatabaseError(
                            "A planilha ainda não foi importada para o banco local."
                        )
        except sqlite3.Error as exc:
            raise DatabaseError(
                "A planilha foi atualizada, mas o estado da sincronização não pôde ser salvo."
            ) from exc

    def reset_workbook(
        self, workbook_path: str | Path, metadata: WorkbookMetadata
    ) -> None:
        """Remove todos os registros e reinicia os metadados da planilha."""
        key = self._workbook_key(workbook_path)
        mtime_ns, file_size = self._fingerprint(key)
        now = self._now()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    workbook_id = self._workbook_id(connection, key)
                    connection.execute(
                        "DELETE FROM entries WHERE workbook_id = ?", (workbook_id,)
                    )
                    cursor = connection.execute(
                        """
                        UPDATE workbooks
                        SET activity_types_json = ?, ticket_types_json = ?,
                            phases_json = ?, recent_numbers_json = '[]',
                            revision = revision + 1,
                            synced_revision = revision + 1,
                            file_mtime_ns = ?, file_size = ?, updated_at = ?,
                            last_synced_at = ?
                        WHERE id = ?
                        """,
                        (
                            json.dumps(metadata.activity_types, ensure_ascii=False),
                            json.dumps(metadata.ticket_types, ensure_ascii=False),
                            json.dumps(metadata.phases, ensure_ascii=False),
                            mtime_ns,
                            file_size,
                            now,
                            now,
                            workbook_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise DatabaseError(
                            "A planilha ainda não foi importada para o banco local."
                        )
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Não foi possível limpar o banco de dados local."
            ) from exc
