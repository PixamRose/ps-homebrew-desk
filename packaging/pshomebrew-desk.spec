# -*- mode: python ; coding: utf-8 -*-
# Build on Windows:
#   pyinstaller packaging/pshomebrew-desk.spec
# Output: dist/PSHomebrewDesk/PSHomebrewDesk.exe

block_cipher = None

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('catalog/default.json', 'catalog'),
        ('version.json', '.'),
        ('assets/AppIcon.ico', 'assets'),
        ('assets/icon.png', 'assets'),
        ('assets/logo.png', 'assets'),
        ('payloads/README.txt', 'payloads'),
    ],
    hiddenimports=[
        'app',
        'desk',
        'desk.common',
        'desk.transfer',
        'desk.games',
        'desk.elfs',
        'desk.relapse',
        'desk.update_channel',
        'desk.companion',
        'desk.history',
        'desk.discord_hook',
        'desk.eden',
        'desk.orbit',
        'rarfile',
        'webview',
        'webview.platforms.edgechromium',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['vendor'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PSHomebrewDesk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/AppIcon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PSHomebrewDesk',
)
