# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None

# Đường dẫn tài nguyên cần đóng gói kèm theo ứng dụng
datas = [
    ('resources', 'resources'),
    ('core/tts_runner.py', 'core'),
]

# Các module lớn không sử dụng cần loại trừ để giảm dung lượng file exe
excludes = [
    'PySide6.QtWebEngine',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtQuick',
    'PySide6.QtQml',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.QtCharts',
    'PySide6.QtSpatialAudio',
    'tkinter',
    'unittest',
]

hiddenimports = [
    'core',
    'core.models',
    'core.profiles',
    'core.parser',
    'core.storage',
    'core.crawler',
    'core.importer',
    'core.spellchecker',
    'core.ai_checker',
    'core.merger',
    'core.reporter',
    'core.video_models',
    'core.video_renderer',
    'core.ffmpeg_utils',
    'core.utils',
    'core.tts_models',
    'core.tts_chunker',
    'core.tts_manifest',
    'core.tts_adapter',
    'core.tts_assembler',
    'core.tts_dictionary',
    'gui',
    'gui.main_window',
    'gui.widgets',
    'gui.dialogs',
    'gui.workers',
    'gui.video_tab',
    'gui.video_worker',
    'gui.tts_tab',
    'gui.tts_worker',
    'bs4',
    'lxml',
    'requests',
]

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Chế độ One-file Standalone Executable (.exe độc lập, tiện copy chia sẻ)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TruyenAudio',
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
