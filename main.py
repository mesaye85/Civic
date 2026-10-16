"""CivicHorizon command-line entry point.

    python main.py [--input PATH] [--weights PATH] [--rules PATH] [--output DIR]

Scores every country in the input file with the explicit rules in rules.json
and the weights in weights.json (equal weights if that file does not exist).
See README.md for the scoring formula.
"""
from __future__ import annotations

import argparse
import os
import sys

from civic import ConfigError, InputError, assess, indicator_fields, load_records, load_rules, load_schema, load_weights
from civic.config import (
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RULES_PATH,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_WEIGHTS_PATH,
    SCORE_FIELD,
)
from civic.report import format_diagnostics, format_rejected, format_table, write_outputs


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score countries with CivicHorizon's documented rules.")
    parser.add_argument("--input", help="CSV or JSON input "
                        "(default: $CIVIC_INPUT, else data/seed_structural_democracy_data.csv)")
    parser.add_argument("--weights", help="weights JSON (default: weights.json if present, else equal weights)")
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="rules JSON (default: rules.json)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR), help="output directory (default: output/)")
    return parser.parse_args(argv)


def run(argv=None) -> int:
    args = parse_args(argv)
    input_path = args.input or os.environ.get("CIVIC_INPUT") or str(DEFAULT_INPUT_PATH)
    weights_path = args.weights
    if weights_path is None and DEFAULT_WEIGHTS_PATH.is_file():
        weights_path = str(DEFAULT_WEIGHTS_PATH)

    try:
        schema = load_schema(DEFAULT_SCHEMA_PATH)
        indicators = indicator_fields(schema)
        weights = load_weights(weights_path, indicators)
        rules = load_rules(args.rules)
        records = load_records(input_path, schema)
    except (ConfigError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    assessment = assess(records, schema, weights, rules)
    csv_path, json_path = write_outputs(assessment, schema, weights, rules, input_path, args.output)

    print("CivicHorizon rule-based assessment")
    print(f"input:   {input_path} ({len(records)} records)")
    print(f"weights: {weights_path or 'equal'} ({len(indicators)} indicators)")
    print(f"rules:   {args.rules} (threshold {rules.classification_threshold:g}, "
          f"min coverage {rules.min_weight_coverage:.0%})")
    if any(isinstance(r, dict) and SCORE_FIELD in r for r in records):
        print(f"note:    {SCORE_FIELD} values in the input are ignored; it is computed from the indicators")
    print()
    print(format_table(assessment))
    if assessment.results:
        print()
        print("Diagnostics")
        print(format_diagnostics(assessment))
    if assessment.rejected:
        print()
        print(f"Rejected {len(assessment.rejected)} record(s) that failed schema validation:")
        print(format_rejected(assessment))
    print()
    print(f"wrote {csv_path} and {json_path}")
    return 0 if assessment.results else 1


if __name__ == "__main__":
    sys.exit(run())
