# USV Segmentation Desktop (`segmentation-app`)

Desktop pipeline for mouse USV recordings: segmentation, basic features, syllable classification (CNN), and enriched Excel output.

## Relation to `mouse-usv-asd-pipeline`

The repository **mouse-usv-asd-pipeline** is used only as a **reference** for behavior and step order. **This app does not modify that project.**  
When comparing preprocessing logic, treat `mouse-usv-asd-pipeline/src/preprocessing` as read-only; apply any fixes only under `segmentation-app/preprocessing`.

| Step | mouse-usv-asd-pipeline (`run_pipeline.py`) | segmentation-app |
|------|---------------------------------------------|------------------|
| Load metadata + WAVs | `prepare_recording_metadata` | `pipeline.py` (client folder, classic `metadata/` + `USV_Recordings/`, or WAV scan) |
| Segmentation | `run_segmentation` | In-process workbook + `segment_single_recording` |
| Read rows | `read_segmentation_results` | Same module |
| ISI + start/end frequency | `compute_basic_features` | Same (can load audio per recording to save RAM) |
| CNN classification | `run_classification` | Same (`Syl_Class_Vec` with `recordings_search_root`) |
| Enriched columns | `enrich_segmentation_columns` | Same |
| Per-file CSV features | `run_feature_extraction` | **Not** part of the default GUI pipeline (optional offline) |
| Aggregate `all_data.*` | `run_aggregated_feature_extraction` | **Not** in app default flow |

## Folder layouts

- **Client / year folder:** `2015/*.xlsx` metadata + tree `Mother_Genotype/Name_Genotype/day_n/sessionN/rec.wav` under the same year folder.
- **Classic dataset:** `metadata/*.xlsx` + `USV_Recordings/<year>/...`.

## Running

- **Developer:** `pip install -r requirements.txt`, then `python app.py`.
- **Programmatic:** `from pipeline import execute_pipeline` — returns `(primary_xlsx_path, RunSummary)`; optional kwargs: `output_dir`, `years`, `want_syllables_xlsx`, `want_metadata_xlsx`, `metadata_only`. Progress callback: `(progress, message, eta_seconds=None)`.
- **Packaged:** see `docs/BUILD.md` (Windows portable + installer, macOS `.app`).

## Outputs

Configurable in the UI:

1. **Syllable Excel** — one row per detected syllable with enriched columns (default on).
2. **Recording metadata Excel** — one row per metadata row with resolved WAV path, status, and optional syllable count (default on).

## Model weights

Place `model_weights.h6` under `models/` next to `app.py` / `pipeline.py` (or bundle in PyInstaller `datas`). The app resolves the model from the **install folder**, not from the current working directory, so runs from arbitrary folders (e.g. Downloads) still find it.

You can override with environment variable `USV_MODEL_PATH` (full path to `model_weights.h6`, or to a folder that contains it).

If the file is missing or classification fails, syllable numbers fall back to class `10` (undefined).

## Metadata Excel columns

Required columns match `METADATA_REQUIRED_COLUMNS` in `preprocessing/utils/io_utils.py`. If your sheet uses **Gender** / **gender** (or Hebrew **מין** / **מגדר**) instead of **Sex**, it is normalized automatically when reading.
