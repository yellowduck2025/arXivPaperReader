# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = [('F:/work_software/anaconda/envs/build/Library/bin/libssl-3-x64.dll', '.'), ('F:/work_software/anaconda/envs/build/Library/bin/libcrypto-3-x64.dll', '.'), ('F:/work_software/anaconda/envs/build/Library/bin/tcl86t.dll', '.'), ('F:/work_software/anaconda/envs/build/Library/bin/tk86t.dll', '.')]
hiddenimports = ['src.searcher', 'src.downloader', 'src.parser', 'src.extractor', 'src.csv_writer', 'src.stats', 'src.models', 'src.config', 'src.translator', 'src.orchestrator', 'requests', 'deep_translator']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='arXivPaperReader',
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
