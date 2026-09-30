# -*- mode: python ; coding: utf-8 -*-
# TokyoAme 打包配置（PyInstaller）
#
# 打包前（改过界面文字或图标时）：
#     python3 i18n/gen_ts.py      # 重新生成 .ts 并编译 .qm
#     python3 make_icon.py        # 重新生成 TokyoAme.icns
# 背景音乐放在 music/ 目录（来源与许可见 music/CREDITS.md），会一起打进包里。
# 打包：
#     pyinstaller TokyoAme.spec   # 结果在 dist/TokyoAme.app

from pathlib import Path


block_cipher = None

__version__ = '1.0.0'

project_dir = Path(SPECPATH)


def existing_datas(pattern, target):
    return [(str(path), target) for path in sorted(project_dir.glob(pattern))]


# 翻译文件放进 i18n/ 子目录（程序按 sys._MEIPASS/i18n 查找）；缺了就停下，免得打出一个切不了语言的包
missing_qm = [code for code in ('zh_CN', 'ja_JP') if not (project_dir / 'i18n' / ('tokyoame_%s.qm' % code)).exists()]
if missing_qm:
    raise SystemExit('missing i18n/tokyoame_%s.qm: run python3 i18n/gen_ts.py before pyinstaller' % ','.join(missing_qm))
datas = existing_datas('i18n/*.qm', 'i18n')
# 背景音乐（music/ 目录，程序按 sys._MEIPASS/music 查找；没有这个目录也能打包，只是没有音乐）
for pattern in ('music/*.ogg', 'music/*.mp3', 'music/*.m4a', 'music/*.wav', 'music/CREDITS.md'):
    datas += existing_datas(pattern, 'music')

bundle_icon = str(project_dir / 'TokyoAme.icns') if (project_dir / 'TokyoAme.icns').exists() else None

info_plist = {
    'NSHumanReadableCopyright': 'Copyright © 2026 Yixiang SHEN. All rights reserved.',
    'CFBundleVersion': '1',
    'CFBundleShortVersionString': __version__,
    'LSApplicationCategoryType': 'public.app-category.casual-games',
    'NSPrincipalClass': 'NSApplication',
    'LSMinimumSystemVersion': '13.0',
    'NSHighResolutionCapable': True,
    'ITSAppUsesNonExemptEncryption': False,
    'CFBundleDisplayName': 'TokyoAme',
    'CFBundleName': 'TokyoAme',
    'CFBundleDevelopmentRegion': 'en',
    'CFBundleLocalizations': ['en', 'zh_CN', 'ja'],
}

a = Analysis(
    [str(project_dir / 'ame.py')],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=['PyQt6.sip', 'PyQt6.QtMultimedia'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'tcl', 'tk'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 去掉用不到的 Qt 部件（约 15 MB）：PDF 模块和它的图片插件、Qt 自带的界面翻译。
# 注意别去掉 QtNetwork：背景音乐用的 QtMultimedia 依赖它。
_UNUSED_QT = ('QtPdf', 'libqpdf', 'Qt6/translations/')
a.binaries = [entry for entry in a.binaries if not any(key in entry[0] for key in _UNUSED_QT)]
a.datas = [entry for entry in a.datas if not any(key in entry[0] for key in _UNUSED_QT)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TokyoAme',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TokyoAme',
)
app = BUNDLE(
    coll,
    name='TokyoAme.app',
    icon=bundle_icon,
    info_plist=info_plist,
    bundle_identifier='com.ryanthehito.tokyoame',
    version=__version__,
)
