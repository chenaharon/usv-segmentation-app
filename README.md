# USV Segmentation Desktop (`segmentation-app`)

Desktop application for processing mouse USV recordings end-to-end:

- recording discovery from folder trees
- metadata matching (including flexible column aliases)
- syllable segmentation
- feature enrichment
- optional CNN-based syllable classification
- export of rich Excel outputs and run summaries

This repository is focused on the desktop app experience (`app.py`) and the orchestration engine (`pipeline.py`).

## Table of contents

- [Quick start](#quick-start)
- [What the app does](#what-the-app-does)
- [Input data layouts](#input-data-layouts)
- [Outputs](#outputs)
- [Model weights](#model-weights)
- [Programmatic API](#programmatic-api)
- [Project structure](#project-structure)
- [Documentation map](#documentation-map)

## Quick start

### Run from source

```bash
pip install -r requirements.txt
python app.py
```

### Build distributables

See `docs/BUILD.md` for:

- Windows portable EXE
- Windows installer (Inno Setup)
- macOS `.app` bundle

## What the app does

The app processes one or more selected years and can run in different modes:

- **Segmentation + Classification**: full flow including CNN label assignment.
- **Segmentation**: segmentation and derived columns, without CNN classes.
- **With Recordings Files Scan**: also emits inventory workbook for resolved recordings.
- **Only Recordings Files Scan**: scans recordings and metadata mapping only (no segmentation).

The UI supports:

- per-year selection
- nested per-folder filtering (checkbox tree)
- optional manual metadata workbook override per year
- real-time progress, elapsed time, and logs
- results and outputs browsers

## Input data layouts

The pipeline supports multiple layouts.

### 1) Client year-folder layout

Example:

```
2023/
  metadata_file.xlsx
  Mother_Genotype/
    Pup_Genotype/
      day_6/
        session2/
          T0000054.wav
```

### 2) Classic dataset layout

Example:

```
metadata/
  Metadata Recording Mapping (2023).xlsx
USV_Recordings/
  2023/
    Mother_Genotype/
      Pup_Genotype/
        day_6/
          session2/
            T0000054.wav
```

### Metadata columns

Canonical required columns:

- `Mother`
- `Mother Genotype`
- `Name`
- `Sex`
- `Offspring Genotype`
- `Day`
- `Session`
- `Recording Number`

Aliases are supported (including common English/Hebrew variants such as `Gender`, `מין`, `מגדר`).

## Outputs

Timestamp format is:

`YYYY-MM-DD_HH-MM-SS`

Main outputs:

- `segmentation_<year>_<timestamp>.xlsx` (or `segmentation_classification_...`)
- merged multi-year workbook: `segmentation_*_Multiple_Years_<timestamp>.xlsx` (if relevant)
- recording inventory: `recordings_metadata_<year>_<timestamp>.xlsx` (scan mode)
- summary workbook: `<main_output_stem>_summary.xlsx`

Summary columns include:

- `Year`
- `Total mice (pups)`
- `Total recordings`
- `Total syllables`
- `Mice with syllables detected`
- `Recordings with syllables`

## Model weights

Place CNN model under `models/` (bundled into desktop build), or override with:

- `USV_MODEL_PATH` = absolute path to model folder/file

If model loading fails, classification falls back to class `10`.

## Programmatic API

Use the pipeline without UI:

```python
from pipeline import execute_pipeline

primary_output, summary = execute_pipeline(
    folder_path="path/to/data",
    progress_callback=lambda p, msg, eta=None: print(f"{p:.1%} {msg}"),
    output_dir="outputs",
    years=["2015", "2018"],
    want_syllables_xlsx=True,
    want_metadata_xlsx=True,
    metadata_only=False,
    run_classification=True,
)
```

Returns:

- `primary_output`: primary generated workbook path
- `summary`: `RunSummary` with counters, output list, and errors

## Project structure

```text
segmentation-app/
  app.py                       # Desktop UI
  pipeline.py                  # Multi-year orchestration engine
  metadata_export.py           # Inventory + summary workbook writers
  preprocessing/
    steps/                     # Pipeline processing stages
    utils/                     # I/O, path matching, metadata normalization
    legacy/                    # Legacy research computation modules
  docs/
    BUILD.md                   # Packaging/build instructions
```

## Documentation map

- `docs/USER_GUIDE.md` - UI usage walkthrough
- `docs/ARCHITECTURE.md` - module architecture and execution model
- `docs/PIPELINE_REFERENCE.md` - pipeline stages, inputs/outputs, and key data models
- `docs/DEVELOPMENT.md` - development workflow, code conventions, and release checklist
- `docs/TROUBLESHOOTING.md` - common failures and diagnostics
- `docs/BUILD.md` - packaging for Windows and macOS
