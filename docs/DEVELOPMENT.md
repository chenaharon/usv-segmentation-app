# Development Guide

Guide for contributors working on `segmentation-app`.

## Local setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

## Core files

- `app.py` - desktop UI and worker-thread event handling
- `pipeline.py` - orchestration and multi-year processing
- `metadata_export.py` - metadata inventory + summary workbook writing
- `preprocessing/steps/*` - pipeline stages
- `preprocessing/utils/*` - metadata/path helpers and shared utilities

## Coding principles used in this project

- Keep UI updates on the main Tk thread.
- Keep heavy processing in worker thread + queue events.
- Prefer robust metadata/path normalization over strict string matches.
- Preserve backward compatibility of workbook schemas when possible.
- Add progress updates for long-running loops, but avoid noisy log spam.

## Safe change areas

Usually safe:

- UI text/layout behavior in `app.py`
- progress/status messaging
- output naming and summary ordering
- docs and build scripts

Requires extra validation:

- segmentation and feature extraction logic
- path normalization/identity key behavior
- metadata alias normalization
- CNN classification preprocessing assumptions

## Manual validation checklist

After substantial changes:

1. Launch app and verify startup without exceptions.
2. Select a data folder and verify year tree rendering.
3. Run a short segmentation task and confirm outputs are created.
4. Validate pause/resume/stop behavior.
5. Verify summary workbook columns/order.
6. Toggle show/hide logs and dark mode during a run.
7. Re-check packaging (Windows/macOS) if build-related files changed.

## Packaging workflow

Use:

- `scripts/build_windows.ps1`
- `scripts/build_macos.sh`

See `docs/BUILD.md` for details and prerequisites.

## Versioning

App version string is in `app.py` (`APP_VERSION`).

When shipping:

- bump version
- rebuild portable and installer artifacts
- verify docs are up to date
