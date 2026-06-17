# PyInstaller spec — YouTube Downloader
# 사용법: pyinstaller ytdownloader.spec
#
# ffmpeg 번들 방법 (선택):
#   ffmpeg.exe를 src/ 폴더에 복사 후 빌드하면 EXE 내부에 번들됨 (~240MB)
#   번들하지 않으면 YTDownloader.exe 옆에 ffmpeg.exe를 두면 됨

import os

block_cipher = None

# ffmpeg.exe가 src/ 폴더에 있으면 번들에 포함
_ffmpeg_src = os.path.join(SPECPATH, 'ffmpeg.exe')
_ffmpeg_binaries = [(_ffmpeg_src, 'ffmpeg')] if os.path.exists(_ffmpeg_src) else []

a = Analysis(
    ['downloader.py'],
    pathex=[],
    binaries=_ffmpeg_binaries,
    datas=[],
    hiddenimports=[
        'yt_dlp',
        'yt_dlp.extractor',
        'yt_dlp.postprocessor',
        'yt_dlp.utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='YTDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # GUI 앱 — 콘솔 창 숨김 (디버그 시 True로 변경)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
