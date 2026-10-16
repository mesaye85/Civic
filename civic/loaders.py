"""Pluggable input loaders.

A loader takes ``(path, schema)`` and returns a list of records (dicts keyed by
schema field name). Register a new format with ``@register_loader(".ext")``.
Loaders only read; validation and scoring happen in ``civic.scoring``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd

LOADERS: dict[str, Callable[[Path, dict], list]] = {}


class InputError(ValueError):
    """The input file is missing, unreadable, or of an unsupported type."""


def register_loader(ext: str):
    """Register ``func`` as the loader for files ending in ``ext`` (e.g. ".csv")."""
    def decorator(func):
        LOADERS[ext.lower()] = func
        return func
    return decorator


def _number_or_text(text: str):
    try:
        return float(text)
    except ValueError:
        # Left as text so schema validation rejects the row with a type error.
        return text


@register_loader(".csv")
def load_csv(path: Path, schema: dict) -> list[dict]:
    """Read a CSV. Empty cells mean "not provided"; numeric fields are parsed per cell."""
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        raise InputError(f"{path}: file is empty") from None
    frame.columns = [str(column).strip() for column in frame.columns]
    number_fields = {name for name, spec in schema["properties"].items() if spec.get("type") == "number"}
    records = []
    for row in frame.to_dict(orient="records"):
        record = {}
        for column, cell in row.items():
            text = str(cell).strip()
            if text:
                record[column] = _number_or_text(text) if column in number_fields else text
        records.append(record)
    return records


@register_loader(".json")
def load_json(path: Path, schema: dict) -> list:
    """Read a JSON list of records, or an object whose values are records.

    A null value means "not provided", the same as an empty CSV cell.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: invalid JSON ({exc})") from None
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        raise InputError(f"{path}: expected a list of records or an object of records")
    return [
        {key: value for key, value in record.items() if value is not None} if isinstance(record, dict) else record
        for record in data
    ]


def load_records(path, schema: dict) -> list:
    path = Path(path)
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        supported = ", ".join(sorted(LOADERS))
        raise InputError(f"{path}: unsupported file type '{path.suffix}' (supported: {supported})")
    if not path.is_file():
        raise InputError(f"{path}: file not found")
    return loader(path, schema)
