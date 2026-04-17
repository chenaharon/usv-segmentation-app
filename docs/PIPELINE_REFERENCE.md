# Pipeline Reference

Reference for the orchestration API and stage behavior.

## Entry points

- UI entry point: `app.py`
- Programmatic entry point: `pipeline.execute_pipeline(...)`
- Core orchestration: `pipeline.run_pipeline(...)`

## `PipelineOptions`

Main options:

- `root_folder`: selected dataset root
- `output_dir`: optional output directory
- `years`: optional selected year list
- `want_syllables_xlsx`: emit segmentation workbook
- `want_metadata_xlsx`: emit metadata inventory workbook
- `metadata_only`: skip segmentation and only build inventory
- `run_classification`: enable/disable CNN syllable classification
- `subfolder_filters`: per-year relative path filters
- `metadata_file_overrides`: per-year explicit metadata workbook paths

## Run summary (`RunSummary`)

Important counters:

- metadata rows scanned
- resolved WAV files
- segmentation success/failure counts
- recordings with zero syllables
- total syllable rows
- output file list
- error message list

Derived properties:

- recordings with syllables in output
- recordings without syllable rows

## Supported metadata styles

Canonical required metadata columns:

- `Mother`, `Mother Genotype`, `Name`, `Sex`, `Offspring Genotype`, `Day`, `Session`, `Recording Number`

Alias normalization supports common variants (including Hebrew labels and `Gender` equivalents).

## Stage sequence (per year)

When segmentation mode is enabled, per-year processing follows:

1. Metadata discovery and row parsing
2. Recording path resolution
3. Segmentation per recording
4. Segmentation workbook write
5. Segmentation workbook read-back
6. Basic feature computation
7. Optional CNN classification
8. Column enrichment and final ordering
9. Inventory syllable-count merge

When metadata-only or recordings-scan-only modes are selected, segmentation stages are skipped.

## Output naming

Timestamp format:

- `YYYY-MM-DD_HH-MM-SS`

Examples:

- `segmentation_2015_<timestamp>.xlsx`
- `segmentation_classification_2023_<timestamp>.xlsx`
- `recordings_metadata_2018_<timestamp>.xlsx`
- `<stem>_summary.xlsx`

## Summary workbook schema

Columns:

- `Year`
- `Total mice (pups)`
- `Total recordings`
- `Total syllables`
- `Mice with syllables detected`
- `Recordings with syllables`

## Model fallback behavior

If classification model resolution/loading fails, syllable class column is set to fallback class `10`.
