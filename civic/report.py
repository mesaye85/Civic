"""Write and print assessment results."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .config import COUNTRY_FIELD, SCORE_FIELD, Rules, indicator_fields
from .scoring import Assessment, CountryResult

CLASSIFICATION_FIELD = "Classification"
COVERAGE_FIELD = "Weight_Coverage"
MISSING_FIELD = "Missing_Indicators"


def _ranked_entries(result: CountryResult, ranked: list[tuple[str, float]]) -> list[dict]:
    return [
        {"indicator": name, "value": result.contributions[name].value, "contribution": contribution}
        for name, contribution in ranked
    ]


def result_to_dict(result: CountryResult) -> dict:
    return {
        "country": result.country,
        "score": result.score,
        "classification": result.classification,
        "weight_coverage": result.coverage,
        "missing_indicators": result.missing_indicators,
        "top_contributors": _ranked_entries(result, result.top_contributors),
        "bottom_contributors": _ranked_entries(result, result.bottom_contributors),
        "contributions": {
            name: {
                "value": c.value,
                "weight": c.weight,
                "effective_weight": c.effective_weight,
                "contribution": c.contribution,
            }
            for name, c in result.contributions.items()
        },
        "metadata": result.metadata,
    }


def assessment_to_dict(assessment: Assessment, weights: dict, rules: Rules, input_path) -> dict:
    return {
        "input": str(input_path),
        "rules": rules.to_dict(),
        "weights": weights,
        "countries": [result_to_dict(r) for r in assessment.results],
        "rejected": [
            {"record_number": r.record_number, "country": r.country, "errors": r.errors}
            for r in assessment.rejected
        ],
    }


def csv_columns(schema: dict) -> list[str]:
    inputs = [name for name in schema["properties"] if name not in (COUNTRY_FIELD, SCORE_FIELD)]
    contributions = [f"{name}_contribution" for name in indicator_fields(schema)]
    return [COUNTRY_FIELD, SCORE_FIELD, CLASSIFICATION_FIELD, COVERAGE_FIELD, MISSING_FIELD] + inputs + contributions


def result_to_row(result: CountryResult) -> dict:
    row = {
        COUNTRY_FIELD: result.country,
        SCORE_FIELD: result.score,
        CLASSIFICATION_FIELD: result.classification,
        COVERAGE_FIELD: result.coverage,
        MISSING_FIELD: ";".join(result.missing_indicators),
    }
    for name, c in result.contributions.items():
        row[name] = c.value
        row[f"{name}_contribution"] = c.contribution
    row.update(result.metadata)
    return row


def write_outputs(assessment: Assessment, schema: dict, weights: dict, rules: Rules,
                  input_path, output_dir) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "scores.csv"
    json_path = output_dir / "scores.json"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns(schema))
        writer.writeheader()
        for result in assessment.results:
            writer.writerow(result_to_row(result))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(assessment_to_dict(assessment, weights, rules, input_path), handle, indent=2)
        handle.write("\n")
    return csv_path, json_path


def _fmt_score(score) -> str:
    return "n/a" if score is None else f"{score:.2f}"


def format_table(assessment: Assessment) -> str:
    if not assessment.results:
        return "No valid country records to score."
    width = max(len("Country"), *(len(r.country) for r in assessment.results))
    lines = [f"{'Country':<{width}}  {'Score':>5}  {'Coverage':>8}  Status"]
    lines.append("-" * len(lines[0]) + "-" * 12)
    for r in assessment.results:
        lines.append(f"{r.country:<{width}}  {_fmt_score(r.score):>5}  {r.coverage:>8.0%}  {r.classification}")
    return "\n".join(lines)


def _fmt_ranked(result: CountryResult, ranked: list[tuple[str, float]]) -> str:
    return ", ".join(f"{name}={result.contributions[name].value:g} (+{c:.3f})" for name, c in ranked) or "none"


def format_diagnostics(assessment: Assessment) -> str:
    blocks = []
    for r in assessment.results:
        blocks.append("\n".join([
            f"{r.country}: {_fmt_score(r.score)} -> {r.classification}",
            f"  highest: {_fmt_ranked(r, r.top_contributors)}",
            f"  lowest:  {_fmt_ranked(r, r.bottom_contributors)}",
            f"  missing: {', '.join(r.missing_indicators) or 'none'}",
        ]))
    return "\n".join(blocks)


def format_rejected(assessment: Assessment) -> str:
    lines = []
    for r in assessment.rejected:
        label = r.country if r.country is not None else "(no valid Country)"
        lines.append(f"record {r.record_number} {label}:")
        lines.extend(f"  - {error}" for error in r.errors)
    return "\n".join(lines)
