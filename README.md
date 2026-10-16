# CivicHorizon

CivicHorizon is a small Python tool that scores countries on 19 structural governance indicators with explicit, documented rules. Each indicator is a 0–10 value supplied in the input. The tool validates each record against a JSON Schema, takes a weighted mean, and labels the result against a fixed threshold. It also reports how much each indicator contributed. There is no trained model or imputation, so every score can be traced to the input values, the weights and the rules.

## The rules

Three files define how a score is computed.

- **[`schema/schema.json`](schema/schema.json)** defines the fields. The indicators are the 19 numeric `*_Score` fields. Each one may carry a `*_definition` and a `*_source` string. Those strings are copied to the output but are never scored. `Democracy_Status` is the computed score and is not an input.
- **`weights.json`** is optional. It maps indicator names to non-negative numbers. Indicators you don't list default to `1.0`, so without the file every indicator has equal weight. Weights are normalized to sum to 1. An unknown key (including a metadata field or `Democracy_Status`), a negative weight, or all-zero weights stops the run with an error.
- **[`rules.json`](rules.json)** sets the classification rules:

| Key | Default | Meaning |
|---|---|---|
| `classification_threshold` | `5.0` | The score that separates the two labels below. |
| `label_at_or_above_threshold` | `"Democratic"` | The label for a score at or above the threshold. |
| `label_below_threshold` | `"Non-Democratic"` | The label for a score below the threshold. |
| `min_weight_coverage` | `1.0` | The share of total weight that must be present. `1.0` means every indicator is required. |
| `insufficient_data_label` | `"Insufficient data"` | The label given when coverage falls below the minimum. |

For each country, *P* is the set of indicators that have a value and *w* is the normalized weight:

```
score    = Σ(w_i · x_i for i in P) / Σ(w_i for i in P)
coverage = Σ(w_i for i in P) / Σ(w_i for all indicators)

if coverage < min_weight_coverage:   status = insufficient_data_label
elif score >= classification_threshold: status = label_at_or_above_threshold
else:                                status = label_below_threshold
```

A missing value is treated as missing, never as zero. The partial score and the coverage are still reported for a country labeled insufficient. A perfect 10 on every indicator scores exactly 10.0.

A record is rejected and listed in the report, rather than scored, when it fails the schema. That covers a missing `Country`, a non-numeric value, a value outside 0–10, or a column that isn't in the schema. A country name that appears more than once is also rejected. Only countries in the input are assessed.

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python main.py
```

```
python main.py [--input PATH] [--weights PATH] [--rules PATH] [--output DIR]
```

- `--input` takes a CSV or JSON file. It defaults to `$CIVIC_INPUT` if that is set, and otherwise to `data/seed_structural_democracy_data.csv`.
- `--weights` defaults to `weights.json` if that file exists, and otherwise to equal weights.
- `--rules` defaults to `rules.json`.
- `--output` defaults to `output/`.

The run prints a table of country, score, coverage and status. Below it, each country gets its three highest and three lowest contributors and its missing indicators, followed by any rejected records with the reasons.

On the bundled seed data, every Democratic score falls between 8.61 and 8.93 and every Non-Democratic score between 1.36 and 2.56:

```
Country       Score  Coverage  Status
-------------------------------------------------
Norway         8.90      100%  Democratic
North Korea    1.36      100%  Non-Democratic
...
```

## Input format

- **CSV** has one row per country, and its columns are schema field names. An empty cell means the value is missing. [`data/governance_index_template.csv`](data/governance_index_template.csv) has every field in schema order.
- **JSON** is either a list of records or an object whose values are records. A `null` or absent key means the value is missing.

Both loaders produce the same records, and the tests check this. To add a format, write a function `(path, schema) -> list[dict]` and decorate it with `@register_loader(".ext")` in [`civic/loaders.py`](civic/loaders.py).

If the input has a `Democracy_Status` value, the tool ignores it and computes the score itself.

## Outputs

The tool writes two files.

- `output/scores.csv` has one row per scored country: `Country`, `Democracy_Status` (the score), `Classification`, `Weight_Coverage`, `Missing_Indicators`, every input field, and an `<indicator>_contribution` column for each indicator.
- `output/scores.json` records the input path, the rules and normalized weights that were applied, and one entry per country. Each entry holds the score, classification, coverage, missing indicators, top and bottom contributors, a per-indicator block (`value`, `weight`, `effective_weight`, `contribution`) and metadata. The file ends with the list of rejected records and their errors.

`weight` is the normalized weight across all 19 indicators. `effective_weight` is the weight renormalized over the indicators present. Each contribution equals `value × effective_weight`, and a country's contributions add up to its score.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
flake8 . --exclude venv,.venv --max-complexity=10 --max-line-length=127
```

The tests cover these cases:

- Exact scoring at 10.0 and at the threshold, and that metadata carries no weight.
- Weight normalization, custom weights, and rejection of unknown or negative weights.
- Partial data, both with and without a lowered `min_weight_coverage`.
- Rejection of out-of-range, non-numeric, NaN and duplicate records.
- Matching results from the CSV and JSON loaders.
- An end-to-end run on the seed data, the contents of the output files, and the CLI's error exits.

CI runs flake8 and pytest on Python 3.11 ([`.github/workflows/python-app.yml`](.github/workflows/python-app.yml)).

## Logical limitations

- **The indicator values are hand-scored judgments.** [`CONTRIBUTIONS.md`](CONTRIBUTIONS.md) asks for verifiable, quantitative sources. The tool, however, receives numbers that a person has already scored, and it cannot check how they were produced. The rules make the aggregation reproducible, but they do nothing to make the inputs objective.
- **Equal weights and the 5.0 threshold are choices, not findings.** Nothing in the data establishes that the indicators matter equally, or that 5.0 separates two kinds of political system. Changing either one can change labels.
- **A binary label hides gradation.** A country at 5.0 and a country at 9.9 get the same label, while 4.9 and 5.0 get different ones. The score carries more information than the label does.
- **The indicators likely overlap.** Several of them probably measure related things, such as Participation Accessibility, Pathway to Influence and Exit vs Voice Behavior. Under equal weights, a trait that several indicators share is counted more than once. I haven't tested for correlation.
- **The seed data is illustrative and unsourced** (see [`data/README.md`](data/README.md)). The seed scores show that the pipeline runs. They are not assessments of those countries.
- **The percentile quantification scale in CONTRIBUTIONS.md is not implemented.** The tool does not convert raw measurements to 0–10 percentiles, so it expects inputs that have already been scored.
- **There is no time dimension.** Each record is one snapshot, with no year field and no way to track change.
- **The variable names in CONTRIBUTIONS.md don't map 1:1 to the schema's field names yet.** For example, "Sub-national Autonomy" there appears, by its position, to correspond to `Local_Governance_Score` here, and the sample CSV header in that file uses names the schema doesn't have.

## History

Earlier versions trained a random-forest classifier on labels that were derived from the same features with the same 5.0 threshold, which made the reported accuracy circular. They also filled missing values with a linear regression and padded every country absent from the input with zeros. I removed all three so that every score traces to the explicit rules above.

## License

MIT. See [`LICENSE`](LICENSE).
