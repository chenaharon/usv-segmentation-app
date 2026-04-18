# -*- mode: python ; coding: utf-8 -*-
# Onedir bundle for Windows installer (Inno Setup). Separate artifact from ``SegmentationAppPortable.spec`` (onefile).
# Run (use ``--distpath`` so ``dist/`` stays reserved for the portable one-file EXE):
#   pyinstaller -y --distpath dist_installer_stage SegmentationAppInstaller.spec
# Output: dist_installer_stage/USV_Segmentation_Install/USV_Segmentation.exe + dependencies (no temp extraction on each launch).

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
import os
import sys

datas = [('preprocessing', 'preprocessing'), ('models', 'models'), ('assets', 'assets')]
binaries = []
hiddenimports = ['utils', 'steps', 'legacy', 'metadata_export', 'pandas']
hiddenimports += collect_submodules('utils')
hiddenimports += collect_submodules('steps')
hiddenimports += collect_submodules('legacy')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('CTkMessagebox')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

app_icon = None
if sys.platform.startswith('win'):
    ico_path = os.path.join('assets', 'app_icon.ico')
    if os.path.exists(ico_path):
        app_icon = ico_path

a = Analysis(
    ['app.py'],
    pathex=['preprocessing'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'test',
        'tests',
        'pytest',
        'matplotlib.tests',
        'IPython',
        'notebook',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='USV_Segmentation',
    icon=app_icon,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='USV_Segmentation_Install',
)
