# Retriever Fixtures

## `cdc-epi-info-2015-annual-report.pdf`

Realistic report fixture used by Retriever live PDF and chart-understanding tests.

- Source: https://stacks.cdc.gov/view/cdc/42684
- Download URL: https://stacks.cdc.gov/view/cdc/42684/cdc_42684_DS1.pdf
- Rights: CDC Stacks marks this record as Public Domain.
- Expected chart evidence: page 6 contains `Number of Persons Trained in Epi InfoTM (All Tools), 2015`, a column/bar chart where the highest month is approximately May at 200 trainees. The live test derives page 6 from this full report at runtime to keep local Ollama vision runs bounded.
