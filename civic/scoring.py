"""Rule-based scoring.

For each country with a valid record:

    score    = sum(w_i * x_i for present i) / sum(w_i for present i)
    coverage = sum(w_i for present i) / sum(w_i for all i)

If coverage < rules.min_weight_coverage the country is labeled
rules.insufficient_data_label (the partial score is still reported); otherwise
it is labeled by comparing the score to rules.classification_threshold.

Sums are computed with exact fractions of the values as written, so a perfect
10 scores exactly 10.0 and equal weights give exactly the arithmetic mean; the
reported (float) score is what gets compared with the threshold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from jsonschema import Draft7Validator

from .config import COUNTRY_FIELD, Rules, indicator_fields, metadata_fields

TOP_N = 3


def _exact(value) -> Fraction:
    return Fraction(repr(float(value)))


@dataclass
class Contribution:
    value: float | None
    weight: float            # normalized over all indicators
    effective_weight: float | None  # renormalized over the indicators present
    contribution: float | None      # value * effective_weight; these sum to the score


@dataclass
class CountryResult:
    country: str
    score: float | None
    classification: str
    coverage: float
    missing_indicators: list[str]
    contributions: dict[str, Contribution]
    metadata: dict[str, str] = field(default_factory=dict)

    def _present(self) -> list[tuple[str, float]]:
        return [(name, c.contribution) for name, c in self.contributions.items() if c.contribution is not None]

    @property
    def top_contributors(self) -> list[tuple[str, float]]:
        """Largest contributions first; ties broken by indicator name."""
        return sorted(self._present(), key=lambda item: (-item[1], item[0]))[:TOP_N]

    @property
    def bottom_contributors(self) -> list[tuple[str, float]]:
        """Smallest contributions first; ties broken by indicator name."""
        return sorted(self._present(), key=lambda item: (item[1], item[0]))[:TOP_N]


@dataclass
class RejectedRecord:
    record_number: int  # 1-based position in the input (CSV data row or JSON element)
    country: str | None
    errors: list[str]


@dataclass
class Assessment:
    results: list[CountryResult]
    rejected: list[RejectedRecord]


def validate_record(record, validator: Draft7Validator, indicators: list[str]) -> list[str]:
    """Schema errors for one record, plus a finiteness check JSON Schema cannot express."""
    errors = []
    for error in sorted(validator.iter_errors(record), key=lambda e: [str(p) for p in e.path]):
        location = "/".join(str(part) for part in error.path)
        errors.append(f"{location}: {error.message}" if location else error.message)
    if isinstance(record, dict):
        for name in indicators:
            value = record.get(name)
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(f"{name}: {value} is not a finite number")
    return errors


def score_record(record: dict, weights: dict[str, float], rules: Rules, schema: dict) -> CountryResult:
    """Score one already-validated record."""
    indicators = indicator_fields(schema)
    present = [name for name in indicators if record.get(name) is not None]
    missing = [name for name in indicators if record.get(name) is None]

    exact_weights = {name: _exact(weights[name]) for name in indicators}
    total_weight = sum(exact_weights.values())
    present_weight = sum((exact_weights[name] for name in present), Fraction(0))
    coverage = present_weight / total_weight

    if present_weight > 0:
        score = sum(exact_weights[n] * _exact(record[n]) for n in present) / present_weight
    else:
        score = None

    if score is None or float(coverage) < rules.min_weight_coverage:
        classification = rules.insufficient_data_label
    elif float(score) >= rules.classification_threshold:
        classification = rules.label_at_or_above_threshold
    else:
        classification = rules.label_below_threshold

    contributions = {}
    for name in indicators:
        weight = exact_weights[name] / total_weight
        if name in present and present_weight > 0:
            effective = exact_weights[name] / present_weight
            contributions[name] = Contribution(
                value=float(record[name]),
                weight=float(weight),
                effective_weight=float(effective),
                contribution=float(effective * _exact(record[name])),
            )
        else:
            value = record.get(name)
            contributions[name] = Contribution(
                value=None if value is None else float(value),
                weight=float(weight),
                effective_weight=None,
                contribution=None,
            )

    metadata = {name: record[name] for name in metadata_fields(schema) if record.get(name) is not None}
    return CountryResult(
        country=record[COUNTRY_FIELD],
        score=None if score is None else float(score),
        classification=classification,
        coverage=float(coverage),
        missing_indicators=missing,
        contributions=contributions,
        metadata=metadata,
    )


def assess(records: list, schema: dict, weights: dict[str, float], rules: Rules) -> Assessment:
    """Validate every record, reject invalid or duplicate ones, and score the rest.

    Only countries present in ``records`` are assessed; nothing is padded or imputed.
    """
    validator = Draft7Validator(schema)
    indicators = indicator_fields(schema)

    names = [r.get(COUNTRY_FIELD) if isinstance(r, dict) else None for r in records]
    duplicates = {n for n in names if isinstance(n, str) and names.count(n) > 1}

    results, rejected = [], []
    for number, record in enumerate(records, start=1):
        country = names[number - 1] if isinstance(names[number - 1], str) else None
        errors = validate_record(record, validator, indicators)
        if country in duplicates:
            errors.append(f"{COUNTRY_FIELD}: '{country}' appears more than once; each country must appear once")
        if errors:
            rejected.append(RejectedRecord(number, country, errors))
            continue
        results.append(score_record(record, weights, rules, schema))
    return Assessment(results, rejected)
