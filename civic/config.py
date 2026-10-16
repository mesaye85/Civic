"""Schema, weights and rules: everything that decides how a score is computed."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from jsonschema import Draft7Validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schema" / "schema.json"
DEFAULT_RULES_PATH = PROJECT_ROOT / "rules.json"
DEFAULT_WEIGHTS_PATH = PROJECT_ROOT / "weights.json"
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "seed_structural_democracy_data.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

COUNTRY_FIELD = "Country"
SCORE_FIELD = "Democracy_Status"


class ConfigError(ValueError):
    """The schema, weights or rules file is missing or invalid."""


def read_json(path) -> object:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise ConfigError(f"{path}: file not found") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from None


def load_schema(path=DEFAULT_SCHEMA_PATH) -> dict:
    schema = read_json(path)
    Draft7Validator.check_schema(schema)
    return schema


def indicator_fields(schema: dict) -> list[str]:
    """Scored fields: every numeric schema property except the output score itself."""
    return [
        name for name, spec in schema["properties"].items()
        if spec.get("type") == "number" and name != SCORE_FIELD
    ]


def metadata_fields(schema: dict) -> list[str]:
    """Descriptive fields (*_definition, *_source): carried to output, never scored."""
    return [
        name for name, spec in schema["properties"].items()
        if spec.get("type") == "string" and name != COUNTRY_FIELD
    ]


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_weights(raw: dict | None, indicators: list[str]) -> dict[str, float]:
    """Validate raw weights and scale them to sum to 1.

    Indicators not listed in ``raw`` get weight 1.0 before normalization, so an
    empty mapping means equal weights.
    """
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise ConfigError("weights must be a JSON object mapping indicator names to numbers")
    unknown = sorted(set(raw) - set(indicators))
    if unknown:
        raise ConfigError(
            f"unknown weight key(s): {', '.join(unknown)}. Weights can only be set for the "
            f"{len(indicators)} indicator fields; metadata fields and {SCORE_FIELD} are never scored."
        )
    weights = {}
    for name in indicators:
        value = raw.get(name, 1.0)
        if not _is_finite_number(value):
            raise ConfigError(f"weight for {name} must be a finite number, got {value!r}")
        if value < 0:
            raise ConfigError(f"weight for {name} must not be negative, got {value}")
        weights[name] = float(value)
    total = math.fsum(weights.values())
    if total <= 0:
        raise ConfigError("at least one weight must be greater than zero")
    return {name: value / total for name, value in weights.items()}


def load_weights(path, indicators: list[str]) -> dict[str, float]:
    """Load weights from a JSON file, or equal weights when ``path`` is None."""
    return normalize_weights(None if path is None else read_json(path), indicators)


@dataclass(frozen=True)
class Rules:
    """Classification rules. Defaults match the committed rules.json."""

    classification_threshold: float = 5.0
    label_at_or_above_threshold: str = "Democratic"
    label_below_threshold: str = "Non-Democratic"
    min_weight_coverage: float = 1.0
    insufficient_data_label: str = "Insufficient data"

    def to_dict(self) -> dict:
        return asdict(self)


RULES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "classification_threshold",
        "label_at_or_above_threshold",
        "label_below_threshold",
        "min_weight_coverage",
        "insufficient_data_label",
    ],
    "properties": {
        "description": {"type": "string"},
        "classification_threshold": {"type": "number", "minimum": 0, "maximum": 10},
        "label_at_or_above_threshold": {"type": "string", "minLength": 1},
        "label_below_threshold": {"type": "string", "minLength": 1},
        "min_weight_coverage": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "insufficient_data_label": {"type": "string", "minLength": 1},
    },
}


def parse_rules(raw: object) -> Rules:
    errors = sorted(Draft7Validator(RULES_SCHEMA).iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, e.path)) or 'rules'}: {e.message}" for e in errors)
        raise ConfigError(f"invalid rules: {details}")
    for key in ("classification_threshold", "min_weight_coverage"):
        if not math.isfinite(raw[key]):
            raise ConfigError(f"invalid rules: {key} must be a finite number")
    labels = [raw["label_at_or_above_threshold"], raw["label_below_threshold"], raw["insufficient_data_label"]]
    if len(set(labels)) != len(labels):
        raise ConfigError("invalid rules: the three labels must be different from each other")
    fields = {key: value for key, value in raw.items() if key != "description"}
    return Rules(**fields)


def load_rules(path=DEFAULT_RULES_PATH) -> Rules:
    return parse_rules(read_json(path))
