# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller MOB.spec

EXCLUDES = [
    'matplotlib', 'scipy', 'numpy', 'pandas', 'PyQt5', 'PyQt6',
    'PySide2', 'PySide6', 'IPython', 'jupyter', 'notebook'
]

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('icon.png', '.'),
    ],
    hiddenimports=[
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.backends.openssl.backend',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

UPX_EXCLUDE = [
    'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll',
    'python3*.dll', 'python*.dll', '_ssl.pyd',
]

exe = EXE(
    pyz,
    a.scripts, [],
    exclude_binaries=True,
    name='MOB',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=UPX_EXCLUDE,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=UPX_EXCLUDE,
    name='MOB',
)
