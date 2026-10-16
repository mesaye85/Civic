# Data

## `seed_structural_democracy_data.csv`

Ten countries with values for all 19 indicators. These values are **illustrative and unsourced**. I entered them by hand to exercise the pipeline. They are not assessments of these countries and have no definitions or sources attached. Do not cite them.

The file also has a `Democracy_Status` column with hand-entered values. The scorer ignores that column and computes `Democracy_Status` from the indicators.

## `governance_index_template.csv`

This is an empty template for contributions. Its header lists every field in `schema/schema.json` in schema order: `Country`, then each `*_Score` followed by its `*_definition` and `*_source`, then `Democracy_Status`. Leave `Democracy_Status` empty because the scorer computes it. Leave a cell empty when you have no value for it. An empty cell counts as missing, never as zero.
