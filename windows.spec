# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'main.py')], pathex=[str(root)], binaries=[],
    datas=[(str(root / 'assets'), 'assets')], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtPdf', 'PySide6.QtOpenGL', 'numpy'],
    noarchive=False, optimize=1,
)

# 只使用 Widgets 光栅画布、SVG 与 JPEG。剔除虚拟键盘、PDF、
# Quick/QML、软件 OpenGL、网络插件与其他语言翻译。
plugins = {'qwindows.dll', 'qoffscreen.dll', 'qmodernwindowsstyle.dll',
           'qsvgicon.dll', 'qsvg.dll', 'qjpeg.dll', 'qico.dll'}
unused_qt = {'opengl32sw.dll', 'Qt6Quick.dll', 'Qt6Qml.dll', 'Qt6QmlModels.dll',
             'Qt6QmlWorkerScript.dll', 'Qt6Pdf.dll', 'Qt6OpenGL.dll',
             'Qt6VirtualKeyboard.dll', 'Qt6SvgWidgets.dll', 'Qt6Network.dll', 'QtNetwork.pyd'}

def needed(entry):
    name = entry[0].replace('\\', '/')
    base = name.rsplit('/', 1)[-1]
    if name.startswith('PySide6/'):
        if '/plugins/' in name:
            return base in plugins
        if '/translations/' in name:
            return base == 'qtbase_zh_CN.qm'
        if base in unused_qt:
            return False
    return True

a.binaries = [entry for entry in a.binaries if needed(entry)]
a.datas = [entry for entry in a.datas if needed(entry)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name='EasyDrawFlat',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    version=str(root / 'version_info.txt'), icon=[str(root / 'EasyDrawFlat.ico')],
)
