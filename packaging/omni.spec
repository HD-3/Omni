# -*- mode: python ; coding: utf-8 -*-
# Omni PyInstaller 打包配置(onedir:dist/Omni/Omni 双击运行)
#
# 用法(在项目根目录):
#   conda run -n omni python -m PyInstaller packaging/omni.spec
#
# 说明:PyInstaller 6 不再通过 Analysis(hookspath=...) 加载第三方 hooks
# 目录,这里直接调用 Kivy 官方 pyinstaller_hooks 模块,等效于加载
# hook-kivy.py(隐藏导入 + 数据文件 + 运行时 hook)。

import glob
import os
import sys

project_root = os.path.abspath(os.path.join(SPECPATH, '..'))

import kivy  # noqa
from kivy.tools.packaging.pyinstaller_hooks import (
    add_dep_paths, datas as kivy_datas, get_deps_minimal, runtime_hooks,
)

add_dep_paths()

# Omni 用不到视频/音频/摄像头/拼写:排除以精简并避开 GStreamer。
# 注意:clipboard 不能排除——TextInput 初始化会 import kivy.core.clipboard,
# 排除后冻结包启动即崩 ModuleNotFoundError(实测)。其 Linux 后端
# (sdl2/xclip/xsel)无重依赖,体积可忽略,保留默认。
kivy_deps = get_deps_minimal(video=None, audio=None, camera=None,
                             spelling=None)

datas = [
    (os.path.join(project_root, 'omni.kv'), '.'),
    (os.path.join(project_root, 'visualisation', 'shaders'),
     'visualisation/shaders'),
    (os.path.join(project_root, 'visualisation', 'assets'),
     'visualisation/assets'),
    (os.path.join(project_root, 'tutorials', 'steps.json'), 'tutorials'),
    # 自带剪贴板工具(xclip/xsel):Kivy 剪贴板探测靠 subprocess 在
    # PATH 里找,main.py 启动时把 tools/ 加进 PATH
    (os.path.join(project_root, 'tools'), 'tools'),
] + kivy_datas

# conda 环境的 SDL2 动态库(ctypes 运行时加载,静态分析找不到,手动收集)
binaries = []
env_lib = os.path.join(sys.base_prefix, 'lib')
for pattern in ('libSDL2-2.0.so*', 'libSDL2_image-2.0.so*',
                'libSDL2_ttf-2.0.so*', 'libSDL2_mixer-2.0.so*'):
    for f in glob.glob(os.path.join(env_lib, pattern)):
        binaries.append((f, '.'))

# 图像 provider 显式带上,避免默认 provider 探测遗漏
hiddenimports = ['numpy', 'stl'] + kivy_deps['hiddenimports'] + [
    'kivy.core.image.img_sdl2', 'kivy.core.image.img_pil',
    'kivy.core.image.img_tex', 'kivy.core.image.img_dds',
]

a = Analysis(
    [os.path.join(project_root, 'main.py')],
    pathex=[project_root],
    binaries=binaries + kivy_deps.get('binaries', []),
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks(),
    excludes=['tkinter', 'matplotlib', 'PyQt5', 'PySide2']
             + kivy_deps.get('excludes', []),
    noarchive=False,
)

# 不打包系统 X11/桌面库:conda 环境里的这些库要求较新 glibc(本机
# 2.35),在 glibc 更老的机器上(如 Ubuntu 20.04 的 2.31)加载会报
# "GLIBC_2.33 not found" 直接崩(窗口 provider 初始化失败)。这些库
# 目标机系统必带(deb 的 Depends 已声明),删掉让 loader 落到系统版,
# 版本随系统 glibc 天然匹配。
_SYSTEM_LIBS = {
    'libX11.so.6', 'libXau.so.6', 'libXdmcp.so.6', 'libXext.so.6',
    'libXmu.so.6', 'libXrender.so.1', 'libXt.so.6', 'libICE.so.6',
    'libSM.so.6', 'libuuid.so.1', 'libuuid.so', 'libbsd.so.0',
    'libmd.so.0', 'libmtdev.so.1',
}
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]) not in _SYSTEM_LIBS]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Omni',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无终端窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Omni',
)
