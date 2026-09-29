#!/bin/bash
# Omni Linux 打包脚本:一条命令产出 dist/Omni/Omni(onedir,双击运行)
#
# 依赖:conda 环境 omni(内含 kivy/numpy/numpy-stl/pyinstaller)
set -e
cd "$(dirname "$0")/.."

CONDA_PY=python
if command -v conda >/dev/null 2>&1; then
    CONDA_PY="conda run -n omni python"
fi

echo "==> 清理旧构建"
rm -rf build dist

echo "==> PyInstaller 打包(kivy hooks + 资源文件)"
$CONDA_PY -m PyInstaller --noconfirm --clean packaging/omni.spec

echo "==> 打包完成: dist/Omni/Omni"
ls -lh dist/Omni/Omni
