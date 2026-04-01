# Building SegmentationApp for distribution

All build steps run from the `segmentation-app` directory with a Python 3.10+ venv that has `requirements.txt` plus **TensorFlow** (and other scientific stack) installed for the CNN.

## Windows — portable one-file EXE

```powershell
pip install -r requirements.txt pyinstaller
pyinstaller SegmentationAppPortable.spec
```

Output: `dist/SegmentationAppPortable.exe` (single file; first launch may be slow while extracting). The EXE uses `assets/app_icon.ico` (generated from `app_icon.png`); rebuild the `.ico` after changing the PNG if needed.

For a **folder** build (faster startup), use a separate `.spec` with `EXE(..., exclude_binaries=True)` + `COLLECT(...)` or PyInstaller `--onedir`.

## Windows — installer (Inno Setup)

1. Build the portable EXE (or onedir folder) as above.
2. Install [Inno Setup](https://jrsoftware.org/isinfo.php).
3. Open `installer/SegmentationApp.iss` in Inno Setup, adjust `Source` paths if your output folder differs, then Compile.

The script creates Start Menu / Desktop shortcuts and an uninstaller.

## macOS — `.app` bundle

Build **on a Mac** (Apple Silicon or Intel matching your targets):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pyinstaller
pyinstaller SegmentationAppPortable.spec
```

Gatekeeper: users may need **Right-click → Open** the first time unless you **codesign** and **notarize** with an Apple Developer ID (optional for lab distribution).

## CI (optional)

Use GitHub Actions with `windows-latest` and `macos-latest` jobs running the same PyInstaller command and uploading `dist/` artifacts.

## Size notes

TensorFlow and OpenCV (via legacy code) dominate bundle size. The `SegmentationAppPortable.spec` `excludes` list trims test-only packages; do **not** remove `models/`, `preprocessing/`, or `assets/` (window icon) from `datas`.
