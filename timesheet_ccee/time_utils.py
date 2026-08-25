from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from openpyxl.utils.datetime import from_excel


def mask_duration_input(value: Any) -> str:
    """Aplica progressivamente a máscara HH:MM durante a digitação."""
    text = str(value or "")
    if ":" in text:
        hours_part, minutes_part = text.split(":", 1)
        hours = re.sub(r"\D", "", hours_part)[:2]
        minutes = re.sub(r"\D", "", minutes_part)[:2]
        return f"{hours}:{minutes}"

    digits = re.sub(r"\D", "", text)[:4]
    if len(digits) <= 2:
        return digits
    return f"{digits[:2]}:{digits[2:]}"


def parse_duration(value: Any, *, allow_zero: bool = False) -> int:
    """Converte HH:mm, 7h30 ou horas decimais em minutos."""
    text = str(value or "").strip().lower().replace(" ", "")
    if not text:
        raise ValueError("Informe as horas no formato HH:mm, por exemplo 07:30.")

    minutes: int
    clock_match = re.fullmatch(r"(\d{1,3}):(\d{1,2})", text)
    hours_match = re.fullmatch(r"(\d{1,3})h(?:(\d{1,2}))?", text)

    if clock_match or hours_match:
        match = clock_match or hours_match
        assert match is not None
        hours_part = int(match.group(1))
        minutes_part = int(match.group(2) or 0)
        if minutes_part > 59:
            raise ValueError("Os minutos devem estar entre 00 e 59.")
        minutes = (hours_part * 60) + minutes_part
    else:
        normalized = text.replace(",", ".")
        try:
            decimal_hours = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(
                "Formato de horas inválido. Use HH:mm, 7h30 ou 7,5."
            ) from exc
        if decimal_hours < 0:
            raise ValueError("O tempo não pode ser negativo.")
        minutes = int(
            (decimal_hours * Decimal(60)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    if minutes < 0 or (minutes == 0 and not allow_zero):
        raise ValueError("O tempo precisa ser maior que zero.")
    if minutes > 1440:
        raise ValueError("O tempo de uma atividade não pode ultrapassar 24 horas.")
    return minutes


def format_duration(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours, remainder = divmod(minutes, 60)
    return f"{hours:02d}:{remainder:02d}"


def excel_duration_to_minutes(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, timedelta):
        return int(round(value.total_seconds() / 60))
    if isinstance(value, datetime):
        return (value.hour * 60) + value.minute + round(value.second / 60)
    if isinstance(value, time):
        return (value.hour * 60) + value.minute + round(value.second / 60)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(round(float(value) * 1440))
    return parse_duration(value, allow_zero=True)


def excel_value_to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = from_excel(value)
        return converted.date() if isinstance(converted, datetime) else converted
    if isinstance(value, str):
        for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
            try:
                return datetime.strptime(value.strip(), pattern).date()
            except ValueError:
                continue
    return None


def parse_br_date(value: str) -> date:
    text = value.strip()
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError("Data inválida. Use o formato DD/MM/AAAA.")


def format_br_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")
