param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$PortableExeName = "USV Segmentation (v1.0.2) - Portable.exe"
# Must match OutputBaseFilename (+ .exe) in installer/SegmentationApp.iss.
$InstallerExeName = "USV Segmentation Setup (v1.0.2).exe"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Step "Installing build dependencies"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

Write-Step "Cleaning previous portable output"
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

Write-Step "Building portable EXE"
pyinstaller "SegmentationAppPortable.spec" --noconfirm --clean

$portableExePath = Join-Path "dist" $PortableExeName
if (-not (Test-Path $portableExePath)) {
    throw "Portable build failed: $portableExePath was not produced."
}

Write-Step "Portable build complete: $portableExePath"

if ($SkipInstaller) {
    Write-Host "Installer step skipped." -ForegroundColor Yellow
    exit 0
}

Write-Step "Building installer with Inno Setup"
function Resolve-IsccPath {
    $cmd = Get-Command "iscc" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}
$isccExe = Resolve-IsccPath
if (-not $isccExe) {
    throw "Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 or add iscc to PATH, or run with -SkipInstaller."
}
Write-Host "Using: $isccExe" -ForegroundColor DarkGray
& $isccExe "installer/SegmentationApp.iss"

if (-not (Test-Path "dist_installer")) {
    throw "Installer build failed: dist_installer folder was not produced."
}

$installerPath = Join-Path "dist_installer" $InstallerExeName
if (-not (Test-Path $installerPath)) {
    throw "Installer build failed: $installerPath was not produced."
}

Write-Step "Installer build complete: $installerPath"
