#!/bin/bash
# Omni .deb 安装包构建:产出 dist/omni_<版本>_amd64.deb
#
# 用法(在项目根目录):
#   ./packaging/build_deb.sh              # 先重打 PyInstaller 包,再打 deb
#   ./packaging/build_deb.sh --skip-build # dist/Omni 已是最新,跳过 PyInstaller
#   VERSION=1.1.0 ./packaging/build_deb.sh --skip-build   # 覆盖版本号
#
# 说明:deb 内容 = dist/Omni 整个目录(装到 /opt/omni) + 桌面启动器 + 图标。
# 用户配置写在 ~/.omni/,与安装目录无关,升级包不会丢配置。
set -e
cd "$(dirname "$0")/.."

VERSION="${VERSION:-1.0.0}"
DEB_NAME="omni_${VERSION}_amd64.deb"
DEBROOT=packaging/debian

if [ "$1" != "--skip-build" ]; then
    ./packaging/build_linux.sh
fi

[ -x dist/Omni/Omni ] || { echo "错误: dist/Omni/Omni 不存在,请先跑 ./packaging/build_linux.sh"; exit 1; }

echo "==> 组装 deb 目录(opt/omni ← dist/Omni)"
rm -rf "$DEBROOT/opt"
mkdir -p "$DEBROOT/opt"
cp -r dist/Omni "$DEBROOT/opt/omni"

echo "==> 写入版本号 $VERSION"
sed -i "s/^Version:.*/Version: $VERSION/" "$DEBROOT/DEBIAN/control"
chmod 0755 "$DEBROOT/DEBIAN/postinst"

echo "==> 构建 $DEB_NAME"
mkdir -p dist
dpkg-deb --build --root-owner-group "$DEBROOT" "dist/$DEB_NAME"

echo "==> 完成: dist/$DEB_NAME"
ls -lh "dist/$DEB_NAME"
