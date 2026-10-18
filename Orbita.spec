# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path

datas = []
datas += collect_data_files('tzdata')


a = Analysis(
    [str(Path(SPECPATH)/'orbita_entry.py')],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['tzdata'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PIL', 'numpy', 'pandas', 'matplotlib', 'scipy',
              'PySide6.QtVirtualKeyboard', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick'],
    noarchive=False,
    optimize=0,
)
# QtGui's generic plugin discovery otherwise includes unused Virtual Keyboard
# (GPL-only for open-source users) and the PDF image plugin. The application
# does not use either. Filter native transitive binaries as well as bindings.
blocked = ('virtualkeyboard', 'qt6pdf', 'qpdf.dll', 'qpdf.so', 'qpdf.dylib')
a.binaries = [entry for entry in a.binaries if not any(part in entry[0].lower() for part in blocked)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Orbita',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Orbita',
)
