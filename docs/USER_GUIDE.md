# User Guide

This guide explains how to operate the desktop app (`app.py`) from folder selection to final outputs.

## 1. Start the app

```bash
python app.py
```

## 2. Select folders

- **Data Folder**: root dataset path (single year or multi-year container).
- **Output Folder**: optional custom output path. If left empty, the app uses its default output path internally.

## 3. Choose processing mode

- **Segmentation + Classification**
  - full flow (segmentation, feature enrichment, CNN syllable classes)
- **Segmentation**
  - segmentation and enrichment without CNN class assignment

Recording scan mode:

- **Without Recordings Files Scan**
- **With Recordings Files Scan**
- **Only Recordings Files Scan**

## 4. Select years and subfolders

- Use year checkboxes to include/exclude years.
- Expand year trees and select only relevant subfolders if needed.
- `Select All` / `Deselect All` control all year and tree selections.

During active processing, selection widgets are locked to prevent inconsistent runtime changes.

## 5. Metadata availability

For each year row, the UI shows whether metadata was auto-detected.

If metadata is missing, click the prompt on the year row to manually select a metadata workbook for that year.

## 6. Run controls

- **Run** starts processing.
- While running, the same button toggles **Pause/Resume**.
- **Stop** requests graceful cancellation.
- **Show Logs / Hide Logs** toggles the log panel.
- **Outputs** can be opened while a run is active.
- **Results** is enabled after run completion when summary data exists.

## 7. Progress and status

- Progress bar shows coarse-grained percent updates.
- Status line shows elapsed time while processing.
- Detailed stage messages appear in the log panel.

## 8. Result artifacts

Typical files in output folder:

- segmentation workbook (`segmentation_...xlsx` or `segmentation_classification_...xlsx`)
- optional recording inventory workbook (`recordings_metadata_...xlsx`)
- summary workbook (`*_summary.xlsx`)

For multi-year runs, per-year segmentation files may be merged into one `Multiple_Years` workbook.

## 9. Tips

- Prefer selecting only needed years/subfolders to reduce runtime.
- Ensure model files are available if using classification mode.
- Keep metadata files closed in Excel during processing to avoid lock errors.
