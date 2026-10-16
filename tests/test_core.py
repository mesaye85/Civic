import csv
import json

import pytest

import main
from civic import (
    ConfigError,
    Rules,
    assess,
    indicator_fields,
    load_records,
    load_rules,
    load_schema,
    load_weights,
    metadata_fields,
    normalize_weights,
    parse_rules,
)
from civic.config import DEFAULT_INPUT_PATH, DEFAULT_RULES_PATH, DEFAULT_SCHEMA_PATH

SCHEMA = load_schema(DEFAULT_SCHEMA_PATH)
INDICATORS = indicator_fields(SCHEMA)
EQUAL = normalize_weights(None, INDICATORS)
RULES = Rules()


def record(country="Testland", value=10.0, **overrides):
    row = {"Country": country}
    row.update({name: value for name in INDICATORS})
    row.update(overrides)
    return row


def score_one(row, weights=EQUAL, rules=RULES):
    assessment = assess([row], SCHEMA, weights, rules)
    assert not assessment.rejected, assessment.rejected
    return assessment.results[0]


def test_indicators_are_the_19_score_fields():
    assert len(INDICATORS) == 19
    assert all(name.endswith("_Score") for name in INDICATORS)
    assert "Democracy_Status" not in INDICATORS
    assert len(metadata_fields(SCHEMA)) == 38


def test_committed_rules_file_matches_documented_defaults():
    assert load_rules(DEFAULT_RULES_PATH) == Rules()


def test_perfect_ten_scores_exactly_ten():
    result = score_one(record())
    assert result.score == 10.0
    assert result.coverage == 1.0
    assert result.classification == RULES.label_at_or_above_threshold


def test_score_exactly_at_threshold_gets_at_or_above_label():
    assert score_one(record(value=5.0)).classification == "Democratic"
    assert score_one(record(value=4.99)).classification == "Non-Democratic"


def test_metadata_fields_carry_zero_weight_and_pass_through():
    plain = record(value=7.0)
    annotated = dict(plain)
    for name in metadata_fields(SCHEMA):
        annotated[name] = "documented"
    a, b = score_one(plain), score_one(annotated)
    assert a.score == b.score == 7.0
    assert set(EQUAL) == set(INDICATORS)
    assert not set(b.contributions) & set(metadata_fields(SCHEMA))
    assert b.metadata == {name: "documented" for name in metadata_fields(SCHEMA)}


def test_default_weights_are_equal_and_normalized():
    assert sum(EQUAL.values()) == pytest.approx(1.0)
    assert all(value == pytest.approx(1 / 19) for value in EQUAL.values())


def test_custom_weights_are_normalized_and_applied(tmp_path):
    first, second = INDICATORS[0], INDICATORS[1]
    path = tmp_path / "weights.json"
    path.write_text(json.dumps({first: 4, second: 0}))
    weights = load_weights(path, INDICATORS)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights[first] == pytest.approx(4 / 21)  # 4 + 17 unlisted indicators at 1.0
    assert weights[second] == 0.0

    row = record(value=5.0, **{first: 10.0, second: 0.0})
    expected = (4 * 10.0 + 17 * 5.0) / 21
    result = score_one(row, weights)
    assert result.score == pytest.approx(expected)
    assert sum(c.contribution for c in result.contributions.values()) == pytest.approx(result.score)


@pytest.mark.parametrize("bad, message", [
    ({"Not_A_Field": 1}, "unknown weight key"),
    ({"Leadership_Turnover_Score_source": 1}, "unknown weight key"),
    ({"Democracy_Status": 1}, "unknown weight key"),
    ({"Leadership_Turnover_Score": -1}, "must not be negative"),
    ({"Leadership_Turnover_Score": "2"}, "finite number"),
    ({name: 0 for name in indicator_fields(SCHEMA)}, "greater than zero"),
])
def test_invalid_weights_raise(bad, message):
    with pytest.raises(ConfigError, match=message):
        normalize_weights(bad, INDICATORS)


def test_missing_indicator_is_insufficient_with_partial_score_and_coverage():
    row = record(value=8.0)
    del row[INDICATORS[0]]
    row[INDICATORS[1]] = 2.0
    result = score_one(row)
    assert result.classification == RULES.insufficient_data_label
    assert result.missing_indicators == [INDICATORS[0]]
    assert result.coverage == pytest.approx(18 / 19)
    assert result.score == pytest.approx((17 * 8.0 + 2.0) / 18)
    assert result.contributions[INDICATORS[0]].contribution is None


def test_lower_min_coverage_allows_partial_scoring():
    row = record(value=8.0)
    del row[INDICATORS[0]]
    rules = Rules(min_weight_coverage=0.9)
    result = score_one(row, rules=rules)
    assert result.coverage == pytest.approx(18 / 19)
    assert result.score == pytest.approx(8.0)
    assert result.classification == "Democratic"


def test_country_with_no_indicators_is_insufficient():
    result = score_one({"Country": "Emptyland"}, rules=Rules(min_weight_coverage=0.01))
    assert result.score is None
    assert result.coverage == 0.0
    assert result.classification == RULES.insufficient_data_label


