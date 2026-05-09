# -*- mode: python ; coding: utf-8 -*-
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
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('CTkMessagebox')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Use .ico on Windows only; macOS can use the default bundle icon in this spec.
app_icon = None
if sys.platform.startswith("win"):
    ico_path = os.path.join("assets", "app_icon.ico")
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
    a.binaries,
    a.datas,
    [],
    name='USV Segmentation (v1.0.2) - Portable',
    icon=app_icon,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
