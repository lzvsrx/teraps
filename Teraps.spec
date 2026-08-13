# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['teraps.py'],
    pathex=[],
    binaries=[],
    datas=[('assets\\teraps.ico', 'assets'), ('assets\\teraps_avatar.png', 'assets')],
    hiddenimports=['edge_tts', 'aiohttp', 'speech_recognition', 'sounddevice', 'cffi', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5', 'comtypes.stream'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'pyarrow', 'av', 'onnxruntime', 'torch', 'tensorflow', 'transformers', 'huggingface_hub', 'faster_whisper', 'whisper'],
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
    name='Teraps',
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
    icon=['assets\\teraps.ico'],
)