@pytest.mark.parametrize("bad_value", [11, -0.5, "high", float("nan")])
def test_invalid_value_is_rejected_and_reported(bad_value):
    good = record("Goodland", 6.0)
    bad = record("Badland", 6.0, **{INDICATORS[2]: bad_value})
    assessment = assess([good, bad], SCHEMA, EQUAL, RULES)
    assert [r.country for r in assessment.results] == ["Goodland"]
    assert len(assessment.rejected) == 1
    rejected = assessment.rejected[0]
    assert rejected.country == "Badland"
    assert rejected.record_number == 2
    assert any(INDICATORS[2] in error for error in rejected.errors)


def test_unknown_column_and_missing_country_are_rejected():
    assessment = assess([record(Extra_Field=1), {INDICATORS[0]: 5.0}], SCHEMA, EQUAL, RULES)
    assert assessment.results == []
    assert len(assessment.rejected) == 2


def test_duplicate_country_is_rejected():
    assessment = assess([record("Twinland"), record("Twinland", 2.0)], SCHEMA, EQUAL, RULES)
    assert assessment.results == []
    assert [r.record_number for r in assessment.rejected] == [1, 2]


def test_only_input_countries_are_assessed():
    assessment = assess([record("Onlyland", 6.0)], SCHEMA, EQUAL, RULES)
    assert [r.country for r in assessment.results] == ["Onlyland"]


def test_invalid_rules_raise():
    raw = Rules().to_dict()
    with pytest.raises(ConfigError, match="min_weight_coverage"):
        parse_rules({**raw, "min_weight_coverage": 1.5})
    with pytest.raises(ConfigError, match="labels must be different"):
        parse_rules({**raw, "label_below_threshold": "Democratic"})
    with pytest.raises(ConfigError):
        parse_rules({**raw, "unexpected": 1})


def test_csv_and_json_loaders_produce_identical_results(tmp_path):
    rows = [
        record("Alpha", 7.5, **{f"{INDICATORS[0]}_source": "Annual report 2024"}),
        record("Beta", 3.0),
    ]
    del rows[1][INDICATORS[4]]
    csv_path, json_path = tmp_path / "in.csv", tmp_path / "in.json"
    columns = list(SCHEMA["properties"])
    with open(csv_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows))

    from_csv = assess(load_records(csv_path, SCHEMA), SCHEMA, EQUAL, RULES)
    from_json = assess(load_records(json_path, SCHEMA), SCHEMA, EQUAL, RULES)
    assert from_csv == from_json
    assert [r.classification for r in from_csv.results] == ["Democratic", "Insufficient data"]


def test_seed_data_end_to_end(tmp_path, capsys):
    exit_code = main.run(["--input", str(DEFAULT_INPUT_PATH), "--output", str(tmp_path)])
    assert exit_code == 0
    printed = capsys.readouterr().out
    assert "Norway" in printed and "Diagnostics" in printed

    report = json.loads((tmp_path / "scores.json").read_text())
    status = {c["country"]: c["classification"] for c in report["countries"]}
    scores = {c["country"]: c["score"] for c in report["countries"]}
    assert len(status) == 10
    assert report["rejected"] == []
    for country in ["Norway", "Sweden", "New Zealand", "Switzerland", "Canada"]:
        assert scores[country] >= 5.0
        assert status[country] == "Democratic"
    for country in ["North Korea", "Eritrea", "Iran", "Russia", "Saudi Arabia"]:
        assert scores[country] < 5.0
        assert status[country] == "Non-Democratic"


def test_output_files_include_contributions(tmp_path):
    rows = [record("Alpha", 7.0), record("Beta", 9.0, **{INDICATORS[0]: 11})]
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(rows))
    out = tmp_path / "out"
    assert main.run(["--input", str(input_path), "--output", str(out)]) == 0

    report = json.loads((out / "scores.json").read_text())
    alpha = report["countries"][0]
    assert alpha["country"] == "Alpha"
    assert set(alpha["contributions"]) == set(INDICATORS)
    assert sum(c["contribution"] for c in alpha["contributions"].values()) == pytest.approx(alpha["score"])
    assert len(alpha["top_contributors"]) == 3 and len(alpha["bottom_contributors"]) == 3
    assert report["rejected"][0]["country"] == "Beta"
    assert report["rules"] == Rules().to_dict()

    with open(out / "scores.csv", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert [row["Country"] for row in written] == ["Alpha"]
    assert float(written[0]["Democracy_Status"]) == pytest.approx(7.0)
    assert float(written[0][f"{INDICATORS[0]}_contribution"]) == pytest.approx(7.0 / 19)


def test_civic_input_env_var_is_honored(tmp_path, monkeypatch):
    input_path = tmp_path / "env.json"
    input_path.write_text(json.dumps([record("Envland", 4.0)]))
    monkeypatch.setenv("CIVIC_INPUT", str(input_path))
    assert main.run(["--output", str(tmp_path / "out")]) == 0
    report = json.loads((tmp_path / "out" / "scores.json").read_text())
    assert [c["country"] for c in report["countries"]] == ["Envland"]


def test_unsupported_input_type_and_bad_weights_exit_with_error(tmp_path, capsys):
    bad_input = tmp_path / "in.txt"
    bad_input.write_text("x")
    assert main.run(["--input", str(bad_input), "--output", str(tmp_path)]) == 2
    weights = tmp_path / "w.json"
    weights.write_text(json.dumps({"Unknown": 1}))
    assert main.run(["--weights", str(weights), "--output", str(tmp_path)]) == 2
    assert "unknown weight key" in capsys.readouterr().err
