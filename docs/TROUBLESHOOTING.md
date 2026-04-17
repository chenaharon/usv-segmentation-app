# Troubleshooting

Common issues and quick diagnostics for `segmentation-app`.

## App does not start

Symptoms:

- immediate traceback on `python app.py`

Checks:

- activate the correct venv
- ensure `pip install -r requirements.txt` completed
- verify Python version compatibility with installed TensorFlow build

## Model classification not running (all class 10)

Symptoms:

- syllable classification column is all `10`
- logs mention missing model or classification failure

Checks:

- verify model files exist under `models/`
- set `USV_MODEL_PATH` to a valid model path
- inspect run logs for model load exceptions

## Metadata workbook not detected

Symptoms:

- year row shows missing metadata
- recordings not found from metadata mode

Checks:

- verify required metadata columns exist (or compatible aliases)
- ensure workbook is not temporary (`~$...`) or locked by Excel
- manually select metadata workbook for the year from UI

## Progress appears stuck

Symptoms:

- progress remains on same percentage for a while

Explanation:

- pipeline stages vary in duration (segmentation, spectrogram generation, classification)
- percent updates are coarse by design for smoother UX

Checks:

- open log panel and confirm new entries appear
- check elapsed time keeps increasing

## Stop/Pause not immediate

Explanation:

- cancellation/pause checks are cooperative and occur between processing chunks
- current long operation may need to finish before control change is visible

## Excel write errors / permission denied

Symptoms:

- save failure, permission denied, file in use

Checks:

- close the target workbook in Excel
- verify output folder write permissions
- retry in a clean output directory

## Packaged app issues

For build/distribution failures:

- review `docs/BUILD.md`
- for Windows installer, ensure `iscc` (Inno Setup compiler) is available in `PATH`
- for macOS, build on macOS and consider code-sign/notarization for external distribution

## Getting actionable logs

When reporting a bug, include:

- app version
- selected mode/options
- input folder layout type
- relevant log excerpt
- full traceback (if any)
