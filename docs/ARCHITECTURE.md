# Architecture Overview

This document describes the runtime architecture of `segmentation-app`.

## High-level layers

## 1) UI layer (`app.py`)

- Renders the desktop interface using `customtkinter`.
- Builds year/folder selection trees.
- Manages run controls (run, pause/resume, stop).
- Receives progress/events from background worker thread.
- Writes user-facing status and logs.

## 2) Orchestration layer (`pipeline.py`)

- Defines `PipelineOptions` and `RunSummary`.
- Discovers year roots and selected subfolder filters.
- Runs per-year processing pipelines.
- Produces final output paths and summary stats.
- Merges multi-year workbooks when relevant.

## 3) Processing stages (`preprocessing/steps`)

- `segmentation.py`: syllable segmentation and initial workbook rows
- `read_segmentation.py`: normalized read-back of segmentation sheet
- `compute_basic_features.py`: ISI/start-end frequency features
- `classification.py`: model loading, inference, post-processing
- `enrich_columns.py`: final derived columns and ordering
- `extract_features.py`: optional offline feature extraction utilities

## 4) Utilities (`preprocessing/utils`)

- metadata header normalization and alias support
- path resolution and fuzzy matching for recording paths
- logging and CLI utilities (legacy non-UI flows)

## 5) Legacy computation modules (`preprocessing/legacy`)

- algorithmic implementations used by current steps
- kept as imported computational dependencies, not as direct UI entrypoints

## Threading model

- UI runs on the main Tk thread.
- Pipeline execution runs on a worker thread.
- Worker emits structured events (`progress`, `done`, `error`, `stopped`) through a thread-safe queue.
- UI polls the queue on a timer and updates controls safely from the main thread.

## Data flow summary

1. User selects data root, years, and options in UI.
2. UI computes subfolder filters and metadata overrides.
3. Worker calls `execute_pipeline(...)`.
4. Pipeline resolves metadata rows to WAV files, processes selected recordings, and writes workbooks.
5. Worker posts final summary and outputs back to UI.

## Output model

- Segmentation workbook: syllable rows and derived columns.
- Metadata/recording inventory workbook: per recording path + status.
- Summary workbook: per-year aggregate counters.

## Packaging boundary

Runtime packaging includes:

- `app.py`
- `pipeline.py`
- `metadata_export.py`
- `preprocessing/`
- `models/`
- `assets/`

See `docs/BUILD.md` for build details.
