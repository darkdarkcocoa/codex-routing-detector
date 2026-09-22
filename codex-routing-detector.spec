# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['codex_routing_webui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['webview.platforms.winforms', 'webview.platforms.edgechromium'],
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
    name='codex-routing-detector',
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
    icon=['docs/icon.ico'],
)
