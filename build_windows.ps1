# Build Windows portable EXE (requires venv with tensorflow + pyinstaller)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Error "Install PyInstaller in the active environment: pip install pyinstaller"
}
pyinstaller --noconfirm SegmentationAppPortable.spec
Write-Host "Done. See dist/"
