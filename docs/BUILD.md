# Building SegmentationApp for distribution

All build steps run from the `segmentation-app` directory with a Python 3.10+ venv that has `requirements.txt` plus **TensorFlow** (and other scientific stack) installed for the CNN.

## Artifact naming (do not overwrite older releases)

Use **versioned filenames** so `dist/` and `dist_installer/` can hold multiple builds side by side.

| Artifact | Filename pattern | Example |
|----------|-------------------|---------|
| Windows portable (one-file EXE) | `USV Segmentation (vVERSION) - Portable.exe` | `USV Segmentation (v1.0.2) - Portable.exe` |
| Windows installer (Inno Setup) | `USV Segmentation Setup (vVERSION).exe` | `USV Segmentation Setup (v1.0.2).exe` |
| macOS `.app` | Same stem as portable (`name=` in `SegmentationAppPortable.spec`) | `USV Segmentation (v1.0.2) - Portable.app` |
| macOS DMG (optional) | Same pattern as Windows installer | `USV Segmentation Setup (v1.0.2).dmg` |

The portable name comes from `name=` in `SegmentationAppPortable.spec`. The installer/DMG names are kept in `installer/SegmentationApp.iss` (`OutputBaseFilename`, driven by `#define MyAppVersion`) and `scripts/build_macos.sh`.

### Version bump checklist

When shipping a new version, update **the same version string** everywhere:

1. `app.py` — `APP_VERSION`
2. `SegmentationAppPortable.spec` — `name=` for the portable stem
3. `installer/SegmentationApp.iss` — `#define MyAppVersion` (installer output uses `USV Segmentation Setup (v{#MyAppVersion})`)
4. `scripts/build_windows.ps1` — `$PortableExeName` and `$InstallerExeName` (must match the files above)
5. `scripts/build_macos.sh` — `APP_NAME` and `DMG_NAME`

## Inno Setup compiler (`ISCC.exe`) on Windows

The **Start Menu** entry for “Inno Setup 6” is only a shortcut. The real command-line compiler is typically:

- **Per-user install (common):** `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`  
  Full path example: `C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe`
- **Machine-wide:** `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` or `C:\Program Files\Inno Setup 6\ISCC.exe`

`scripts/build_windows.ps1` resolves `ISCC.exe` automatically if `iscc` is not on `PATH` (same search order as above).

## Windows — portable one-file EXE

```powershell
pip install -r requirements.txt pyinstaller
pyinstaller SegmentationAppPortable.spec
```

Output: `dist/USV Segmentation (vVERSION) - Portable.exe` (single file; from `name=` in `SegmentationAppPortable.spec`; first launch may be slow while extracting). The EXE uses `assets/app_icon.ico` (generated from `app_icon.png`); rebuild the `.ico` after changing the PNG if needed.

## Windows — installer (onedir + Inno Setup)

The **installer does not wrap the onefile portable**. It ships a **separate PyInstaller onedir** bundle (`SegmentationAppInstaller.spec`): files live under `Program Files`, no full onefile extraction on every launch — usually **faster and more stable** for lab PCs. Download size may be similar or somewhat smaller than wrapping the same onefile (LZMA on many DLLs); the main win is runtime behavior.

```powershell
pip install -r requirements.txt pyinstaller
pyinstaller -y --distpath dist_installer_stage SegmentationAppInstaller.spec
```

`--distpath dist_installer_stage` keeps **`dist/` only for the portable one-file** (`SegmentationAppPortable.spec`). The onedir used by Inno lives under `dist_installer_stage/USV_Segmentation_Install/` (main executable: `USV_Segmentation.exe`). The Inno script expects that path (`#define InstallerStageRoot` in `installer/SegmentationApp.iss`).

Use `-y` (or delete `dist_installer_stage/USV_Segmentation_Install` first) if PyInstaller complains the output folder is not empty. Close any running copy of the versioned setup executable (e.g. `USV Segmentation Setup (v1.0.2).exe`) before recompiling Inno, or the old installer may be locked.

If you rename the `COLLECT` `name=` or the `EXE` `name=` in `SegmentationAppInstaller.spec`, update `#define InstallBuildDir` / `#define MyAppExeName` in `installer/SegmentationApp.iss`.

Then compile the installer:

1. Install [Inno Setup](https://jrsoftware.org/isinfo.php).
2. Open `installer/SegmentationApp.iss` in Inno Setup and **Compile** (or run `ISCC.exe` on that `.iss`, or use `scripts/build_windows.ps1`).

Output: `dist_installer/USV Segmentation Setup (vVERSION).exe`. Shortcuts and uninstaller are created by Inno.

## macOS — `.app` bundle

Build **on a Mac** (Apple Silicon or Intel matching your targets):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pyinstaller
pyinstaller SegmentationAppPortable.spec
```

Gatekeeper: users may need **Right-click → Open** the first time unless you **codesign** and **notarize** with an Apple Developer ID (optional for lab distribution).

Use `scripts/build_macos.sh` for a DMG named like the Windows installer (`USV Segmentation Setup (vVERSION).dmg`).

## CI (optional)

Use GitHub Actions with `windows-latest` and `macos-latest` jobs running the same PyInstaller command and uploading `dist/` artifacts.

## Size notes

TensorFlow and OpenCV (via legacy code) dominate bundle size. The `SegmentationAppPortable.spec` `excludes` list trims test-only packages; do **not** remove `models/`, `preprocessing/`, or `assets/` (window icon) from `datas`.
